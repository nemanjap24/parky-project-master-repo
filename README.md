# parky-scraper

Scrapes publicly accessible, JavaScript-rendered grocery product pages from kosik.sk with Crawl4AI and writes one JSONL record per product: static product data plus one price observation. It can optionally classify products with the Qwen/Ollama integration, using Kosik's own category breadcrumb.

## What is included

- `scraper`: renders Kosik product pages and extracts typed observations (schema 0.2). JSON-LD is the primary data source, with rendered HTML as a flagged fallback. Results are appended to daily JSONL files.
- `qwen_classifier`: classifies products through an Ollama-compatible `/api/generate` endpoint.
- `scraper/tests` and `qwen_classifier/tests`: offline tests using rendered-page fixtures and mocked HTTP clients.
- `docs/output-format.md`: field-by-field description of the output, written as the basis for the database schema.

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
OLLAMA_TIMEOUT_SECONDS=120
```

`CLASSIFICATION_CONFIDENCE_THRESHOLD` must be between `0` and `1`. `OLLAMA_TIMEOUT_SECONDS` is the HTTP timeout for one Ollama request (default `120`, must be greater than `0`). `CLASSIFICATION_ENABLED` is read by scraper configuration and defaults to `false`; the scraper CLI enables classification explicitly with `--classify`. Never commit, print, or log `OLLAMA_API_KEY`.

## Run the scraper

### Weekend collection from whitelisted categories

The categories to collect are listed in [`config/kosik_categories.json`](config/kosik_categories.json) by their stable Kosik id (`c3365`), with the weekend day they belong to:

```json
{"categories": [{"id": "c3365", "name": "Slaniny", "day": "fri"}]}
```

```bash
python -m scraper.cli --category-products --day fri --classify
```

1. The crawler reads Kosik's public `sitemap.xml` and `categories.xml` and finds each whitelisted category **by id**, so a renamed URL slug does not drop it. Ids that are missing from the sitemap are reported.
2. It renders each category page, clicks "Načítať ďalšie" up to 30 times, and collects the product links. A category whose list may be truncated (click limit reached, or the loading state is unknown) is reported as **incomplete**.
3. The URLs are saved per category to `discovery-<run_id>.json` next to the output file before any product is scraped.
4. Products are scraped category by category with `source_listing_url` set. A product listed in several categories is scraped once, under the first one. If a product's own breadcrumb is not under the listing category (for example a recommended product), the record gets the warning `outside_listing_category`.

To resume an interrupted run without discovering again, scraping only the products that are still missing:

```bash
python -m scraper.cli --from-manifest output/kosik/2026-11-14/discovery-2026-11-14-kosik-01.json --skip-existing
```

`--all-products` lists every product in Kosik's product sitemap, without category information. It is meant for debugging only, because it covers the whole shop.

### Individual product URLs

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p7004-nord-svit-zlate-parky-93-maesa" \
  --url "https://www.kosik.sk/p6902-tauris-zipser-parky-71-maesa" \
  --source-listing-url "https://www.kosik.sk/c3350-parky" \
  --classify
```

- `--url` can be repeated. URLs are scraped sequentially and rate-limited by `SCRAPER_REQUEST_DELAY_SECONDS`.
- By default, records are **appended** to `output/kosik/<YYYY-MM-DD>/observations.jsonl`, where the date is the UTC date at the start of the run. `--output <path>` appends to a custom JSONL file instead.
- Each run gets a `run_id` such as `2026-11-14-kosik-01`. The number continues from the highest run id already in the target file.
- `--source-listing-url` (optional, only with `--url`) records the category page the URLs came from.
- `--classify` (optional) adds a `classification` object and requires the Ollama configuration.
- Records are written one by one as they are scraped, so a failure keeps everything scraped before it. The CLI prints the run id, the count and the output path.
- `--skip-existing` skips product URLs that already have a record in the output file.
- Use exactly one source: `--url`, `--category-products`, `--from-manifest`, or `--all-products`.

Programmatic batches use the same pipeline:

```python
from scraper.output import JsonlWriter
from scraper.pipeline import ScrapingPipeline

pipeline = ScrapingPipeline(run_id="2026-11-14-kosik-01")
with JsonlWriter(path) as writer:
    await pipeline.scrape_many(urls, source_listing_url=listing_url, on_result=writer.write)
```

## Output format

One line per product. A shortened example:

```json
{
  "schema_version": "0.2",
  "run_id": "2026-11-14-kosik-01",
  "scraped_at": "2026-11-14T08:12:44Z",
  "retailer": "kosik",
  "retailer_product_id": "7004",
  "url": "https://www.kosik.sk/p7004-nord-svit-zlate-parky-93-maesa",
  "name": "Nord Svit Zlaté párky (93% mäsa)",
  "package": {"raw": "250 g", "amount": 250, "unit": "g", "base_quantity": 0.25, "base_unit": "kg"},
  "retailer_category_path": ["Údeniny a lahôdky", "Párky, klobásy, špekáčiky", "Párky"],
  "shelf_price": 3.39,
  "unit_price": {"value": 13.56, "per": "kg", "computed": 13.56},
  "promotions": [
    {"type": "multibuy", "min_qty": 2, "promo_price": 2.99, "discount_pct": 11, "valid_until": null}
  ],
  "in_stock": true,
  "classification": null,
  "extraction": {"source": "json-ld+html", "scraper_version": "0.2.0", "warnings": []}
}
```

Key rules:

- `shelf_price` is the unconditional price for one piece. Multikup tiers, crossed-out prices and "Dorovnaná cena" go into `promotions`.
- Data-quality problems never stop extraction. They are recorded as codes in `extraction.warnings`, for example `unit_price_mismatch`, and a record needs review when that list is not empty.

See [`docs/output-format.md`](docs/output-format.md) for every field, the warning codes and a suggested table split.

## Classification integration

`ScrapingPipeline` accepts a classifier implementing the `QwenClassifier` interface. It sends the product name **together with the Kosik breadcrumb** (`retailer_category_path`), and the prompt tells the model to map that breadcrumb to the broad categories rather than guess from the name. The result is stored as:

```json
"classification": {
  "category": "masove_vyrobky",
  "subcategory": "parky",
  "confidence": 0.93,
  "model": "qwen3:30b",
  "prompt_version": "2026-11-breadcrumb-v1",
  "classified_at": "2026-11-14T08:12:47Z"
}
```

Confidence below `CLASSIFICATION_CONFIDENCE_THRESHOLD` adds the warning `low_classification_confidence`. The classifier is injected, so extraction and tests never call Ollama directly.

## Run the standalone classifier

The classifier CLI accepts one or more product names and writes an array of validated classifications. It does not take breadcrumbs:

```bash
python -m qwen_classifier.cli \
  --products "K-Classic Mlieko plnotucne 1 l" "McCain Golden Longs hranolky" \
  --output output/classifications.json \
  --mark-needs-review
```

`--mark-needs-review` sets `needs_review` to `true` when confidence is below `CLASSIFICATION_CONFIDENCE_THRESHOLD`. The command requires `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, and `OLLAMA_MODEL`, and prints the resulting JSON to stdout as well as saving it to the requested path.

## Tests

```bash
pytest
```

The suite runs offline. Regression tests parse six real rendered Kosik pages in `scraper/fixtures/kosik_*.html`: sausages with Multikup, lemons and fries with a dated discount, bacon with "Dorovnaná cena", and oranges. Pipeline and CLI tests use a fake crawler, and classifier tests use `httpx.MockTransport`.

`python -m scraper.cli --help` and `python -m qwen_classifier.cli --help` are available without network access. Live scraping is sequential, rate-limited, and limited to public pages; it does not bypass CAPTCHA, authentication, bot protection, rate limits, or robots restrictions. Selectors may require maintenance if Kosik changes its page markup.
