from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ScraperSettings, get_scraper_settings
from .crawler import CrawlError, KosikCrawler
from .discovery import read_manifest
from .models import ProductObservation
from .pipeline import ScrapingPipeline

MAX_PAGES = 30
DEFAULT_PAGE_COUNTS = [15, 30]


class DelayMeasuringCrawler(KosikCrawler):
    def __init__(self, settings: ScraperSettings) -> None:
        super().__init__(settings=settings, debug_output_dir=None)
        self.last_delay_wait_seconds = 0.0

    async def _delay(self) -> None:
        started = time.perf_counter()
        await super()._delay()
        self.last_delay_wait_seconds = time.perf_counter() - started


def delay_values() -> list[float]:
    return [step / 2 for step in range(1, 11)]


def validate_page_counts(page_counts: list[int], available_urls: int) -> list[int]:
    if not page_counts:
        raise ValueError("At least one page count is required")
    if any(count < 1 or count > MAX_PAGES for count in page_counts):
        raise ValueError(f"Page counts must be between 1 and {MAX_PAGES}")
    counts = sorted(set(page_counts))
    if counts[-1] > available_urls:
        raise ValueError(
            f"The manifest contains {available_urls} unique product URLs, "
            f"but the benchmark needs {counts[-1]}"
        )
    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure sequential Kosik page scraping at request delays from 0.5 to 5 seconds"
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Saved discovery manifest with product URLs")
    parser.add_argument(
        "--page-counts",
        type=int,
        nargs="+",
        default=DEFAULT_PAGE_COUNTS,
        help=f"Checkpoint counts to measure (default: 15 30; maximum: {MAX_PAGES})",
    )
    parser.add_argument("--report", type=Path, help="JSON report path (default: timestamped file under output/)")
    args = parser.parse_args(argv)
    if not args.page_counts or any(count < 1 or count > MAX_PAGES for count in args.page_counts):
        parser.error(f"--page-counts values must be between 1 and {MAX_PAGES}")
    return args


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _checkpoint(page_results: list[dict[str, Any]], page_count: int, elapsed: float) -> dict[str, Any]:
    rows = page_results[:page_count]
    return {
        "page_count": page_count,
        "elapsed_seconds": round(elapsed, 3),
        "pages_with_warnings": sum(bool(row["warning_codes"]) for row in rows),
        "mean_page_processing_seconds": round(
            statistics.mean(row["page_processing_seconds"] for row in rows), 3
        ),
        "mean_request_delay_wait_seconds": round(
            statistics.mean(row["request_delay_wait_seconds"] for row in rows), 3
        ),
        "mean_wall_seconds_per_page": round(statistics.mean(row["wall_seconds"] for row in rows), 3),
    }


def _empty_page_reason(product: ProductObservation) -> str | None:
    if not product.name and product.shelf_price is None:
        return "No product name or shelf price was extracted"
    return None


def _scrape_failure_type(error: Exception) -> str:
    if isinstance(error, CrawlError) and str(error).startswith("Rendered page was empty:"):
        return "empty_page"
    return "scrape_error"


async def run_benchmark(
    manifest_path: Path,
    report_path: Path,
    page_counts: list[int],
) -> tuple[dict[str, Any], int]:
    manifest = read_manifest(manifest_path)
    urls = list(dict.fromkeys(url for listing in manifest.listings for url in listing.product_urls))
    counts = validate_page_counts(page_counts, len(urls))
    base_settings = get_scraper_settings()
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "page_counts": counts,
        "delay_values_seconds": delay_values(),
        "request_mode": "sequential",
        "classification_enabled": False,
        "notes": (
            "The configured delay is the minimum wait after a previous request completes. "
            "Page processing time includes rendering, extraction, and Crawl4AI's configured "
            "delay_before_return_html."
        ),
        "status": "running",
        "runs": [],
    }
    _write_report(report_path, report)

    for delay_seconds in delay_values():
        settings = replace(base_settings, request_delay_seconds=delay_seconds)
        crawler = DelayMeasuringCrawler(settings=settings)
        pipeline = ScrapingPipeline(crawler=crawler, settings=settings)
        page_results: list[dict[str, Any]] = []
        delay_run: dict[str, Any] = {
            "request_delay_seconds": delay_seconds,
            "checkpoints": [],
            "pages": page_results,
        }
        report["runs"].append(delay_run)
        delay_started = time.perf_counter()

        for index, url in enumerate(urls[: counts[-1]], start=1):
            crawler.last_delay_wait_seconds = 0.0
            page_started = time.perf_counter()
            try:
                product = await pipeline.scrape(url, classify=False)
            except Exception as exc:
                wall_seconds = time.perf_counter() - page_started
                failure_type = _scrape_failure_type(exc)
                page_results.append(
                    {
                        "index": index,
                        "url": url,
                        "status": failure_type,
                        "wall_seconds": round(wall_seconds, 3),
                        "request_delay_wait_seconds": round(crawler.last_delay_wait_seconds, 3),
                        "page_processing_seconds": round(
                            max(0.0, wall_seconds - crawler.last_delay_wait_seconds), 3
                        ),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                delay_run["failure"] = {
                    "type": failure_type,
                    "page_index": index,
                    "error": page_results[-1]["error"],
                }
                report["status"] = "failed"
                report["finished_at"] = datetime.now(timezone.utc).isoformat()
                report["failure"] = {
                    "type": failure_type,
                    "request_delay_seconds": delay_seconds,
                    "page_index": index,
                    "error": page_results[-1]["error"],
                }
                _write_report(report_path, report)
                status_message = "Empty page" if failure_type == "empty_page" else "Scrape failed"
                print(
                    f"{status_message} at delay {delay_seconds:.1f}s, page {index}/{counts[-1]}: {exc}",
                    file=sys.stderr,
                )
                return report, 1

            wall_seconds = time.perf_counter() - page_started
            page_result = {
                "index": index,
                "url": url,
                "status": "success",
                "wall_seconds": round(wall_seconds, 3),
                "request_delay_wait_seconds": round(crawler.last_delay_wait_seconds, 3),
                "page_processing_seconds": round(
                    max(0.0, wall_seconds - crawler.last_delay_wait_seconds), 3
                ),
                "warning_codes": product.extraction.warnings,
                "product_name": product.name,
            }
            empty_reason = _empty_page_reason(product)
            if empty_reason is not None:
                page_result["status"] = "empty_page"
                page_result["error"] = empty_reason
                delay_run["failure"] = {
                    "type": "empty_page",
                    "page_index": index,
                    "error": empty_reason,
                }
                report["status"] = "failed"
                report["finished_at"] = datetime.now(timezone.utc).isoformat()
                report["failure"] = {
                    "type": "empty_page",
                    "request_delay_seconds": delay_seconds,
                    "page_index": index,
                    "error": empty_reason,
                }
                page_results.append(page_result)
                _write_report(report_path, report)
                print(
                    f"Empty product page at delay {delay_seconds:.1f}s, "
                    f"page {index}/{counts[-1]}: {url}",
                    file=sys.stderr,
                )
                return report, 1

            page_results.append(page_result)
            if index in counts:
                checkpoint = _checkpoint(page_results, index, time.perf_counter() - delay_started)
                delay_run["checkpoints"].append(checkpoint)
                print(
                    f"Delay {delay_seconds:.1f}s: {index} pages in "
                    f"{checkpoint['elapsed_seconds']:.1f}s "
                    f"(mean page processing {checkpoint['mean_page_processing_seconds']:.2f}s, "
                    f"{checkpoint['pages_with_warnings']} page(s) with extraction warnings)"
                )
                _write_report(report_path, report)

    report["status"] = "completed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_report(report_path, report)
    return report, 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = args.report or Path(
        "output"
    ) / f"scraper-delay-benchmark-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    try:
        _, exit_code = asyncio.run(run_benchmark(args.manifest, report_path, args.page_counts))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(f"Benchmark report: {report_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
