# AI Coding Agent Guide

## Project overview

`parky-scraper` is the data-collection and classification prototype for the academic **AI PARKY** project. The wider platform is intended to collect competitor and market prices, normalize and match product data, analyze historical price movements, forecast prices, recommend selling prices, and visualize those results.

The current repository deliberately covers only an early slice of that goal: scrape publicly accessible JavaScript-rendered product pages from `kosik.sk`, extract a typed product observation (schema 0.2: static product data plus one price observation), optionally classify it through Qwen/Ollama using Kosik's breadcrumb, and append it to daily JSONL files. It does **not** yet provide a database, multi-retailer integration, scheduling, matching, analytics, forecasts, recommendation logic, frontend, or deployment.

## Repository structure

| Path | Responsibility and main entry points |
| --- | --- |
| `scraper/` | Kosik scraping package. `crawler.py` contains `KosikCrawler` (page rendering plus sitemap and category-page URL discovery); `discovery.py` defines the category whitelist and the discovery manifest; `extraction.py` contains `extract_product`; `jsonld.py` parses schema.org JSON-LD; `promotions.py` parses Multikup tiers and discount labels; `package.py` normalizes package sizes; `validation.py` computes unit prices and warning codes; `models.py` defines `ProductObservation` and its nested models; `pipeline.py` coordinates scraping and optional classification; `output.py` writes JSONL and assigns run ids; `config.py` reads scraper settings; `cli.py` is run with `python -m scraper.cli`. `fixtures/kosik_*.html` are six real rendered Kosik pages used by regression tests; `tests/` covers parsing, models, validation, pipeline, and output. |
| `config/kosik_categories.json` | Whitelist of Kosik categories to collect, by category id (`c3365`), with an optional weekend day (`fri`, `sat`, `sun`). Validated by `CategoryWhitelist`. |
| `qwen_classifier/` | Qwen/Ollama classification package. `client.py` contains `QwenClassifier`; `prompts.py` builds the constrained classification prompt; `models.py` defines Pydantic response contracts; `config.py` reads Ollama settings; `cli.py` is run with `python -m qwen_classifier.cli`. Its `tests/` validate prompts, models, and mocked HTTP behavior. |
| `README.md` | User-facing setup, configuration, usage, architecture summary, and test documentation. |
| `docs/output-format.md` | Field-by-field description of the JSONL output and warning codes; the basis for the future database schema. Keep it in sync with `scraper/models.py`. |
| `docs/known-issues.md` | Open problems and follow-ups with evidence and proposed fixes. |
| `docs/scraper-model-v2.md` | Task specification that introduced output schema 0.2. |
| `requirements.txt` | Runtime and test dependencies: Crawl4AI, HTTP client, Pydantic, dotenv, and pytest. |
| `.env.example` | Template for required local scraper and Ollama configuration. Copy it to `.env`; do not put real credentials in it. |
| `pytest.ini` | Pytest configuration; adds the repository root to `pythonpath`. |
| `.gitignore` | Ignores Python/build artifacts, virtual environments, `.env`, generated scraper output (`scraper/output/` and `output/`), and other local artifacts. |

## Current architecture

```text
config/kosik_categories.json (category ids, day)
   |
   v
KosikCrawler.discover_category_listings
   |-- sitemap.xml -> categories.xml (find category URL by id)
   |-- render category page, click "Načítať ďalšie", collect /p… links
   v
DiscoveryManifest -> discovery-<run_id>.json (per category: URL, product URLs, complete?)
   |
   v  per category: scrape_many(urls, source_listing_url=category URL)
URL produktu
   |
   v
KosikCrawler.crawl (rendered HTML)
   |
   v
extract_product
   |-- parse_product_json_ld   (sku, name, brand, price, currency, stock, breadcrumb)
   |-- HTML                    (package, unit price, promotions, origin, shelf life, fallbacks)
   |-- observation_warnings    (consistency checks -> extraction.warnings)
   v
ProductObservation
   |
   +--> [optional] QwenClassifier (name + breadcrumb) -> classification
   |
   v
JsonlWriter -> output/kosik/<YYYY-MM-DD>/observations.jsonl (append, 1 line = 1 product)
```

`KosikCrawler` accepts only public `kosik.sk` URLs, applies the configured request delay, and renders the page with headless Crawl4AI/Playwright. Those browser components are required because the product content is JavaScript-rendered; the crawler waits for the populated Kosik application before returning HTML.

URL discovery is part of `KosikCrawler`. `discover_category_listings(categories)` reads `sitemap.xml` and `categories.xml` with `httpx`, finds the whitelisted categories by id, renders each category page with a load-more script, and returns a `DiscoveryManifest` grouped by category. Sitemap requests use the same request delay as page renders. The CLI saves the manifest before scraping, scrapes each category as one `scrape_many` batch with `source_listing_url`, scrapes duplicates only once, and can resume with `--from-manifest` and `--skip-existing`. `discover_product_urls()` (`--all-products`) covers the whole product sitemap and is for debugging only.

`extract_product` deterministically turns a rendered page into a `ProductObservation`. JSON-LD (`Product`, `Offer` referenced by `@id`, `BreadcrumbList`) is the primary source for identity, `shelf_price`, currency, `in_stock`, and the Kosik category. HTML provides the package size, unit price, crossed-out price, promotions (`discount`, `multibuy`, `price_match`), country of origin, and minimum shelf life, and serves as a fallback. `shelf_price` is the unconditional one-piece price and must never come from Multikup tiers. Problems never raise: they are appended as codes to `extraction.warnings`, and `needs_review` is derived from that list. Prices are `Decimal` and serialized as JSON numbers. `docs/output-format.md` lists every field and warning code.

`ScrapingPipeline` injects the crawler, an optional classifier, a clock, and the `run_id`. `scrape_many(urls, source_listing_url=..., on_result=...)` is the batch entry point for the category crawler; it scrapes sequentially, and `on_result` lets callers persist each record immediately. When classification is selected, the pipeline sends a `ClassificationInput` (name plus `retailer_category_path`) to `QwenClassifier`. It stores `classification` with category, subcategory, confidence, model, `prompt_version`, and `classified_at`, and adds `low_classification_confidence` when the confidence is below the threshold. The Qwen client calls Ollama's `/api/generate` using `qwen3:30b` by default, with `stream=false`, `think=false`, temperature `0`, a JSON schema, and Pydantic validation. The prompt (`PROMPT_VERSION` in `qwen_classifier/prompts.py`; bump it whenever the prompt changes) makes the breadcrumb the primary signal. Its eight supported broad categories are `masove_vyrobky`, `mliecne_vyrobky`, `pekaren`, `ovocie_zelenina`, `napoje`, `mrazene`, `sladkosti`, and `ine`.

The scraper CLI appends records to `output/kosik/<YYYY-MM-DD>/observations.jsonl` (UTC date at run start) or to the `--output` path. It assigns a `run_id` like `2026-11-14-kosik-01`, numbered after the highest id already in that file. With `--classify` the records include `classification`; there is no separate raw file. The standalone classifier CLI writes and prints classifications for supplied product names.

## Commands

Run these commands from the repository root.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest
```

For live Crawl4AI scraping, install the browser dependencies required by the installed Crawl4AI release before running a scrape.

Collect Friday's whitelisted categories with classification:

```bash
python -m scraper.cli --category-products --day fri --classify
```

Test one category with a small product limit:

```bash
python -m scraper.cli --category-products --category c3365 --limit 15 --classify --output output/test-slaniny.jsonl
```

Resume an interrupted run from its discovery manifest:

```bash
python -m scraper.cli \
  --from-manifest output/kosik/2026-11-14/discovery-2026-11-14-kosik-01.json \
  --skip-existing
```

Scrape individual URLs without classification (appends to `output/kosik/<YYYY-MM-DD>/observations.jsonl`):

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p39112-citrony"
```

Scrape a listing batch with Qwen/Ollama classification into a custom file:

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p7004-nord-svit-zlate-parky-93-maesa" \
  --url "https://www.kosik.sk/p6902-tauris-zipser-parky-71-maesa" \
  --source-listing-url "https://www.kosik.sk/c3350-parky" \
  --output output/parky.jsonl \
  --classify
```

Run the standalone classifier CLI:

```bash
python -m qwen_classifier.cli \
  --products "K-Classic Mlieko plnotucne 1 l" "McCain Golden Longs hranolky" \
  --output output/classifications.json \
  --mark-needs-review
```

## Environment variables

| Variable | Used by | Purpose | Secret? |
| --- | --- | --- | --- |
| `SCRAPER_USER_AGENT` | scraper | Browser user-agent string. | No |
| `SCRAPER_REQUEST_DELAY_SECONDS` | scraper | Minimum delay between crawler requests; default `2`. | No |
| `SCRAPER_PAGE_TIMEOUT_SECONDS` | scraper | Page-render timeout in seconds; default `60`. | No |
| `CLASSIFICATION_ENABLED` | scraper | Enables pipeline classification when no explicit `classify` argument overrides it; `true` or `false`. | No |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | scraper and classifier | Value from `0` through `1` below which classification is marked for review. | No |
| `OLLAMA_BASE_URL` | classifier | Base URL of the Ollama-compatible service. | No |
| `OLLAMA_API_KEY` | classifier | Bearer token sent to Ollama. | **Yes** |
| `OLLAMA_MODEL` | classifier | Ollama model name, such as `qwen3:30b`. | No |
| `OLLAMA_TIMEOUT_SECONDS` | classifier | HTTP timeout for one Ollama request; default `120`. | No |

`OLLAMA_API_KEY` must never be committed, hardcoded, printed, logged, or included in examples. Keep it only in an ignored local environment source or an approved secret manager. The classifier requires `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, and `OLLAMA_MODEL` when it is constructed.

## Coding standards

- [ ] Keep code compatible with Python 3.10+ and use type hints.
- [ ] Use Pydantic models for external data contracts, including scraped and model/API data.
- [ ] Inject external services (crawler, HTTP client, classifier) so business logic remains testable offline.
- [ ] Keep secrets out of code, tests, fixtures, logs, generated output, and documentation.
- [ ] Do not make real network calls from unit tests.
- [ ] Raise clear, contextual exceptions and preserve useful error messages.
- [ ] Prefer small, focused modules over broad utility layers.
- [ ] Add or update tests for every new behavior.
- [ ] Update both `README.md` and this file when user-visible behavior or architecture changes.
- [ ] When output fields change, update `docs/output-format.md` and bump `SCHEMA_VERSION`; when extraction logic changes, bump `SCRAPER_VERSION` (both in `scraper/models.py`).
- [ ] Report data problems as `extraction.warnings` codes rather than raising or silently dropping values.

## Testing rules

Run the complete suite with:

```bash
pytest
```

All current tests are offline. `scraper/tests/test_regression_kosik.py` pins expected values for six real rendered pages in `scraper/fixtures/kosik_*.html`, including the Multikup shelf-price regression, dated discounts, "Dorovnaná cena", and an empty `warnings` list. Pipeline and CLI tests inject fake crawler and classifier implementations and write to `tmp_path`. When a Kosik markup change breaks extraction, add the new rendered page as a fixture with pinned expectations; review it for sensitive data first. Classifier client tests use `httpx.MockTransport`; they do not contact Ollama.

A live manual test is appropriate only when changing browser rendering, Kosik selectors, or real Ollama integration, and only after the offline tests pass. Keep live scraping sequential, publicly accessible, respectful, and rate-limited by `SCRAPER_REQUEST_DELAY_SECONDS`. Do not present a live scrape or Ollama result as tested unless it was actually run.

## Security and scraping rules

- Never bypass CAPTCHA, authentication, bot protection, rate limits, or robots restrictions.
- Use only publicly accessible pages.
- Never store or expose credentials.
- Preserve request delays; do not add aggressive parallel scraping.
- Do not commit output files that may contain sensitive operational data.
- Treat rendered HTML/debug output and API error text as potentially sensitive operational artifacts; keep them out of commits and logs unless explicitly reviewed and safe.

## Roadmap

### Phase 1 — Data collection

- Improve the Kosik scraper and add retailer-specific extractors.
- Add Tesco, Lidl, Kaufland, and optionally Wolt Market.
- Add scheduled daily collection, retries, logging, and monitoring.

### Phase 2 — Data integration

- Design a PostgreSQL schema.
- Normalize data, match products across retailers, store price history, and add data-quality checks.

### Phase 3 — Analysis

- Analyze price history, category indexes, trends, seasonality, and price dispersion across retailers.

### Phase 4 — Prediction

- Build time-series and ML models for input-material and product-price predictions, with evaluation metrics.

### Phase 5 — Pricing recommendations

- Combine cost, competitor-price, and margin inputs into a recommended selling price with an explanation.

### Phase 6 — Web application

- Add a FastAPI backend, PostgreSQL persistence, and Vue frontend.
- Provide product lists and filters, product details with price charts, category charts, and a custom index for selected products.

### Phase 7 — Evaluation

- Evaluate prediction accuracy and economic impact, and document limitations.

## Current limitations

Open issues with evidence and proposed fixes are tracked in `docs/known-issues.md`; update it when you fix or find one.

- The category whitelist currently holds only example categories; the team still has to fill in the ~16 subcategories and their days.
- Category discovery depends on clicking "Načítať ďalšie" (at most 30 clicks). The result is reported through a `data-parky-load-more` marker on `<body>`; a listing is marked `complete: false` when the limit is hit or the marker is missing. Whether Kosik offers URL-based pagination has not been checked.

- Only Kosik is implemented.
- Output schema 0.2 is file-based (JSONL); the database schema is being designed separately from `docs/output-format.md`.
- A failing URL stops the run; records already written are kept, but there is no per-URL retry or skip yet.
- `run_id` numbering assumes runs into the same file are sequential, not concurrent.
- Classification uses broad food categories, not the future domain taxonomy.
- There is no database persistence, scheduler, frontend, prediction model, cross-retailer product matching, or production deployment.

## Agent workflow

1. Read this file and `README.md`.
2. Inspect the relevant source files and tests before changing code.
3. Make the smallest coherent change.
4. Add or update tests.
5. Run `pytest`.
6. Update documentation when behavior or architecture changes.
7. Do not commit secrets.
8. Do not claim live scraping or Ollama integration was tested unless it was actually run.
