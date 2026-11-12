import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scraper.config import ScraperSettings
from scraper.crawler import SITEMAP_URL, CrawlError, KosikCrawler
from scraper.discovery import (
    CategoryEntry,
    CategoryListing,
    CategoryWhitelist,
    DiscoveryManifest,
    category_id_from_url,
    load_category_whitelist,
    read_manifest,
    write_manifest,
)

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
SITEMAP_INDEX = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex {NS}>
  <sitemap><loc>https://www.kosik.sk/sitemap/categories.xml</loc></sitemap>
  <sitemap><loc>https://www.kosik.sk/sitemap/products_1.xml</loc></sitemap>
  <sitemap><loc>https://evil.example/sitemap/products_2.xml</loc></sitemap>
</sitemapindex>"""
CATEGORIES = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset {NS}>
  <url><loc>https://www.kosik.sk/c3338-udeniny-a-lahodky</loc></url>
  <url><loc>https://www.kosik.sk/c3365-slaniny-nove-meno?utm=x</loc></url>
  <url><loc>https://www.kosik.sk/c3350-parky</loc></url>
  <url><loc>https://evil.example/c9999-x</loc></url>
</urlset>"""
PRODUCTS = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset {NS}>
  <url><loc>https://www.kosik.sk/p7004-nord-svit?x=1</loc></url>
  <url><loc>https://www.kosik.sk/c3350-parky</loc></url>
  <url><loc>https://www.kosik.sk/p6902-tauris</loc></url>
</urlset>"""


def _category_page(*paths: str, marker: str | None = "clicks=2;exhausted=1") -> str:
    links = "".join(f'<a href="{path}">x</a>' for path in paths)
    attr = f' data-parky-load-more="{marker}"' if marker else ""
    return f"<html><body{attr}>{links}<a href='https://evil.example/p1-x'>x</a><a href='/c3366-slanina'>x</a></body></html>"


class FakeCrawler(KosikCrawler):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(ScraperSettings(request_delay_seconds=0), debug_output_dir=None)
        self.pages = pages
        self.requested: list[str] = []

    async def _fetch_sitemap(self, url: str) -> str:
        self.requested.append(url)
        return {
            SITEMAP_URL: SITEMAP_INDEX,
            "https://www.kosik.sk/sitemap/categories.xml": CATEGORIES,
            "https://www.kosik.sk/sitemap/products_1.xml": PRODUCTS,
        }[url]

    async def crawl(self, url: str, *, load_all: bool = False, save_debug: bool = True) -> str:
        assert load_all and not save_debug
        self.requested.append(url)
        return self.pages[url]


def test_category_id_from_url() -> None:
    assert category_id_from_url("https://www.kosik.sk/c3365-slaniny") == "c3365"
    assert category_id_from_url("https://www.kosik.sk/c3365?page=2") == "c3365"
    assert category_id_from_url("https://www.kosik.sk/p7004-parky") is None
    assert category_id_from_url(None) is None


def test_whitelist_validation_and_day_selection(tmp_path: Path) -> None:
    path = tmp_path / "categories.json"
    path.write_text(
        json.dumps(
            {
                "categories": [
                    {"id": "c3365", "name": "Slaniny", "day": "fri"},
                    {"id": "c3350", "name": "Párky", "day": "sat"},
                    {"id": "c1", "name": "Bez dňa"},
                ]
            }
        ),
        encoding="utf-8",
    )
    whitelist = load_category_whitelist(path)
    assert [c.id for c in whitelist.for_day("fri")] == ["c3365"]
    assert [c.id for c in whitelist.for_day(None)] == ["c3365", "c3350", "c1"]


@pytest.mark.parametrize(
    "categories",
    [
        [{"id": "c1", "name": "A"}, {"id": "c1", "name": "B"}],
        [{"id": "/c3365-slaniny", "name": "path instead of id"}],
        [{"id": "c1", "name": "A", "day": "mon"}],
        [],
    ],
)
def test_invalid_whitelist_is_rejected(tmp_path: Path, categories: list[dict[str, str]]) -> None:
    path = tmp_path / "categories.json"
    path.write_text(json.dumps({"categories": categories}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid category whitelist"):
        load_category_whitelist(path)


def test_repository_whitelist_is_valid() -> None:
    whitelist = load_category_whitelist(Path(__file__).parents[2] / "config" / "kosik_categories.json")
    assert whitelist.categories


def test_discovery_groups_products_by_category_and_matches_by_id() -> None:
    crawler = FakeCrawler(
        {
            "https://www.kosik.sk/c3365-slaniny-nove-meno": _category_page("/p7224-slanina", "/p7224-slanina", "/p1-b"),
            "https://www.kosik.sk/c3350-parky": _category_page("/p7004-nord-svit", marker="clicks=30;exhausted=0"),
        }
    )
    categories = [
        CategoryEntry(id="c3365", name="Slaniny"),
        CategoryEntry(id="c3350", name="Párky"),
        CategoryEntry(id="c4242", name="Zmazaná"),
    ]
    manifest = asyncio.run(crawler.discover_category_listings(categories))

    assert [(l.category_id, l.url, l.product_urls, l.load_more_clicks, l.complete) for l in manifest.listings] == [
        (
            "c3365",
            "https://www.kosik.sk/c3365-slaniny-nove-meno",
            ["https://www.kosik.sk/p1-b", "https://www.kosik.sk/p7224-slanina"],
            2,
            True,
        ),
        ("c3350", "https://www.kosik.sk/c3350-parky", ["https://www.kosik.sk/p7004-nord-svit"], 30, False),
    ]
    assert manifest.missing_category_ids == ["c4242"]
    assert manifest.product_count == 3


def test_missing_load_more_marker_means_incomplete() -> None:
    crawler = FakeCrawler({"https://www.kosik.sk/c3350-parky": _category_page("/p1-a", marker=None)})
    manifest = asyncio.run(crawler.discover_category_listings([CategoryEntry(id="c3350", name="Párky")]))
    assert (manifest.listings[0].load_more_clicks, manifest.listings[0].complete) == (None, False)


def test_discovery_fails_when_no_whitelisted_category_exists() -> None:
    with pytest.raises(CrawlError, match="None of the whitelisted categories"):
        asyncio.run(FakeCrawler({}).discover_category_listings([CategoryEntry(id="c4242", name="X")]))


def test_product_sitemap_discovery_ignores_foreign_hosts_and_non_products() -> None:
    crawler = FakeCrawler({})
    urls = asyncio.run(crawler.discover_product_urls())
    assert urls == ["https://www.kosik.sk/p6902-tauris", "https://www.kosik.sk/p7004-nord-svit"]
    assert "https://evil.example/sitemap/products_2.xml" not in crawler.requested


def test_invalid_sitemap_xml_is_reported() -> None:
    class Broken(FakeCrawler):
        async def _fetch_sitemap(self, url: str) -> str:
            return "<not-xml"

    with pytest.raises(CrawlError, match="Invalid sitemap XML"):
        asyncio.run(Broken({}).discover_category_listings([CategoryEntry(id="c1", name="X")]))


def test_crawler_rejects_non_kosik_urls() -> None:
    with pytest.raises(CrawlError, match="Only public kosik.sk"):
        asyncio.run(KosikCrawler(ScraperSettings(), debug_output_dir=None).crawl("https://evil.example/p1-x"))


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = DiscoveryManifest(
        run_id="2026-11-14-kosik-01",
        discovered_at=datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc),
        listings=[
            CategoryListing(
                category_id="c3350",
                category_name="Párky",
                url="https://www.kosik.sk/c3350-parky",
                product_urls=["https://www.kosik.sk/p7004-x"],
                load_more_clicks=0,
                complete=True,
            )
        ],
    )
    path = tmp_path / "nested" / "discovery.json"
    write_manifest(manifest, path)
    assert read_manifest(path) == manifest


def test_whitelist_model_requires_categories() -> None:
    with pytest.raises(ValueError):
        CategoryWhitelist(categories=[])
