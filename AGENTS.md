# AI Coding Agent Guide

## Project overview

`parky-scraper` is the data-collection and classification prototype for the academic **AI PARKY** project. The wider platform is intended to collect competitor and market prices, normalize and match product data, analyze historical price movements, forecast prices, recommend selling prices, and visualize those results.

The current repository deliberately covers only an early slice of that goal: scrape publicly accessible JavaScript-rendered product pages from `kosik.sk`, extract product fields, optionally classify product titles through Qwen/Ollama, and write JSON. It does **not** yet provide a database, multi-retailer integration, scheduling, matching, analytics, forecasts, recommendation logic, frontend, or deployment.

## Repository structure

| Path | Responsibility and main entry points |
| --- | --- |
| `scraper/` | Kosik scraping package. `crawler.py` contains `KosikCrawler`; `extraction.py` contains `extract_product`; `models.py` defines `ScrapedProduct`; `pipeline.py` coordinates scraping and optional classification; `config.py` reads scraper settings; `cli.py` is run with `python -m scraper.cli`. `fixtures/` contains local rendered-HTML samples and `tests/` covers extraction, models, and pipeline behavior. |
| `qwen_classifier/` | Qwen/Ollama classification package. `client.py` contains `QwenClassifier`; `prompts.py` builds the constrained classification prompt; `models.py` defines Pydantic response contracts; `config.py` reads Ollama settings; `cli.py` is run with `python -m qwen_classifier.cli`. Its `tests/` validate prompts, models, and mocked HTTP behavior. |
| `README.md` | User-facing setup, configuration, usage, architecture summary, and test documentation. |
| `requirements.txt` | Runtime and test dependencies: Crawl4AI, HTTP client, Pydantic, dotenv, and pytest. |
| `.env.example` | Template for required local scraper and Ollama configuration. Copy it to `.env`; do not put real credentials in it. |
| `pytest.ini` | Pytest configuration; adds the repository root to `pythonpath`. |
| `.gitignore` | Ignores Python/build artifacts, virtual environments, `.env`, generated scraper output (`scraper/output/` and `output/`), and other local artifacts. |

## Current architecture

```text
URL produktu
   |
   v
KosikCrawler
   |
   v
extract_product
   |
   v
ScrapedProduct
   |
   +--> products.raw.json
   |
   +--> QwenClassifier
           |
           v
        products.json
```

`KosikCrawler` accepts only public `kosik.sk` URLs, applies the configured request delay, and renders the page with headless Crawl4AI/Playwright. Those browser components are required because the product content is JavaScript-rendered; the crawler waits for the populated Kosik application before returning HTML.

`extract_product` deterministically parses rendered HTML into a `ScrapedProduct`: title, price, regular price, unit price, weight/volume, availability, brand, discount state, URL, and scrape timestamp. `ScrapedProduct` is a Pydantic contract and carries optional classification fields.

`ScrapingPipeline` injects the crawler and an optional classifier. When classification is selected, it passes the product `raw_title` to `QwenClassifier`, then merges category, subcategory, confidence, and `needs_review` into the product. The Qwen client calls Ollama's `/api/generate` using `qwen3:30b` by default, with `stream=false`, `think=false`, temperature `0`, a JSON schema, and Pydantic validation. Its eight supported broad categories are `masove_vyrobky`, `mliecne_vyrobky`, `pekaren`, `ovocie_zelenina`, `napoje`, `mrazene`, `sladkosti`, and `ine`.

The scraper CLI always writes the unclassified scrape results beside the requested output as `products.raw.json` (for example, `output/products.raw.json`). With `--classify`, the requested `products.json` contains merged classification fields; without it, the requested output and raw output contain the same unclassified records. The standalone classifier CLI writes and prints classifications for supplied product names.

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

Scrape without classification:

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p39112-citrony" \
  --output output/products.json
```

Scrape with Qwen/Ollama classification:

```bash
python -m scraper.cli \
  --url "https://www.kosik.sk/p39112-citrony" \
  --url "https://www.kosik.sk/p1952-mccain-golden-longs-hranolky" \
  --output output/products.json \
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

## Testing rules

Run the complete suite with:

```bash
pytest
```

All current tests are offline. Scraper extraction tests use local HTML fixtures, and pipeline tests inject fake crawler and classifier implementations. Classifier client tests use `httpx.MockTransport`; they do not contact Ollama.

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

- Only Kosik is implemented.
- The JSON output is not yet the final meat-product schema.
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
