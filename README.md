# parky-scraper

Scrapes publicly accessible, JavaScript-rendered grocery product pages from kosik.sk with Crawl4AI and optionally classifies product names with the existing Qwen/Ollama integration.

## What is included

- `scraper`: renders Kosik product pages, extracts typed product data, and writes JSON.
- `qwen_classifier`: classifies product names through an Ollama-compatible `/api/generate` endpoint.
- `scraper/tests` and `qwen_classifier/tests`: offline tests using local fixtures and mocked HTTP clients.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For live scraping, install the browser dependencies required by the Crawl4AI release installed in your environment.

## Environment configuration

Copy `.env.example` to `.env` and replace the Ollama placeholder with an approved local secret. The scraper settings are non-secret:

```dotenv
SCRAPER_USER_AGENT=Mozilla/5.0
SCRAPER_REQUEST_DELAY_SECONDS=2
SCRAPER_PAGE_TIMEOUT_SECONDS=60
CLASSIFICATION_ENABLED=false
CLASSIFICATION_CONFIDENCE_THRESHOLD=0.75
```

Classification additionally requires:

```dotenv
OLLAMA_BASE_URL=https://ollama.example.invalid
OLLAMA_API_KEY=<your-secret>
OLLAMA_MODEL=qwen3:30b
```

`CLASSIFICATION_CONFIDENCE_THRESHOLD` must be between `0` and `1`. `CLASSIFICATION_ENABLED` is read by scraper configuration and defaults to `false`; the scraper CLI enables classification explicitly with `--classify`. Never commit, print, or log `OLLAMA_API_KEY`.

## Run the scraper

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p39112-citrony" \
  --url "https://www.kosik.sk/p1952-mccain-golden-longs-hranolky" \
  --url "https://www.kosik.sk/p6902-tauris-zipser-parky-71-maesa" \
  --output output/products.json \
  --classify
```

`--url` can be repeated. `--classify` is optional and requires the Ollama configuration. The final array is written to the requested path, while the raw, unclassified array is written beside it with `.raw` inserted before the extension. For example, `output/products.json` produces `output/products.raw.json`. Parent directories are created automatically. The CLI prints only a count and output path.

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

## Run the standalone classifier

The classifier CLI accepts one or more product names and writes an array of validated classifications:

```bash
python -m qwen_classifier.cli \
  --products "K-Classic Mlieko plnotucne 1 l" "McCain Golden Longs hranolky" \
  --output output/classifications.json \
  --mark-needs-review
```

`--mark-needs-review` sets `needs_review` to `true` when confidence is below `CLASSIFICATION_CONFIDENCE_THRESHOLD`. The command requires `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, and `OLLAMA_MODEL`, and prints the resulting JSON to stdout as well as saving it to the requested path.

## Tests

The test suite uses only a local HTML fixture and mocked crawler/classifier objects:

```bash
pytest
```

`python -m scraper.cli --help` and `python -m qwen_classifier.cli --help` are available without network access. Live scraping is sequential, rate-limited, and limited to public pages; it does not bypass CAPTCHA, authentication, bot protection, rate limits, or robots restrictions. Selectors may require maintenance if Kosik changes its page markup.
