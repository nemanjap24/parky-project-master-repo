# parky-scraper

Scrapes publicly accessible, JavaScript-rendered grocery product pages from kosik.sk with Crawl4AI and optionally classifies product names with the existing Qwen/Ollama integration.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For live Crawl4AI use, install its browser dependencies as described by the Crawl4AI release installed in your environment.

## Environment configuration

Copy `.env.example` to `.env`. The scraper settings are non-secret:

```dotenv
SCRAPER_USER_AGENT=Mozilla/5.0
SCRAPER_REQUEST_DELAY_SECONDS=2
SCRAPER_PAGE_TIMEOUT_SECONDS=60
CLASSIFICATION_ENABLED=false
CLASSIFICATION_CONFIDENCE_THRESHOLD=0.75
```

Classification additionally uses the existing Ollama variables (`OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, and `OLLAMA_MODEL`) from the local environment. Never commit or print those values.

## Run the scraper

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p39112-citrony" \
  --url "https://www.kosik.sk/p1952-mccain-golden-longs-hranolky" \
  --url "https://www.kosik.sk/p6902-tauris-zipser-parky-71-maesa" \
  --output output/products.json \
  --classify
```

`--url` can be repeated. To discover all product URLs from Kosik's public product sitemap instead, run:

```bash
python -m scraper.cli --all-products --output output/products.json --classify
```

To test discovery from a specific category whitelist, run:

```bash
python -m scraper.cli --category-products --output output/category-products.json --classify
```

The initial whitelist contains only Kosik's bacon category (`/c3365-slaniny`) in `scraper/crawler.py`. Add exact category paths to `_CATEGORY_WHITELIST` to expand the crawl. Use exactly one of `--url`, `--all-products`, or `--category-products`. The category mode reads the categories sitemap, visits only whitelisted pages, and gathers product links before scraping. `--classify` is optional and requires the Ollama configuration. The final array is written to the requested path; the raw, unclassified array is written beside it as `category-products.raw.json`. The CLI prints only a count and output path.

Example product output:

```json
[
  {
    "retailer": "Kosik",
    "url": "https://www.kosik.sk/product/example",
    "scraped_at": "2026-10-20T00:00:00Z",
    "raw_title": "K-Classic Mlieko plnotucne 1 l",
    "price": 0.89,
    "regular_price": 1.09,
    "price_per_unit": 0.89,
    "unit": "l",
    "weight_or_volume": "1 l",
    "is_discounted": true,
    "availability": "Na sklade",
    "category": "mliecne_vyrobky",
    "subcategory": "mlieko",
    "confidence": 0.9,
    "needs_review": false
  }
]
```

## Classification integration

`ScrapingPipeline` accepts a classifier implementing the existing `QwenClassifier.classify()` interface. It sends the extracted `raw_title` as a one-item batch, then merges category, subcategory, confidence, and review status into the product model. This dependency is injected, so extraction and tests never call Ollama directly.

## Tests

The test suite uses only a local HTML fixture and mocked crawler/classifier objects:

```bash
pytest
```

`python -m scraper.cli --help` is also available without network access. Live scraping is sequential, rate-limited, and limited to public pages; it does not bypass CAPTCHA, authentication, bot protection, rate limits, or robots restrictions. Selectors may require maintenance if Kosik changes its page markup.
