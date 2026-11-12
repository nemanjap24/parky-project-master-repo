# Scraper output format (schema 0.2)

This document describes every field the scraper writes. It is the input for the
database schema: each record combines **static product data** and **one price
observation**, so it can be split into a product table and a price-history table.

The Pydantic source of truth is `ProductObservation` in `scraper/models.py`.

## File layout

```text
output/kosik/<YYYY-MM-DD>/observations.jsonl
```

- JSON Lines: UTF-8, one JSON object per line, one line per scraped product page.
- `<YYYY-MM-DD>` is the **UTC date at the start of the run**.
- Runs append to the file for that day. Several runs on the same day share the file and are told apart by `run_id`.
- `python -m scraper.cli --output <path>` writes to a custom path instead, also appending.
- Records are flushed one at a time. If a run fails, every line already written is complete and valid.
- Read the file back with `scraper.output.read_observations(path)`.

## Example

```json
{
  "schema_version": "0.2",
  "run_id": "2026-11-14-kosik-01",
  "scraped_at": "2026-11-14T08:12:44Z",
  "retailer": "kosik",
  "retailer_product_id": "7004",
  "url": "https://www.kosik.sk/p7004-nord-svit-zlate-parky-93-maesa",
  "source_listing_url": "https://www.kosik.sk/c3350-parky",
  "name": "Nord Svit Zlaté párky (93% mäsa)",
  "brand": "Nord Svit",
  "package": {"raw": "250 g", "amount": 250, "unit": "g", "base_quantity": 0.25, "base_unit": "kg"},
  "retailer_category_id": "c3350",
  "retailer_category_path": ["Údeniny a lahôdky", "Párky, klobásy, špekáčiky", "Párky"],
  "country_of_origin": "Slovensko",
  "min_shelf_life_days": 5,
  "currency": "EUR",
  "shelf_price": 3.39,
  "regular_price": null,
  "unit_price": {"value": 13.56, "per": "kg", "computed": 13.56},
  "promotions": [
    {"type": "multibuy", "min_qty": 2, "promo_price": 2.99, "discount_pct": 11, "valid_until": null},
    {"type": "multibuy", "min_qty": 3, "promo_price": 2.69, "discount_pct": 20, "valid_until": null}
  ],
  "in_stock": true,
  "classification": null,
  "extraction": {"source": "json-ld+html", "scraper_version": "0.2.0", "warnings": []}
}
```

## Conventions

- **Money** (`shelf_price`, `regular_price`, `unit_price.value`, `unit_price.computed`, `promotions[].promo_price`) is a `Decimal` in Python, rounded half-up to 2 decimal places. In JSON it is a plain number, so `11.50` appears as `11.5`. Store it as `NUMERIC(10,2)`, not as a float.
- **Quantities** (`package.amount`, `package.base_quantity`) are decimals. Whole numbers are written as integers (`250`).
- **Timestamps** are ISO 8601 in UTC with a `Z` suffix. **Dates** are ISO `YYYY-MM-DD`.
- **Missing values** are `null`, never omitted. Lists are `[]` when empty.
- Records reject unknown fields, so a new field always means a new `schema_version`.
- **Data sources:** JSON-LD (schema.org `Product`, `Offer`, `BreadcrumbList`) is preferred. Rendered HTML is used for fields that JSON-LD does not carry, and as a fallback that is flagged with a warning.

## Fields

Columns: **Group** tells you whether the field belongs to a *run*, the *product* (static, changes rarely), or the *observation* (changes with every scrape).

### Record and run

| Field | Type | Null | Group | Description |
| --- | --- | --- | --- | --- |
| `schema_version` | string | no | run | Output format version, currently `"0.2"`. |
| `run_id` | string | yes | run | `<YYYY-MM-DD>-<retailer>-<NN>`, assigned once at the start of a CLI run; `NN` is the next free number in the target file. `null` only when the pipeline is used without the CLI and no run id is set. |
| `scraped_at` | datetime (UTC) | no | observation | When this page was rendered and parsed. |
| `retailer` | enum `"kosik"` | no | product | Retailer code, lowercase. |
| `url` | string | no | product | Product page URL as requested. |
| `source_listing_url` | string | yes | observation | Category/listing page the URL came from, when the caller provides it (crawler batches, `--source-listing-url`). |

### Product (static data)

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `retailer_product_id` | string | yes | JSON-LD `Product.sku`. Fallback: the number in the URL (`/p7004-…` → `"7004"`). Kept as a string. Together with `retailer` it is the natural product key. |
| `name` | string | yes | JSON-LD `Product.name`. Fallback: the HTML product heading or `og:title`. |
| `brand` | string | yes | JSON-LD `Product.brand.name`. Fallback: the HTML brand link. `null` for unbranded produce (for example lemons). |
| `package` | object | yes | Normalized package size, see [`package`](#package). `null` when the label is missing or not understood (a warning is added). |
| `retailer_category_id` | string | yes | Kosik category id of the most specific breadcrumb entry, taken from its URL (`/c3350-parky` → `"c3350"`). |
| `retailer_category_path` | string[] | no | Kosik breadcrumb names from root to leaf, without the product itself. `[]` when unavailable. |
| `country_of_origin` | string | yes | The "Krajina pôvodu" value exactly as shown (`"Slovensko"`, `"Európska únia"`). Not normalized to ISO codes. |
| `min_shelf_life_days` | integer ≥ 0 | yes | The "Minimálna trvanlivosť" value in days. `null` when not shown. Values that are not in days (weeks, months) are left `null` with the warning `unparsed_shelf_life`. |

### Price observation

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `currency` | string (ISO 4217) | yes | JSON-LD `Offer.priceCurrency`, `"EUR"` on Kosik. `null` when the price comes only from HTML. |
| `shelf_price` | money | yes | Current price for **one piece without any condition** (JSON-LD `Offer.price`). With a plain discount this is already the discounted price. Multikup prices are never used here. |
| `regular_price` | money | yes | Crossed-out original price. Present only when shown, otherwise `null`. |
| `unit_price` | object | yes | Price per base unit, see [`unit_price`](#unit_price). |
| `promotions` | object[] | no | Price conditions shown with the product, see [`promotions[]`](#promotions). Order: `discount`, then `multibuy` tiers by quantity, then `price_match`. |
| `in_stock` | boolean | yes | From JSON-LD `Offer.availability`: `InStock`, `LimitedAvailability`, `OnlineOnly` and `InStoreOnly` → `true`; `OutOfStock`, `SoldOut` and `Discontinued` → `false`; anything else → `null`. The "Do košíka" button text is **not** used. |

### `package`

| Field | Type | Description |
| --- | --- | --- |
| `raw` | string | Label as shown, with whitespace normalized (`"250 g"`, `"4 x 100 g"`). |
| `amount` | decimal > 0 | Total amount in `unit`. For multipacks this is the total: `4 x 100 g` → `400`. |
| `unit` | enum `g`, `kg`, `ml`, `l`, `ks` | Unit of `amount`. |
| `base_quantity` | decimal > 0 | `amount` converted to `base_unit`: `250 g` → `0.25`. |
| `base_unit` | enum `kg`, `l`, `ks` | `g`/`kg` → `kg`, `ml`/`l` → `l`, `ks` → `ks`. |

### `unit_price`

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `value` | money | yes | Unit price as displayed by Kosik. |
| `per` | enum `kg`, `l`, `ks` | yes | Unit of `value`, taken from the "€/kg" text. |
| `computed` | money | yes | `shelf_price / package.base_quantity`, rounded half-up to cents. Use it to check `value`, or when `value` is missing. |

### `promotions[]`

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `type` | enum | no | `discount`: a crossed-out regular price. `multibuy`: a Multikup quantity tier. `price_match`: the "Dorovnaná cena" label (Kosik compares the price with other shops weekly). |
| `min_qty` | integer ≥ 1 | yes | `multibuy` only: the minimum pieces in the cart for `promo_price` to apply. |
| `promo_price` | money | yes | `discount`: equals `shelf_price`. `multibuy`: price per piece at that tier. `price_match`: `null`. |
| `discount_pct` | integer 0–100 | yes | Percentage as shown by Kosik. For a `discount` without a label it is computed from `regular_price` and `shelf_price`. |
| `valid_until` | date | yes | `discount` only, from the label "do DD. MM.". The year is the year of `scraped_at`, or the next year if that date would already be in the past. |

Kosik shows the discount label as `FeatureTag_save_me_label`. This may be a short-shelf-life clearance ("Zachráň ma") rather than a regular campaign. Both are currently stored as `discount`.

### `classification`

`null` unless the scraper runs with `--classify`.

| Field | Type | Description |
| --- | --- | --- |
| `category` | enum | One of `masove_vyrobky`, `mliecne_vyrobky`, `pekaren`, `ovocie_zelenina`, `napoje`, `mrazene`, `sladkosti`, `ine`. |
| `subcategory` | string or null | Short snake_case label suggested by the model (`parky`, `citrusy`). Free text, not a controlled list. |
| `confidence` | number 0–1 | Model's self-reported confidence. |
| `model` | string | Ollama model name, for example `qwen3:30b`. |
| `prompt_version` | string | Version of the classification prompt (`qwen_classifier.prompts.PROMPT_VERSION`). |
| `classified_at` | datetime (UTC) | When the classification was made. |

The LLM receives the product name **and `retailer_category_path`**. It is instructed to map the Kosik breadcrumb to the categories above, and not to guess from the name. A `confidence` below `CLASSIFICATION_CONFIDENCE_THRESHOLD` adds the warning `low_classification_confidence`.

### `extraction`

| Field | Type | Description |
| --- | --- | --- |
| `source` | enum `json-ld+html`, `html` | `json-ld+html` when a JSON-LD `Product` was found. `html` means the HTML fallback only. |
| `scraper_version` | string | Version of the extraction code, currently `0.2.0`. |
| `warnings` | string[] | Data-quality codes, see below. A record is **kept** even when it has warnings. |

`needs_review` is not stored. It is derived as `len(extraction.warnings) > 0`; the Python model exposes it as the `ProductObservation.needs_review` property.

## Warning codes

| Code | Meaning |
| --- | --- |
| `missing_json_ld` | No JSON-LD `Product` on the page; all data comes from HTML. |
| `price_fallback_html` | `shelf_price` was taken from HTML because JSON-LD had no price. |
| `price_source_conflict` | The JSON-LD price and the displayed HTML price differ. JSON-LD wins. |
| `missing_breadcrumb` | JSON-LD exists but has no `BreadcrumbList`. |
| `missing_package` | No package size label found. |
| `unparsed_package` | A package label exists but could not be normalized. |
| `missing_price` | No shelf price at all. |
| `non_positive_price` | `shelf_price <= 0`. |
| `regular_price_not_higher` | `regular_price` exists but is not higher than `shelf_price`. |
| `unit_price_mismatch` | `abs(value - computed) / computed > 0.02`. |
| `unit_price_unit_mismatch` | `unit_price.per` differs from `package.base_unit`, so the two cannot be compared. |
| `unparsed_promotion` | A promotion was shown but could not be parsed (invalid date, or Multikup without readable tiers). |
| `unparsed_shelf_life` | The shelf-life value is not in days. |
| `low_classification_confidence` | The classification confidence is below the configured threshold. |

## Suggested split into tables

This is a suggestion for the schema author, not something the scraper does.

- **product**: key `(retailer, retailer_product_id)`. Columns: `url`, `name`, `brand`, `package_*`, `retailer_category_id`, `retailer_category_path`, `country_of_origin`, `min_shelf_life_days`. Static fields can change over time, so keep the latest values or track their history.
- **price_observation**: key `(retailer, retailer_product_id, scraped_at)` or a surrogate id. Columns: `run_id`, `source_listing_url`, `currency`, `shelf_price`, `regular_price`, `unit_price_*`, `in_stock`, `extraction_*`.
- **promotion**: one row per item of `promotions[]`, referencing `price_observation`.
- **classification**: referencing `product`, or the observation if classifications should be versioned per run. Use `model`, `prompt_version` and `classified_at` to compare classifier versions.
- **run**: `run_id`, retailer, start date.

## Versioning

- `schema_version` changes when fields are added, removed or change meaning.
- `extraction.scraper_version` changes when extraction logic changes, even if the format stays the same.
- `classification.prompt_version` changes when the classification prompt changes.
