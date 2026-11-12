"""Crawl4AI browser integration for public Kosik product pages."""

from __future__ import annotations

import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

from .config import ScraperSettings, get_scraper_settings


class CrawlError(RuntimeError):
    """Raised when a product page cannot be rendered."""


SITEMAP_URL = "https://www.kosik.sk/sitemap.xml"
_KOSIK_HOSTS = {"www.kosik.sk", "kosik.sk"}
_CATEGORY_WHITELIST = {"/c3365-slaniny"}


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

    async def discover_category_product_urls(self, sitemap_url: str = SITEMAP_URL) -> list[str]:
        """Discover product links from the explicitly whitelisted category pages."""
        sitemap_xml = await self._fetch_sitemap(sitemap_url)
        root = self._parse_sitemap(sitemap_xml, sitemap_url)
        categories_url = self._child_sitemap_url(root, "categories.xml")
        if categories_url is None:
            raise CrawlError(f"No categories sitemap found at {sitemap_url}")

        categories_xml = await self._fetch_sitemap(categories_url)
        categories_root = self._parse_sitemap(categories_xml, categories_url)
        category_urls = self._whitelisted_category_urls(categories_root)
        if not category_urls:
            raise CrawlError(f"No whitelisted categories found at {categories_url}")

        product_urls: set[str] = set()
        for category_url in category_urls:
            html = await self.crawl(category_url, load_all=True, save_debug=False)
            product_urls.update(self._product_links(html, category_url))
        if not product_urls:
            raise CrawlError("No product links found on whitelisted Kosik category pages")
        return sorted(product_urls)

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
        js_code = None
        if load_all:
            js_code = """
                (async () => {
                    for (let i = 0; i < 30; i++) {
                        const button = Array.from(document.querySelectorAll("button"))
                            .find((item) => /načítať ďalšie/i.test(item.innerText));
                        if (!button) break;
                        const before = document.querySelectorAll('a[href*="/p"]').length;
                        button.click();
                        for (let wait = 0; wait < 50; wait++) {
                            await new Promise((resolve) => setTimeout(resolve, 100));
                            if (document.querySelectorAll('a[href*="/p"]').length > before) break;
                        }
                        if (document.querySelectorAll('a[href*="/p"]').length <= before) break;
                    }
                })()
            """
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
    def _whitelisted_category_urls(cls, root: ET.Element) -> list[str]:
        if cls._xml_name(root.tag) != "urlset":
            raise CrawlError("Categories sitemap does not contain a URL set")
        category_urls = set()
        for entry in root:
            if cls._xml_name(entry.tag) != "url":
                continue
            location = cls._child_text(entry, "loc")
            if not location or not cls._is_kosik_url(location):
                continue
            parsed = urlparse(location)
            if parsed.path in _CATEGORY_WHITELIST:
                category_urls.add(urlunparse(("https", parsed.netloc, parsed.path, "", "", "")))
        return sorted(category_urls)

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
