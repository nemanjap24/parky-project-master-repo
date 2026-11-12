"""Crawl4AI browser integration for public Kosik pages and product URL discovery."""

from __future__ import annotations

import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

from .config import ScraperSettings, get_scraper_settings
from .discovery import CategoryEntry, CategoryListing, DiscoveryManifest, category_id_from_url


class CrawlError(RuntimeError):
    """Raised when a product page cannot be rendered."""


SITEMAP_URL = "https://www.kosik.sk/sitemap.xml"
_KOSIK_HOSTS = {"www.kosik.sk", "kosik.sk"}
LOAD_MORE_MAX_CLICKS = 30
# The load-more script stores its result on <body> so it survives into the returned HTML.
_LOAD_MORE_MARKER = re.compile(r'data-parky-load-more="clicks=(\d+);exhausted=([01])"')
_LOAD_MORE_SCRIPT = """
    (async () => {
        let clicks = 0;
        let exhausted = false;
        const productLinks = () => document.querySelectorAll('a[href*="/p"]').length;
        const findButton = () => Array.from(document.querySelectorAll("button"))
            .find((item) => /načítať ďalšie/i.test(item.innerText));
        for (; clicks < %(max_clicks)d; ) {
            const button = findButton();
            if (!button) { exhausted = true; break; }
            const before = productLinks();
            button.click();
            clicks += 1;
            for (let wait = 0; wait < 50; wait++) {
                await new Promise((resolve) => setTimeout(resolve, 100));
                if (productLinks() > before) break;
            }
            if (productLinks() <= before) break;
        }
        if (!exhausted && !findButton()) exhausted = true;
        document.body.setAttribute("data-parky-load-more", `clicks=${clicks};exhausted=${exhausted ? 1 : 0}`);
    })()
""" % {"max_clicks": LOAD_MORE_MAX_CLICKS}


class _ProductLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        parsed = urlparse(href)
        if parsed.netloc and parsed.hostname not in _KOSIK_HOSTS:
            return
        if parsed.scheme and not KosikCrawler._is_kosik_url(href):
            return
        if re.match(r"^/p\d+(?:-|$)", parsed.path):
            self.paths.add(parsed.path)


class KosikCrawler:
    def __init__(
        self,
        settings: ScraperSettings | None = None,
        debug_output_dir: Path | None = Path("scraper/output/rendered"),
    ) -> None:
        self.settings = settings or get_scraper_settings()
        self.debug_output_dir = debug_output_dir
        self._last_request_at: float | None = None

    async def discover_product_urls(self, sitemap_url: str = SITEMAP_URL) -> list[str]:
        """Return unique public product URLs listed in Kosik's product sitemaps."""
        sitemap_xml = await self._fetch_sitemap(sitemap_url)
        root = self._parse_sitemap(sitemap_xml, sitemap_url)
        root_type = self._xml_name(root.tag)
        if root_type == "urlset":
            return self._product_urls(root)
        if root_type != "sitemapindex":
            raise CrawlError(f"Unsupported sitemap format at {sitemap_url}")

        product_sitemaps = []
        for sitemap in root:
            if self._xml_name(sitemap.tag) != "sitemap":
                continue
            location = self._child_text(sitemap, "loc")
            if not location or not self._is_kosik_url(location):
                continue
            filename = Path(urlparse(location).path).name
            if filename.startswith("products_") and filename.endswith(".xml"):
                product_sitemaps.append(location)
        if not product_sitemaps:
            raise CrawlError(f"No product sitemaps found at {sitemap_url}")

        urls: set[str] = set()
        for product_sitemap in product_sitemaps:
            content = await self._fetch_sitemap(product_sitemap)
            urls.update(self._product_urls(self._parse_sitemap(content, product_sitemap)))
        return sorted(urls)

    async def discover_category_listings(
        self,
        categories: Sequence[CategoryEntry],
        sitemap_url: str = SITEMAP_URL,
    ) -> DiscoveryManifest:
        """Find product URLs on the whitelisted category pages, grouped by category.

        Category pages are located in Kosik's categories sitemap by category id,
        so a changed URL slug does not drop a category. Whitelisted ids that are
        not in the sitemap are reported in ``missing_category_ids``.
        """

        if not categories:
            raise CrawlError("No categories selected for discovery")
        sitemap_xml = await self._fetch_sitemap(sitemap_url)
        root = self._parse_sitemap(sitemap_xml, sitemap_url)
        categories_url = self._child_sitemap_url(root, "categories.xml")
        if categories_url is None:
            raise CrawlError(f"No categories sitemap found at {sitemap_url}")

        categories_xml = await self._fetch_sitemap(categories_url)
        urls_by_id = self._category_urls_by_id(self._parse_sitemap(categories_xml, categories_url))
        missing = [category.id for category in categories if category.id not in urls_by_id]
        if len(missing) == len(categories):
            raise CrawlError(f"None of the whitelisted categories were found at {categories_url}")

        listings: list[CategoryListing] = []
        for category in categories:
            category_url = urls_by_id.get(category.id)
            if category_url is None:
                continue
            html = await self.crawl(category_url, load_all=True, save_debug=False)
            clicks, exhausted = self._load_more_state(html)
            listings.append(
                CategoryListing(
                    category_id=category.id,
                    category_name=category.name,
                    url=category_url,
                    product_urls=self._product_links(html, category_url),
                    load_more_clicks=clicks,
                    complete=exhausted is True,
                )
            )
        return DiscoveryManifest(
            discovered_at=datetime.now(timezone.utc),
            listings=listings,
            missing_category_ids=missing,
        )

    async def crawl(
        self,
        url: str,
        *,
        load_all: bool = False,
        save_debug: bool = True,
    ) -> str:
        if not self._is_kosik_url(url):
            raise CrawlError("Only public kosik.sk URLs are supported")
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        except ImportError as exc:
            raise CrawlError("Crawl4AI is required for live scraping; install requirements.txt") from exc
        await self._delay()
        browser = BrowserConfig(headless=True, user_agent=self.settings.user_agent)
        js_code = _LOAD_MORE_SCRIPT if load_all else None
        run_config = CrawlerRunConfig(
            page_timeout=int(self.settings.page_timeout_seconds * 1000),
            wait_for="js:() => document.querySelector('#kosik-app2')?.innerText.trim().length > 50",
            delay_before_return_html=2,
            js_code=js_code,
        )
        try:
            async with AsyncWebCrawler(config=browser) as crawler:
                result = await crawler.arun(url=url, config=run_config)
        except asyncio.TimeoutError as exc:
            raise CrawlError(f"Timed out while loading {url}") from exc
        except Exception as exc:
            raise CrawlError(f"Failed to load {url}: {exc}") from exc
        if getattr(result, "success", True) is False:
            raise CrawlError(f"Page navigation failed for {url}")
        content = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
        if not isinstance(content, str) or not content.strip():
            raise CrawlError(f"Rendered page was empty: {url}")
        if save_debug:
            self._save_debug_html(content, url)
        self._last_request_at = asyncio.get_running_loop().time()
        return content

    async def _fetch_sitemap(self, url: str) -> str:
        if not self._is_kosik_url(url):
            raise CrawlError("Only public kosik.sk sitemap URLs are supported")
        await self._delay()
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.page_timeout_seconds,
                headers={"User-Agent": self.settings.user_agent},
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CrawlError(f"Failed to load sitemap {url}: {exc}") from exc
        self._last_request_at = asyncio.get_running_loop().time()
        return response.text

    @classmethod
    def _child_sitemap_url(cls, root: ET.Element, filename: str) -> str | None:
        if cls._xml_name(root.tag) != "sitemapindex":
            raise CrawlError("Sitemap index has an unexpected format")
        for sitemap in root:
            if cls._xml_name(sitemap.tag) != "sitemap":
                continue
            location = cls._child_text(sitemap, "loc")
            if (
                location
                and cls._is_kosik_url(location)
                and Path(urlparse(location).path).name == filename
            ):
                return location
        return None

    @staticmethod
    def _parse_sitemap(content: str, url: str) -> ET.Element:
        try:
            return ET.fromstring(content)
        except ET.ParseError as exc:
            raise CrawlError(f"Invalid sitemap XML at {url}: {exc}") from exc

    @staticmethod
    def _xml_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @classmethod
    def _child_text(cls, parent: ET.Element, name: str) -> str | None:
        for child in parent:
            if cls._xml_name(child.tag) == name and child.text:
                return child.text.strip()
        return None

    @classmethod
    def _product_urls(cls, root: ET.Element) -> list[str]:
        if cls._xml_name(root.tag) != "urlset":
            raise CrawlError("Product sitemap does not contain a URL set")
        urls = []
        for entry in root:
            if cls._xml_name(entry.tag) != "url":
                continue
            location = cls._child_text(entry, "loc")
            if not location or not cls._is_kosik_url(location):
                continue
            parsed = urlparse(location)
            if not re.match(r"^/p\d+(?:-|$)", parsed.path):
                continue
            urls.append(urlunparse(("https", parsed.netloc, parsed.path, "", "", "")))
        return urls

    @classmethod
    def _category_urls_by_id(cls, root: ET.Element) -> dict[str, str]:
        """Map category id (``c3365``) to its canonical URL from the categories sitemap."""

        if cls._xml_name(root.tag) != "urlset":
            raise CrawlError("Categories sitemap does not contain a URL set")
        urls: dict[str, str] = {}
        for entry in root:
            if cls._xml_name(entry.tag) != "url":
                continue
            location = cls._child_text(entry, "loc")
            if not location or not cls._is_kosik_url(location):
                continue
            parsed = urlparse(location)
            category_id = category_id_from_url(parsed.path)
            if category_id and category_id not in urls:
                urls[category_id] = urlunparse(("https", parsed.netloc, parsed.path, "", "", ""))
        return urls

    @staticmethod
    def _load_more_state(html: str) -> tuple[int | None, bool | None]:
        """Clicks made and whether the list was fully loaded; ``(None, None)`` if unknown."""

        match = _LOAD_MORE_MARKER.search(html)
        if match is None:
            return None, None
        return int(match.group(1)), match.group(2) == "1"

    @classmethod
    def _product_links(cls, html: str, category_url: str) -> list[str]:
        parser = _ProductLinkParser()
        parser.feed(html)
        host = urlparse(category_url).netloc
        return [f"https://{host}{path}" for path in sorted(parser.paths)]

    @staticmethod
    def _is_kosik_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in _KOSIK_HOSTS and parsed.port is None

    def _save_debug_html(self, content: str, url: str) -> None:
        if self.debug_output_dir is None:
            return
        path = urlparse(url).path.strip("/").replace("/", "_") or "page"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        output_path = self.debug_output_dir / f"{path[:80]}-{digest}.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    async def _delay(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = asyncio.get_running_loop().time() - self._last_request_at
        remaining = self.settings.request_delay_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
