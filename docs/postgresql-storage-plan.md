# PostgreSQL storage implementation plan

## Recommendation

Use PostgreSQL as the queryable store and keep the existing JSONL files as the
durable source archive. Import records from JSONL into PostgreSQL in a separate,
repeatable step. This fits the current output model, where one record contains
both product details and a point-in-time price observation.

## Proposed tables and fields

| Table | What to store |
| --- | --- |
| `retailers` | `id`, unique retailer `code` (currently `kosik`). Provides a clean path to adding other retailers. |
| `scrape_runs` | `run_id`, `retailer_id`, `started_at`, `finished_at`, run type/status, schema and scraper versions. Optionally keep the discovery manifest as `JSONB`; do not store the full product record as JSONB. |
| `retailer_categories` | `id`, `retailer_id`, retailer's category ID, name, and nullable `parent_id`. A self-referencing parent relation represents the breadcrumb tree. |
| `products` | Internal `id`, `retailer_id`, retailer product ID, canonical product URL, and the latest name/brand. Treat a product as a retailer listing, not a cross-retailer matched item. |
| `observations` | `id`, `product_id`, `run_id`, `scraped_at`, `source_listing_url`; observed product details that may change (name, brand, package, category, origin, shelf life); currency, shelf and regular prices, unit-price fields, stock status; extraction source, warnings, schema version, and scraper version. |
| `promotions` | `id`, `observation_id`, type, minimum quantity, promotion price, discount percentage, and validity date. Store promotions as rows rather than a JSON array, so they can be queried and constrained. |
| `product_classifications` | `id`, `observation_id`, category, subcategory, confidence, model, prompt version, and classification timestamp. A classification belongs to the observation it was produced from, preserving its input context and history. |

## Relations and key rules

```text
retailers 1 ── many scrape_runs
retailers 1 ── many products
retailers 1 ── many retailer_categories
retailer_categories 1 ── many child categories
products 1 ── many observations
scrape_runs 1 ── many observations
observations 1 ── many promotions
observations 1 ── zero-or-one classification per model/prompt version
```

- Use a unique key on `(retailer_id, retailer_product_id)` when the retailer ID
  exists. For records without one, use a retailer-scoped canonical URL as the
  fallback identity.
- Add a unique constraint on `(product_id, run_id)` in `observations`. This
  makes re-imports idempotent and prevents duplicate observations within a run.
- Uniquely identify categories by `(retailer_id, retailer_category_id)`.
- Use foreign keys throughout. Keep category IDs and names in
  `retailer_categories`; observations reference the category at scrape time.
- Use `NUMERIC(10,2)` for money, numeric types for package quantities,
  `TIMESTAMPTZ` for timestamps, and `DATE` for promotion end dates.
- Store extraction `warnings` as a text array initially. Derive `needs_review`
  from whether warnings exist; do not store it redundantly.

Keep product/package values needed for historical interpretation—especially
package quantity and unit—on each observation, even if `products` also holds
the latest values. This avoids losing the context for historical unit prices
when a product's name, size, or category changes.

The selected fields follow the current output contract in
[`output-format.md`](./output-format.md) and its source model in
[`scraper/models.py`](../scraper/models.py). Defer cross-retailer product
matching, analytics tables, and raw rendered HTML storage; they are not needed
for this first database version.

## Implementation phases

1. **Confirm storage decisions:** retain JSONL as the archive; use PostgreSQL
   only for structured records; keep the discovery manifest in the run row only
   if coverage queries are needed.
2. **Create and migrate the schema:** add the tables, indexes, foreign keys, and
   constraints above using the project's chosen migration tool.
3. **Build the importer:** read JSONL, create or find the run and product,
   insert observations and their promotions/classifications in a transaction,
   and report malformed or rejected records explicitly.
4. **Make imports repeatable:** use the uniqueness rules to safely retry
   imports. Assign records without a `run_id` a database import/run identifier
   so every observation has a valid run reference.
5. **Backfill and verify:** import existing JSONL files, compare imported
   counts and key values against the source, and test that re-importing produces
   no duplicates.
6. **Operate safely:** keep database credentials out of the repository, connect
   to a remote database through the approved private access method, and back up
   PostgreSQL separately from the JSONL archive.
