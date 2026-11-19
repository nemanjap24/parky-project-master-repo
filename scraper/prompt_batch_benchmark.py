from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qwen_classifier.client import QwenClassifier
from qwen_classifier.config import get_settings
from qwen_classifier.models import ClassificationInput
from scraper.output import JsonlWriter

from .config import get_scraper_settings
from .crawler import CrawlError
from .delay_benchmark import DelayMeasuringCrawler
from .models import ProductObservation
from .pipeline import ScrapingPipeline

PRODUCT_COUNT = 100
REQUEST_DELAY_SECONDS = 0.5
BATCH_SIZES = (5, 10, 15)


def _batches(items: list[ClassificationInput], size: int) -> list[list[ClassificationInput]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)], 3)


def _empty_page_reason(product: ProductObservation) -> str | None:
    if not product.name and product.shelf_price is None:
        return "No product name or shelf price was extracted"
    return None


def _page_failure_type(error: Exception) -> str:
    if isinstance(error, CrawlError) and str(error).startswith("Rendered page was empty:"):
        return "empty_page"
    return "scrape_error"


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _classification_summary(
    batch_size: int,
    completed_products: int,
    latencies: list[float],
    elapsed_seconds: float,
    categories: Counter[str],
    name_mismatches: int,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "batch_size": batch_size,
        "requested_products": PRODUCT_COUNT,
        "completed_products": completed_products,
        "request_count": len(requests),
        "successful_request_count": len(latencies),
        "failed_request_count": sum(request["status"] == "failed" for request in requests),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "products_per_second": (
            round(completed_products / elapsed_seconds, 3) if elapsed_seconds else None
        ),
        "name_mismatch_count": name_mismatches,
        "request_latency_seconds": {
            "min": round(min(latencies), 3) if latencies else None,
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "returned_categories": dict(categories),
        "requests": requests,
    }


async def run_benchmark(
    report_path: Path,
    products_path: Path,
    seed: int = 42,
) -> tuple[dict[str, Any], int]:
    scraper_settings = replace(
        get_scraper_settings(),
        request_delay_seconds=REQUEST_DELAY_SECONDS,
        classification_enabled=False,
    )
    qwen_settings = get_settings()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-prompt-benchmark"
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "product_source": "random sample from Kosik public product sitemap",
        "random_seed": seed,
        "requested_products": PRODUCT_COUNT,
        "scraper_request_delay_seconds": REQUEST_DELAY_SECONDS,
        "classification_batch_sizes": list(BATCH_SIZES),
        "planned_classification_requests": sum(
            math.ceil(PRODUCT_COUNT / batch_size) for batch_size in BATCH_SIZES
        ),
        "planned_classification_results": PRODUCT_COUNT * len(BATCH_SIZES),
        "classification_requests_are_sequential": True,
        "products_output": str(products_path),
        "status": "running",
        "scraping": {"status": "pending", "pages": []},
        "classification": {
            "status": "pending",
            "model": qwen_settings.model,
            "timeout_seconds": qwen_settings.timeout_seconds,
            "prompt_version": None,
            "batch_runs": [],
        },
    }
    _write_report(report_path, report)

    crawler = DelayMeasuringCrawler(settings=scraper_settings)
    pipeline = ScrapingPipeline(crawler=crawler, settings=scraper_settings, run_id=run_id)
    discovery_started = time.perf_counter()
    try:
        available_urls = await crawler.discover_product_urls()
        if len(available_urls) < PRODUCT_COUNT:
            raise RuntimeError(
                f"Product sitemap returned only {len(available_urls)} unique URLs; "
                f"{PRODUCT_COUNT} are required"
            )
        selected_urls = random.Random(seed).sample(available_urls, PRODUCT_COUNT)
    except Exception as exc:
        report["status"] = "failed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["failure"] = {"stage": "discovery", "error": f"{type(exc).__name__}: {exc}"}
        report["scraping"] = {
            "status": "failed",
            "discovery_elapsed_seconds": round(time.perf_counter() - discovery_started, 3),
            "error": report["failure"]["error"],
            "pages": [],
        }
        _write_report(report_path, report)
        return report, 1

    observations: list[ProductObservation] = []
    scrape_started = time.perf_counter()
    report["scraping"] = {
        "status": "running",
        "discovery_elapsed_seconds": round(time.perf_counter() - discovery_started, 3),
        "available_unique_urls": len(available_urls),
        "selected_url_count": len(selected_urls),
        "pages": [],
    }
    _write_report(report_path, report)

    try:
        with JsonlWriter(products_path) as writer:
            for index, url in enumerate(selected_urls, start=1):
                crawler.last_delay_wait_seconds = 0.0
                page_started = time.perf_counter()
                try:
                    product = await pipeline.scrape(url, classify=False)
                except Exception as exc:
                    elapsed = time.perf_counter() - page_started
                    failure_type = _page_failure_type(exc)
                    page_result = {
                        "index": index,
                        "url": url,
                        "status": failure_type,
                        "wall_seconds": round(elapsed, 3),
                        "request_delay_wait_seconds": round(crawler.last_delay_wait_seconds, 3),
                        "page_processing_seconds": round(
                            max(0.0, elapsed - crawler.last_delay_wait_seconds), 3
                        ),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    report["scraping"]["pages"].append(page_result)
                    raise RuntimeError(f"{failure_type} at product {index}: {exc}") from exc

                elapsed = time.perf_counter() - page_started
                empty_reason = _empty_page_reason(product)
                page_result = {
                    "index": index,
                    "url": url,
                    "product_name": product.name,
                    "status": "empty_page" if empty_reason else "success",
                    "wall_seconds": round(elapsed, 3),
                    "request_delay_wait_seconds": round(crawler.last_delay_wait_seconds, 3),
                    "page_processing_seconds": round(
                        max(0.0, elapsed - crawler.last_delay_wait_seconds), 3
                    ),
                    "warning_codes": product.extraction.warnings,
                }
                data_issue = empty_reason or (
                    "Product name was not extracted" if not product.name else None
                )
                if data_issue:
                    issue_type = "empty_page" if empty_reason else "missing_product_name"
                    page_result["status"] = issue_type
                    page_result["error"] = data_issue
                report["scraping"]["pages"].append(page_result)
                writer.write(product)

                if data_issue:
                    raise RuntimeError(f"{issue_type} at product {index}: {data_issue}")
                observations.append(product)
                if index % 10 == 0:
                    print(f"Scraped {index}/{PRODUCT_COUNT} products")
                    _write_report(report_path, report)
    except Exception as exc:
        report["status"] = "failed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["failure"] = {"stage": "scraping", "error": str(exc)}
        report["scraping"]["status"] = "failed"
        report["scraping"]["completed_products"] = len(observations)
        report["scraping"]["elapsed_seconds"] = round(time.perf_counter() - scrape_started, 3)
        _write_report(report_path, report)
        return report, 1

    report["scraping"]["status"] = "completed"
    report["scraping"]["completed_products"] = len(observations)
    report["scraping"]["elapsed_seconds"] = round(time.perf_counter() - scrape_started, 3)
    report["scraping"]["mean_page_seconds"] = round(
        statistics.mean(page["wall_seconds"] for page in report["scraping"]["pages"]), 3
    )
    report["scraping"]["mean_request_delay_wait_seconds"] = round(
        statistics.mean(page["request_delay_wait_seconds"] for page in report["scraping"]["pages"]),
        3,
    )
    _write_report(report_path, report)

    inputs = [
        ClassificationInput(name=product.name, retailer_category_path=product.retailer_category_path)
        for product in observations
        if product.name is not None
    ]
    report["classification"]["status"] = "running"
    classification_started = time.perf_counter()
    with QwenClassifier(settings=qwen_settings) as classifier:
        report["classification"]["prompt_version"] = classifier.prompt_version
        for batch_size in BATCH_SIZES:
            batches = _batches(inputs, batch_size)
            latencies: list[float] = []
            categories: Counter[str] = Counter()
            name_mismatches = 0
            requests: list[dict[str, Any]] = []
            completed_products = 0
            batch_run: dict[str, Any] = {
                "batch_size": batch_size,
                "status": "running",
                "requests": requests,
            }
            report["classification"]["batch_runs"].append(batch_run)
            batch_started = time.perf_counter()

            for batch_index, batch in enumerate(batches, start=1):
                request_started = time.perf_counter()
                try:
                    results = classifier.classify(batch)
                except Exception as exc:
                    elapsed = time.perf_counter() - request_started
                    requests.append(
                        {
                            "batch_index": batch_index,
                            "product_count": len(batch),
                            "latency_seconds": round(elapsed, 3),
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    batch_run["status"] = "failed"
                    batch_run["failure"] = {
                        "batch_index": batch_index,
                        "error": requests[-1]["error"],
                    }
                    batch_run.update(
                        _classification_summary(
                            batch_size,
                            completed_products,
                            latencies,
                            time.perf_counter() - batch_started,
                            categories,
                            name_mismatches,
                            requests,
                        )
                    )
                    batch_run["status"] = "failed"
                    report["classification"]["status"] = "failed"
                    report["classification"]["elapsed_seconds"] = round(
                        time.perf_counter() - classification_started, 3
                    )
                    report["status"] = "failed"
                    report["finished_at"] = datetime.now(timezone.utc).isoformat()
                    report["failure"] = {
                        "stage": "classification",
                        "batch_size": batch_size,
                        "batch_index": batch_index,
                        "error": requests[-1]["error"],
                    }
                    _write_report(report_path, report)
                    return report, 1

                elapsed = time.perf_counter() - request_started
                latencies.append(elapsed)
                completed_products += len(batch)
                categories.update(result.category for result in results)
                batch_name_mismatches = sum(
                    result.name != product.name for result, product in zip(results, batch, strict=True)
                )
                name_mismatches += batch_name_mismatches
                requests.append(
                    {
                        "batch_index": batch_index,
                        "product_count": len(batch),
                        "latency_seconds": round(elapsed, 3),
                        "status": "success",
                        "category_counts": dict(Counter(result.category for result in results)),
                        "name_mismatch_count": batch_name_mismatches,
                    }
                )
                if batch_index % 5 == 0 or batch_index == len(batches):
                    print(
                        f"Batch size {batch_size}: classified "
                        f"{completed_products}/{len(inputs)} products"
                    )
                    batch_run.update(
                        _classification_summary(
                            batch_size,
                            completed_products,
                            latencies,
                            time.perf_counter() - batch_started,
                            categories,
                            name_mismatches,
                            requests,
                        )
                    )
                    _write_report(report_path, report)

            batch_run.update(
                _classification_summary(
                    batch_size,
                    completed_products,
                    latencies,
                    time.perf_counter() - batch_started,
                    categories,
                    name_mismatches,
                    requests,
                )
            )
            batch_run["status"] = "completed"

    report["classification"]["status"] = "completed"
    report["classification"]["elapsed_seconds"] = round(time.perf_counter() - classification_started, 3)
    report["status"] = "completed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_report(report_path, report)
    return report, 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape 100 public Kosik products at a 0.5-second request delay, "
            "then classify them in batches of 5, 10, and 15"
        )
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible URL sampling")
    parser.add_argument("--report", type=Path, help="JSON report path (default: timestamped file under output/)")
    parser.add_argument(
        "--products-output",
        type=Path,
        help="Scraped JSONL output path (default: timestamped file under output/)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = args.report or Path("output") / f"prompt-batch-benchmark-{timestamp}.json"
    products_path = args.products_output or Path("output") / f"prompt-batch-products-{timestamp}.jsonl"
    try:
        _, exit_code = asyncio.run(run_benchmark(report_path, products_path, seed=args.seed))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(f"Benchmark report: {report_path}")
    print(f"Scraped products: {products_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
