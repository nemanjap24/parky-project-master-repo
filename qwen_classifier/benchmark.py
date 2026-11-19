from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from qwen_classifier.models import ClassificationInput
from scraper.output import read_observations

from .client import QwenClassifier

MAX_PRODUCTS = 10_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark sequential one-product Qwen requests using products from a scraper JSONL file"
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="Scraper observations JSONL file")
    parser.add_argument(
        "--count",
        type=int,
        help=f"Number of classifications to run (1-{MAX_PRODUCTS}); defaults to the input record count",
    )
    parser.add_argument(
        "--repeat-input",
        action="store_true",
        help="Cycle through the input records when --count exceeds the number of records",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Optional pause between requests (default: 0; requests are still strictly sequential)",
    )
    parser.add_argument("--progress-every", type=int, default=10, help="Progress interval in requests")
    parser.add_argument("--report", type=Path, help="Optional path for the JSON benchmark report")
    args = parser.parse_args(argv)

    if args.count is not None and not 1 <= args.count <= MAX_PRODUCTS:
        parser.error(f"--count must be between 1 and {MAX_PRODUCTS}")
    if not math.isfinite(args.delay_seconds) or not 0 <= args.delay_seconds <= 60:
        parser.error("--delay-seconds must be between 0 and 60")
    if args.progress_every < 1:
        parser.error("--progress-every must be at least 1")
    return args


def _build_workload(
    products: Sequence[ClassificationInput],
    count: int | None,
    repeat_input: bool,
) -> list[ClassificationInput]:
    if not products:
        raise ValueError("The input JSONL contains no products to classify")

    target_count = len(products) if count is None else count
    if not 1 <= target_count <= MAX_PRODUCTS:
        raise ValueError(f"Classification count must be between 1 and {MAX_PRODUCTS}")
    if target_count > len(products) and not repeat_input:
        raise ValueError(
            f"Requested {target_count} classifications but the input has {len(products)} records; "
            "provide more data or pass --repeat-input to cycle through it"
        )
    return [products[index % len(products)] for index in range(target_count)]


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil(percentile * len(ordered)) - 1
    return round(ordered[max(0, index)], 3)


def benchmark(
    products: Sequence[ClassificationInput],
    classifier: QwenClassifier,
    delay_seconds: float = 0,
    progress_every: int = 10,
) -> dict[str, Any]:
    started = time.perf_counter()
    latencies: list[float] = []
    failure: dict[str, Any] | None = None

    for index, product in enumerate(products, start=1):
        request_started = time.perf_counter()
        try:
            result = classifier.classify([product])
            if len(result) != 1:
                raise RuntimeError(f"Expected one classification, received {len(result)}")
        except (RuntimeError, ValueError) as exc:
            failure = {"product_index": index, "error": str(exc)}
            break

        latencies.append(time.perf_counter() - request_started)
        if index % progress_every == 0 or index == len(products):
            print(f"Completed {index}/{len(products)} classifications", file=sys.stderr)
        if index < len(products) and delay_seconds:
            time.sleep(delay_seconds)

    elapsed = time.perf_counter() - started
    successful = len(latencies)
    return {
        "model": classifier.model_name,
        "prompt_version": classifier.prompt_version,
        "requested_products": len(products),
        "completed_products": successful,
        "failed_product": None if failure is None else failure["product_index"],
        "error": None if failure is None else failure["error"],
        "requests_in_flight": 1,
        "products_per_request": 1,
        "delay_seconds": delay_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "products_per_second": round(successful / elapsed, 3) if elapsed else None,
        "latency_seconds": {
            "min": round(min(latencies), 3) if latencies else None,
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        observations = read_observations(args.input)
        missing_names = sum(not observation.name for observation in observations)
        if missing_names:
            raise ValueError(f"{args.input} contains {missing_names} observation(s) without a product name")

        source_products = [
            ClassificationInput(name=observation.name, retailer_category_path=observation.retailer_category_path)
            for observation in observations
            if observation.name is not None
        ]
        workload = _build_workload(source_products, args.count, args.repeat_input)

        with QwenClassifier() as classifier:
            report = benchmark(
                workload,
                classifier,
                delay_seconds=args.delay_seconds,
                progress_every=args.progress_every,
            )

        report["input_file"] = str(args.input)
        report["input_records"] = len(source_products)
        report["input_repeated"] = len(workload) > len(source_products)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        print(rendered)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
        return 1 if report["error"] else 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
