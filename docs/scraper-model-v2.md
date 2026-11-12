# Úloha: Scraper model v2 (kosik.sk)

> Návod pre AI coding agenta (Claude Code). Pracuj v repe `parky-scraper`.
> Najprv si prečítaj `AGENTS.md`, `README.md` a balík `scraper/`.
> Postupuj po krokoch nižšie, po každom kroku spusti `pytest` a zastav sa na review.

## Kontext

- Projekt AI PARKY: zber cien z kosik.sk → analýza → predikcia cien → odporúčanie cien.
- Momentálne iba scraper (Crawl4AI) + voliteľná klasifikácia cez Qwen/Ollama.
- Paralelne sa robí **crawler** (prejde ~16 podkategórií, ~1600 položiek, pošle zoznam URL scraperu v dávkach). Scrapuje sa piatok–nedeľa, cca 5 podkategórií denne.
- **DB schéma ešte neexistuje** – robí ju iný člen tímu. Tento model je podklad pre ňu, preto musí byť čistý a zdokumentovaný.
- Dáta zatiaľ ukladáme a spracúvame lokálne (súbory).

## Zistené chyby v súčasnom výstupe

1. **Zlá cena pri Multikupe.** `p7004-nord-svit-zlate-parky-93-maesa`: výstup má `price: 2.99`, správna regálová cena je **3.39** (JSON-LD `Offer.price`). 2.99 je cena „od 2 ks –11 %“. Extraktor (`_first_text` so vzorom `"price"`) chytí prvý prvok s „price“ v triede. Záznam je vnútorne nekonzistentný: `price_per_unit` 13.56 = 3.39 / 0.25 kg. Rovnako pravdepodobne `p6902-tauris-zipser-parky-71-maesa` (2.59 vs 3.19).
2. **Nepoužívame JSON-LD.** Každá stránka má `<script type="application/ld+json">` s `Product` (`sku`, `name`, `brand.name`, `description`, `image`), `Offer` (`price`, `priceCurrency`, `availability`) a `BreadcrumbList` (napr. `Údeniny a lahôdky > Párky, klobásy, špekáčiky > Párky` s URL `c3350-parky`).
3. **Kategória z LLM je zlá.** Pomaranče → `napoje` (kvôli „džúsové“). Košík má breadcrumb `Ovocie a zelenina > Ovocie > Citrusy > Pomaranče`. `subcategory` je vždy `null`, `confidence` je stále ~0.95.
4. **`availability: "Do košíka"`** je text tlačidla, nie stav skladu.
5. **Zahadzujeme dáta:** preškrtnutá cena a koniec akcie („1,75 –54 % do 20. 10.“), štítok „Dorovnaná cena“, Multikup úrovne, „Krajina pôvodu“, „Minimálna trvanlivosť: N dní“, varianty. EAN/GTIN na stránke nie je.

Vyrenderované stránky na testy: `scraper/output/rendered/*.html` (citróny, McCain, Metro Chef pomaranče, Nord Svit párky, Tauris párky, Fine Life slanina).

## Cieľový model

Rozdeliť na **produkt** (statické údaje) a **pozorovanie ceny** (časový rad, 1 záznam za scrape). Výstup scrapera je jeden riadok JSONL na produkt, ktorý obsahuje oboje, aby sa to dalo neskôr rozdeliť do tabuliek.

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
  "package": { "raw": "250 g", "amount": 250, "unit": "g", "base_quantity": 0.25, "base_unit": "kg" },
  "retailer_category_id": "c3350",
  "retailer_category_path": ["Údeniny a lahôdky", "Párky, klobásy, špekáčiky", "Párky"],
  "country_of_origin": "Slovensko",
  "min_shelf_life_days": 5,

  "currency": "EUR",
  "shelf_price": 3.39,
  "regular_price": null,
  "unit_price": { "value": 13.56, "per": "kg", "computed": 13.56 },
  "promotions": [
    { "type": "multibuy", "min_qty": 2, "promo_price": 2.99, "discount_pct": 11, "valid_until": null },
    { "type": "multibuy", "min_qty": 3, "promo_price": 2.69, "discount_pct": 20, "valid_until": null }
  ],
  "in_stock": true,

  "classification": null,
  "extraction": { "source": "json-ld+html", "scraper_version": "0.2.0", "warnings": [] }
}
```

### Pravidlá polí

- `retailer`: malými písmenami, enum (`"kosik"`).
- `retailer_product_id`: z JSON-LD `sku` (záloha: číslo z URL `p(\d+)-`).
- `shelf_price`: aktuálna cena za 1 ks bez podmienky (JSON-LD `Offer.price`). Pri klasickej zľave je to už zľavnená cena.
- `regular_price`: preškrtnutá pôvodná cena, iba ak existuje, inak `null`.
- `promotions[].type`: `discount` (preškrtnutá cena, má `valid_until`), `multibuy` (Multikup, má `min_qty`), `price_match` („Dorovnaná cena“). `valid_until` je ISO dátum; rok doplň podľa `scraped_at` (ak by bol dátum v minulosti, ďalší rok).
- `package`: parsuj `g, kg, ml, l, ks` aj tvary `4 x 100 g`, `1,5 l`. `base_unit` je `kg`, `l` alebo `ks`.
- `unit_price.value`: hodnota uvedená Košíkom; `unit_price.computed` = `shelf_price / base_quantity` (zaokrúhlené na 2 miesta).
- `in_stock`: z JSON-LD `availability` (`https://schema.org/InStock` → `true`).
- Ceny v Pythone ako `Decimal`, v JSON ako číslo s 2 desatinnými miestami.
- `classification` (voliteľné): `{ "category", "subcategory", "confidence", "model", "prompt_version", "classified_at" }`. LLM má mapovať **breadcrumb Košíka** na našu taxonómiu, nie hádať z názvu.
- `extraction.warnings`: zoznam reťazcov, napr. `unit_price_mismatch`, `missing_json_ld`, `price_fallback_html`, `unparsed_package`. `needs_review` = `len(warnings) > 0` (môže byť vypočítané property).

### Validácie (pridávajú warning, nepadajú)

- `shelf_price > 0`
- `|unit_price.value - unit_price.computed| / computed > 0.02` → `unit_price_mismatch`
- `regular_price` existuje a `regular_price <= shelf_price` → `regular_price_not_higher`
- JSON-LD cena ≠ cena z HTML → `price_source_conflict`

## Kroky

Po každom kroku: `pytest`, krátke zhrnutie zmien, počkať na schválenie.

1. **Regresné fixtures + testy.** Skopíruj vyrenderované HTML pre párky Nord Svit, Tauris párky, citróny a slaninu do `scraper/fixtures/` (zmysluplné názvy). Napíš testy, ktoré očakávajú správne hodnoty (Nord Svit `shelf_price == 3.39`, citróny `regular_price == 1.75` a `promotions[0].type == "discount"`, slanina má `price_match`). Testy majú teraz zlyhať.
2. **JSON-LD extrakcia.** V `extraction.py` pridaj parser JSON-LD (`@graph` → `Product`, `Offer`, `BreadcrumbList`). Primárny zdroj pre `sku`, `name`, `brand`, `price`, `currency`, `availability`, kategóriu. HTML len ako záloha (+ warning).
3. **Akcie a doplnkové údaje.** Z HTML vytiahni Multikup úrovne, preškrtnutú cenu + `do DD. MM.`, „Dorovnaná cena“, krajinu pôvodu, minimálnu trvanlivosť.
4. **Nový model.** Prerob `scraper/models.py` podľa cieľového modelu (Pydantic v2, `extra="forbid"`, vnorené modely `Package`, `UnitPrice`, `Promotion`, `Extraction`, `Classification`). Pridaj normalizáciu balenia a validácie. Uprav `pipeline.py` a klasifikáciu tak, aby plnila objekt `classification` a posielala LLM aj breadcrumb.
5. **Výstup JSONL.** CLI zapisuje do `output/kosik/<YYYY-MM-DD>/observations.jsonl` (append, 1 riadok = 1 produkt), `run_id` sa generuje na začiatku behu. Zachovaj možnosť `--output` pre vlastnú cestu. Rozhranie `scrape_many(urls)` nechaj tak, aby ho mohol volať crawler v dávkach.
6. **Dokumentácia.** Aktualizuj `README.md` a `AGENTS.md` (nový formát výstupu, popis polí). Pridaj `docs/output-format.md` s popisom každého poľa – podklad pre autora DB schémy.

## Obmedzenia

- Nečítaj, nevypisuj ani necommituj `.env` (obsahuje `OLLAMA_API_KEY`).
- Testy musia bežať offline (fixtures, mockovaný HTTP), žiadny live scraping v testoch.
- Nemeň crawler logiku zoznamu URL – to robí iný člen tímu.
- Neimplementuj DB – iba súborový výstup.
- Commituj po logických častiach na vetve `feature/scraper-model-v2`.

## Hotovo, keď

- Všetky testy prechádzajú, vrátane nových regresných.
- Na 6 vyrenderovaných stránkach nie je žiadny `unit_price_mismatch`.
- Nord Svit párky: `shelf_price` 3.39 a 2 multibuy akcie (2.99 / 2 ks, 2.69 / 3 ks).
- `docs/output-format.md` existuje a popisuje všetky polia.
