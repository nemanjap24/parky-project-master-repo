import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scraper.cli import parse_args, run
from scraper.config import ScraperSettings
from scraper.models import Extraction, ProductObservation
from scraper.output import JsonlWriter, default_output_path, next_run_id, read_observations
from scraper.pipeline import ScrapingPipeline

FIXTURES = Path(__file__).parents[1] / "fixtures"
DAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 8, 12, 44, tzinfo=timezone.utc)
NORD_SVIT = "https://www.kosik.sk/p7004-nord-svit-zlate-parky-93-maesa"
TAURIS = "https://www.kosik.sk/p6902-tauris-zipser-parky-71-maesa"
FIXTURE_BY_URL = {NORD_SVIT: "kosik_nord_svit_parky.html", TAURIS: "kosik_tauris_parky.html"}


def _observation(run_id: str | None) -> ProductObservation:
    return ProductObservation(
        run_id=run_id,
        url="https://www.kosik.sk/p1-x",
        scraped_at=NOW,
        extraction=Extraction(source="json-ld+html"),
    )


def test_default_output_path() -> None:
    assert default_output_path(DAY) == Path("output/kosik/2026-11-14/observations.jsonl")


def test_run_id_starts_at_01_and_increments_per_day(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    assert next_run_id(DAY, path) == "2026-11-14-kosik-01"
    with JsonlWriter(path) as writer:
        writer.write(_observation("2026-11-14-kosik-01"))
        writer.write(_observation("2026-11-14-kosik-02"))
        writer.write(_observation("2026-11-13-kosik-07"))
        writer.write(_observation(None))
    assert next_run_id(DAY, path) == "2026-11-14-kosik-03"


def test_corrupt_output_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="observations.jsonl:1"):
        next_run_id(DAY, path)


def test_writer_appends_one_json_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "observations.jsonl"
    with JsonlWriter(path) as writer:
        writer.write(_observation("a"))
    with JsonlWriter(path) as writer:
        writer.write(_observation("b"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["run_id"] for line in lines] == ["a", "b"]
    assert [item.run_id for item in read_observations(path)] == ["a", "b"]


def test_writer_requires_context_manager(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="context manager"):
        JsonlWriter(tmp_path / "x.jsonl").write(_observation("a"))


class FixtureCrawler:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on

    async def crawl(self, url: str) -> str:
        if url == self.fail_on:
            raise RuntimeError("boom")
        return (FIXTURES / FIXTURE_BY_URL[url]).read_text(encoding="utf-8")


def _pipeline(crawler: FixtureCrawler) -> ScrapingPipeline:
    return ScrapingPipeline(crawler, settings=ScraperSettings(), clock=lambda: NOW)


def test_cli_appends_jsonl_with_run_id_and_listing(tmp_path: Path) -> None:
    output = tmp_path / "obs.jsonl"
    argv = ["--url", NORD_SVIT, "--url", TAURIS, "--output", str(output), "--source-listing-url", "https://www.kosik.sk/c3350-parky"]

    path, run_id, count = asyncio.run(run(parse_args(argv), pipeline=_pipeline(FixtureCrawler()), now=NOW))
    second = asyncio.run(run(parse_args(argv[:2] + argv[4:6]), pipeline=_pipeline(FixtureCrawler()), now=NOW))

    assert (path, run_id, count) == (output, "2026-11-14-kosik-01", 2)
    assert second[1:] == ("2026-11-14-kosik-02", 1)
    records = read_observations(output)
    assert [(r.run_id, r.retailer_product_id) for r in records] == [
        ("2026-11-14-kosik-01", "7004"),
        ("2026-11-14-kosik-01", "6902"),
        ("2026-11-14-kosik-02", "7004"),
    ]
    assert records[0].source_listing_url == "https://www.kosik.sk/c3350-parky"
    assert records[2].source_listing_url is None
    assert records[0].shelf_price is not None and str(records[0].shelf_price) == "3.39"


def test_cli_default_path_uses_run_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path, _, _ = asyncio.run(run(parse_args(["--url", NORD_SVIT]), pipeline=_pipeline(FixtureCrawler()), now=NOW))
    assert path == Path("output/kosik/2026-11-14/observations.jsonl")
    assert (tmp_path / path).exists()


def test_records_before_a_failure_are_kept(tmp_path: Path) -> None:
    output = tmp_path / "obs.jsonl"
    args = parse_args(["--url", NORD_SVIT, "--url", TAURIS, "--output", str(output)])
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run(args, pipeline=_pipeline(FixtureCrawler(fail_on=TAURIS)), now=NOW))
    assert [r.retailer_product_id for r in read_observations(output)] == ["7004"]
