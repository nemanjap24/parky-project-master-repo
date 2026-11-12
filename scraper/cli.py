"""Command-line interface for scraping Kosik products into JSONL."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .config import get_scraper_settings
from .output import JsonlWriter, default_output_path, next_run_id
from .pipeline import ScrapingPipeline


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public Kosik product pages into JSONL observations")
    parser.add_argument("--url", action="append", required=True, help="Kosik product URL; may be repeated")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL file to append to (default: output/kosik/<YYYY-MM-DD>/observations.jsonl)",
    )
    parser.add_argument("--source-listing-url", default=None, help="Category page the URLs were collected from")
    parser.add_argument("--classify", action="store_true", help="Classify products with Qwen")
    return parser.parse_args(argv)


async def run(
    args: argparse.Namespace,
    pipeline: ScrapingPipeline | None = None,
    now: datetime | None = None,
) -> tuple[Path, str, int]:
    """Scrape ``args.url`` and append one JSONL line per product.

    Returns the output path, the run id and the number of written records.
    ``pipeline`` and ``now`` are injectable for offline tests.
    """

    started = now or datetime.now(timezone.utc)
    output: Path = args.output or default_output_path(started.date())
    run_id = next_run_id(started.date(), output)
    classifier = None
    if pipeline is None:
        if args.classify:
            from qwen_classifier.client import QwenClassifier

            classifier = QwenClassifier()
        pipeline = ScrapingPipeline(classifier=classifier, settings=get_scraper_settings())
    pipeline.run_id = run_id
    try:
        with JsonlWriter(output) as writer:
            await pipeline.scrape_many(
                args.url,
                classify=args.classify,
                source_listing_url=args.source_listing_url,
                on_result=writer.write,
            )
            return output, run_id, writer.count
    finally:
        if classifier is not None:
            classifier.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output, run_id, count = asyncio.run(run(args))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Run {run_id}: scraped {count} product(s); appended to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
