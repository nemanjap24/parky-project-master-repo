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


SLANINA = "https://www.kosik.sk/p7224-fine-life-anglicka-slanina-platky-94-maeso"
FIXTURE_BY_URL[SLANINA] = "kosik_fine_life_slanina.html"
PARKY_LISTING = "https://www.kosik.sk/c3350-parky"
SLANINY_LISTING = "https://www.kosik.sk/c3365-slaniny"


class DiscoveringCrawler(FixtureCrawler):
    async def discover_category_listings(self, categories):  # type: ignore[no-untyped-def]
        from scraper.discovery import CategoryListing, DiscoveryManifest

        listings = {
            "c3350": CategoryListing(
                category_id="c3350",
                category_name="Párky",
                url=PARKY_LISTING,
                product_urls=[NORD_SVIT, TAURIS, SLANINA],
                load_more_clicks=0,
                complete=True,
            ),
            "c3365": CategoryListing(
                category_id="c3365",
                category_name="Slaniny",
                url=SLANINY_LISTING,
                product_urls=[SLANINA, NORD_SVIT],
                load_more_clicks=31,
                complete=False,
            ),
        }
        return DiscoveryManifest(
            discovered_at=NOW,
            listings=[listings[c.id] for c in categories if c.id in listings],
        )


def _whitelist(tmp_path: Path) -> Path:
    path = tmp_path / "categories.json"
    path.write_text(
        json.dumps(
            {
                "categories": [
                    {"id": "c3350", "name": "Párky", "day": "fri"},
                    {"id": "c3365", "name": "Slaniny", "day": "sat"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_category_mode_writes_manifest_and_tags_listing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "obs.jsonl"
    argv = ["--category-products", "--categories-config", str(_whitelist(tmp_path)), "--output", str(output)]

    _, run_id, count = asyncio.run(run(parse_args(argv), pipeline=_pipeline(DiscoveringCrawler()), now=NOW))

    assert count == 3  # Nord Svit and slanina appear in both listings but are scraped once
    records = read_observations(output)
    assert [(r.retailer_product_id, r.source_listing_url) for r in records] == [
        ("7004", PARKY_LISTING),
        ("6902", PARKY_LISTING),
        ("7224", PARKY_LISTING),
    ]
    assert records[0].extraction.warnings == []
    assert records[2].extraction.warnings == ["outside_listing_category"]
    manifest_path = tmp_path / f"discovery-{run_id}.json"
    from scraper.discovery import read_manifest

    assert read_manifest(manifest_path).run_id == run_id
    assert "WARNING: list may be incomplete" in capsys.readouterr().out


def test_day_selects_categories_and_resume_skips_existing(tmp_path: Path) -> None:
    output = tmp_path / "obs.jsonl"
    whitelist = _whitelist(tmp_path)
    friday = ["--category-products", "--day", "fri", "--categories-config", str(whitelist), "--output", str(output)]
    _, first_run, _ = asyncio.run(run(parse_args(friday), pipeline=_pipeline(DiscoveringCrawler()), now=NOW))
    manifest_path = tmp_path / f"discovery-{first_run}.json"

    resume = ["--from-manifest", str(manifest_path), "--skip-existing", "--output", str(output)]
    _, _, resumed = asyncio.run(run(parse_args(resume), pipeline=_pipeline(DiscoveringCrawler()), now=NOW))

    assert resumed == 0
    assert len(read_observations(output)) == 3


def test_resume_after_failure_scrapes_only_missing_products(tmp_path: Path) -> None:
    output = tmp_path / "obs.jsonl"
    argv = ["--category-products", "--day", "fri", "--categories-config", str(_whitelist(tmp_path)), "--output", str(output)]
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run(parse_args(argv), pipeline=_pipeline(DiscoveringCrawler(fail_on=TAURIS)), now=NOW))
    manifest_path = next(tmp_path.glob("discovery-*.json"))

    resume = ["--from-manifest", str(manifest_path), "--skip-existing", "--output", str(output)]
    _, _, resumed = asyncio.run(run(parse_args(resume), pipeline=_pipeline(DiscoveringCrawler()), now=NOW))

    assert resumed == 2
    assert sorted(r.retailer_product_id for r in read_observations(output)) == ["6902", "7004", "7224"]


def test_invalid_option_combinations_are_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--category-products", "--source-listing-url", PARKY_LISTING])
    with pytest.raises(SystemExit):
        parse_args(["--url", NORD_SVIT, "--day", "fri"])
    with pytest.raises(SystemExit):
        parse_args(["--url", NORD_SVIT, "--category-products"])


def test_category_option_selects_any_category_and_limit_caps_the_run(tmp_path: Path) -> None:
    output = tmp_path / "obs.jsonl"
    argv = [
        "--category-products",
        "--category", "c3365",
        "--category", "c3350",
        "--limit", "2",
        "--categories-config", str(_whitelist(tmp_path)),
        "--output", str(output),
    ]  # fmt: skip

    _, run_id, count = asyncio.run(run(parse_args(argv), pipeline=_pipeline(DiscoveringCrawler()), now=NOW))

    assert count == 2
    records = read_observations(output)
    assert [(r.retailer_product_id, r.source_listing_url) for r in records] == [
        ("7224", SLANINY_LISTING),
        ("7004", SLANINY_LISTING),
    ]
    from scraper.discovery import read_manifest

    manifest = read_manifest(tmp_path / f"discovery-{run_id}.json")
    assert [listing.category_id for listing in manifest.listings] == ["c3365", "c3350"]
    assert manifest.product_count == 3  # the manifest keeps the full discovery, only scraping is limited


def test_category_option_accepts_ids_outside_the_whitelist(tmp_path: Path) -> None:
    class RecordingCrawler(DiscoveringCrawler):
        async def discover_category_listings(self, categories):  # type: ignore[no-untyped-def]
            self.selected = [(c.id, c.name) for c in categories]
            return await super().discover_category_listings(categories)

    crawler = RecordingCrawler()
    argv = ["--category-products", "--category", "c2968", "--category", "c3350", "--categories-config", str(_whitelist(tmp_path)),
            "--output", str(tmp_path / "obs.jsonl")]  # fmt: skip
    asyncio.run(run(parse_args(argv), pipeline=_pipeline(crawler), now=NOW))
    assert crawler.selected == [("c2968", "c2968"), ("c3350", "Párky")]


def test_limit_also_applies_to_url_mode(tmp_path: Path) -> None:
    output = tmp_path / "obs.jsonl"
    argv = ["--url", NORD_SVIT, "--url", TAURIS, "--limit", "1", "--output", str(output)]
    _, _, count = asyncio.run(run(parse_args(argv), pipeline=_pipeline(FixtureCrawler()), now=NOW))
    assert count == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--url", NORD_SVIT, "--category", "c3365"],
        ["--category-products", "--category", "3365"],
        ["--category-products", "--category", "/c3365-slaniny"],
        ["--category-products", "--day", "fri", "--category", "c3365"],
        ["--url", NORD_SVIT, "--limit", "0"],
    ],
)
def test_invalid_category_and_limit_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)
