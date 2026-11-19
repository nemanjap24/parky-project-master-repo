# Known issues and follow-ups

Open problems found in schema 0.2 and the category crawler, with the evidence and a proposed fix. Remove an entry when it is fixed, and mention the fixing commit or PR in its place.

Last updated: 2026-11-20 (Qwen prompt batch benchmark).

## 1. Variable-weight packages (`cca 850 g`) are not parsed

- **Symptom:** the record has `package: null`, `unit_price.computed: null`, and the warning `unparsed_package`.
- **Evidence:** live run on category `c3365` (Slaniny) with `--limit 15`. 9 of 15 products have labels like `cca 850 g`. Their prices are otherwise consistent, for example 5.09 € / 0.85 kg = 5.99 €/kg, the value Kosik shows.
- **Additional evidence:** the 100-product prompt batch benchmark reported `unparsed_package` for 14 products. Its report stores warning codes, but not the package labels, so it is unknown how many are the same approximate-weight case.
- **Impact:** a high share of meat products is sold by approximate weight, so the per-kg price is the comparable value for them, not the per-piece price. These records are now all marked for review.
- **Proposed fix:** accept the `cca` prefix in `scraper/package.py` and add `package.approximate: bool`. Document the field in `docs/output-format.md`. Optionally relax the `unit_price_mismatch` tolerance for approximate packages. Add the label to the parser tests and a rendered page to the fixtures.

## 2. "0 clicks, complete" may hide an unmatched load-more button

- **Symptom:** discovery of `c3365` reported 30 products, `load_more_clicks: 0`, `complete: true`.
- **Cause:** the load-more script marks a listing complete when it cannot find a button whose text matches `načítať ďalšie`. If Kosik renames the button, the list is silently truncated and still reported as complete.
- **To check:** open https://www.kosik.sk/c3365-slaniny and compare the product count with 30.
- **Proposed fix:** compare the number of collected links with the product count shown on the category page, if Kosik shows one, and mark the listing incomplete when they differ. Alternatively, find out whether category listings support URL-based pagination, which would be more robust than clicking.

## 3. Classification confidence does not separate uncertain cases

- **Symptom:** every classified product so far has `confidence: 0.95`, including the 15 bacon products and the two sausage products.
- **Impact:** `low_classification_confidence` effectively never fires, so a wrong category would not be flagged.
- **Proposed fix:** evaluate on a mixed sample where the breadcrumb and the name disagree. Consider a deterministic mapping from the Kosik category id (`retailer_category_ids`) to our taxonomy, with the LLM only for unmapped categories, and record which source decided the category.

## 4. The category whitelist holds only examples

- **Symptom:** `config/kosik_categories.json` contains `c3365` (Slaniny) and `c3350` (Párky), both on Friday.
- **Needed:** the team's list of about 16 subcategories (about 1600 products), split over Friday to Sunday (about 5 per day).

## 5. A failing URL stops the run

- **Symptom:** one render or extraction error aborts the whole run. Records written so far are kept.
- **Workaround:** resume with `--from-manifest output/…/discovery-<run_id>.json --skip-existing`.
- **Proposed fix:** retry each URL a limited number of times, then skip it. Log the failures to a file next to the observations, and report them at the end of the run.

## 6. Prompt batch benchmark can report successful scraping with incomplete JSONL output

- **Symptom:** the benchmark report records 100 successful pages, but the corresponding products JSONL contains only 59 unique observations.
- **Evidence:** run `20261119T225928Z-prompt-benchmark`: the JSON report lists 100 successful pages; `output/prompt-batch-products-20261119T225928Z.jsonl` contains products 1–38 and 80–100. Products 39–79 are missing. The cause is unknown.
- **Impact:** the persisted dataset is incomplete, so the recorded scrape count cannot be verified from the observations file or used as a complete input archive.
- **Proposed fix:** reproduce the discrepancy and inspect the writer lifecycle and any concurrent access to the output path. Before marking scraping complete, verify the number of persisted, parseable JSONL records against the number of successful pages; report a clear failure if they differ.

## 7. Prompt batch benchmark does not save per-product classification results

- **Symptom:** the benchmark report stores request timings, category totals, and name-mismatch counts, but not each product's predicted category, subcategory, or confidence.
- **Evidence:** all three batch sizes reported 100 completed classifications, but their category totals differed (for example, `sladkosti` was 11, 9, and 12). The report does not include per-product outputs to compare those classifications.
- **Impact:** the benchmark measures completion and throughput, but cannot show whether changing the batch size changed a particular product's result or whether a result was correct.
- **Proposed fix:** write one classification result per product and batch size to a separate JSONL or JSON output, including the input index, batch size, product name, category, subcategory, and confidence. Add an evaluation against labeled examples before drawing accuracy conclusions.

## 8. Review price consistency warnings from the 100-product sample

- **Symptom:** the benchmark recorded several price-related extraction warnings across the sampled product pages.
- **Evidence:** `output/prompt-batch-benchmark-20261119T225928Z.json` reports `price_source_conflict` on 13 products, `unit_price_mismatch` on 11, `regular_price_not_higher` on 6, and `unit_price_unit_mismatch` on 2. A product can have more than one warning.
- **Impact:** these warnings flag records for review, but the aggregate counts do not establish whether the cause is an extraction defect, inconsistent retailer data, or a legitimate pricing case.
- **Proposed fix:** inspect the affected page URLs and compare the extracted values with the rendered product data. Add reviewed pages as fixtures and update extraction or validation rules only for confirmed cases.

## 9. Smaller limitations

- `run_id` numbering assumes runs into the same file are sequential, not concurrent.
- Output dates and the `run_id` use the UTC date at the start of the run. A run shortly after local midnight belongs to the previous day.
- Money is written as a JSON number rounded to cents (`11.5`, not `11.50`).
- The discount label (`FeatureTag_save_me_label`) may be a short-shelf-life clearance ("Zachráň ma") rather than a regular campaign. Both are stored as `discount`.
- `min_shelf_life_days` is only parsed when the value is given in days; weeks and months produce `unparsed_shelf_life`.
- Each page render starts a new headless browser, which is slow for about 1600 products.
