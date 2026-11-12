"""Command-line interface for scraping Kosik products into JSONL."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .config import get_scraper_settings
from .discovery import (
    DEFAULT_CATEGORIES_CONFIG,
    CategoryEntry,
    DiscoveryManifest,
    load_category_whitelist,
    read_manifest,
    write_manifest,
)
from .output import JsonlWriter, default_output_path, next_run_id, read_observations
from .pipeline import ScrapingPipeline

# (source listing URL or None, product URLs) — one scrape_many call per batch.
Batch = tuple[str | None, list[str]]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public Kosik product pages into JSONL observations")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", action="append", help="Kosik product URL; may be repeated")
    source.add_argument(
        "--category-products",
        action="store_true",
        help="Discover products on the whitelisted categories (see --categories-config and --day)",
    )
    source.add_argument(
        "--from-manifest",
        type=Path,
        help="Scrape the product URLs of a saved discovery manifest (resume a run)",
    )
    source.add_argument(
        "--all-products",
        action="store_true",
        help="Debugging only: every product in Kosik's product sitemap, without category information",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL file to append to (default: output/kosik/<YYYY-MM-DD>/observations.jsonl)",
    )
    parser.add_argument(
        "--source-listing-url",
        default=None,
        help="With --url: category page the URLs were collected from",
    )
    parser.add_argument(
        "--categories-config",
        type=Path,
        default=DEFAULT_CATEGORIES_CONFIG,
        help=f"Category whitelist JSON (default: {DEFAULT_CATEGORIES_CONFIG})",
    )
    parser.add_argument(
        "--day",
        choices=["fri", "sat", "sun"],
        default=None,
        help="With --category-products: only categories planned for this day",
    )
    parser.add_argument(
        "--category",
        action="append",
        metavar="ID",
        help="With --category-products: only this Kosik category id (e.g. c3365), "
        "whether whitelisted or not; may be repeated",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Scrape at most N products in total in this run (for test runs)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip product URLs that already have a record in the output file",
    )
    parser.add_argument("--classify", action="store_true", help="Classify products with Qwen")
    args = parser.parse_args(argv)
    if args.source_listing_url and not args.url:
        parser.error("--source-listing-url can only be used with --url")
    if (args.day or args.category) and not args.category_products:
        parser.error("--day and --category can only be used with --category-products")
    if args.day and args.category:
        parser.error("use either --day or --category, not both")
    invalid = [value for value in args.category or [] if not re.fullmatch(r"c\d+", value)]
    if invalid:
        parser.error(f"--category expects ids like c3365, got: {', '.join(invalid)}")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


def manifest_path_for(output: Path, run_id: str) -> Path:
    return output.with_name(f"discovery-{run_id}.json")


def _report(manifest: DiscoveryManifest, manifest_path: Path | None) -> None:
    saved = f"; saved {manifest_path}" if manifest_path else ""
    print(f"{manifest.product_count} product URL(s) in {len(manifest.listings)} categories{saved}")
    for listing in manifest.listings:
        note = "" if listing.complete else "  WARNING: list may be incomplete (load-more limit or unknown state)"
        print(f"  {listing.category_id} {listing.category_name}: {len(listing.product_urls)}{note}")
    if manifest.missing_category_ids:
        print(f"  WARNING: not in Kosik's categories sitemap: {', '.join(manifest.missing_category_ids)}")


def _selected_categories(args: argparse.Namespace) -> list[CategoryEntry]:
    whitelist = load_category_whitelist(args.categories_config)
    if not args.category:
        return whitelist.for_day(args.day)
    names = {entry.id: entry.name for entry in whitelist.categories}
    return [CategoryEntry(id=value, name=names.get(value, value)) for value in dict.fromkeys(args.category)]


async def _batches(args: argparse.Namespace, pipeline: ScrapingPipeline, output: Path, run_id: str) -> list[Batch]:
    if args.url:
        return [(args.source_listing_url, args.url)]
    if args.all_products:
        return [(None, await pipeline.crawler.discover_product_urls())]
    if args.from_manifest:
        manifest = read_manifest(args.from_manifest)
        _report(manifest, None)
    else:
        categories = _selected_categories(args)
        if not categories:
            raise ValueError(f"No categories in {args.categories_config} for day {args.day!r}")
        manifest = await pipeline.crawler.discover_category_listings(categories)
        manifest = manifest.model_copy(update={"run_id": run_id})
        manifest_path = manifest_path_for(output, run_id)
        write_manifest(manifest, manifest_path)
        _report(manifest, manifest_path)
    return [(listing.url, listing.product_urls) for listing in manifest.listings]


async def run(
    args: argparse.Namespace,
    pipeline: ScrapingPipeline | None = None,
    now: datetime | None = None,
) -> tuple[Path, str, int]:
    """Discover (if requested) and scrape products, appending one JSONL line per product.

    Products found in several categories are scraped once, under the first one.
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
        batches = await _batches(args, pipeline, output, run_id)
        seen: set[str] = set()
        if args.skip_existing and output.exists():
            seen = {record.url for record in read_observations(output)}
        with JsonlWriter(output) as writer:
            for source_listing_url, product_urls in batches:
                urls = [url for url in dict.fromkeys(product_urls) if url not in seen]
                if args.limit is not None:
                    urls = urls[: args.limit - writer.count]
                if not urls:
                    continue
                seen.update(urls)
                await pipeline.scrape_many(
                    urls,
                    classify=args.classify,
                    source_listing_url=source_listing_url,
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
