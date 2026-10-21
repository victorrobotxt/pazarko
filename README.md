---
title: Pazarko
emoji: 🛒
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.0.0
app_file: app.py
pinned: false
---
# пазар. — Bulgarian grocery price comparison

Compares prices across 74 Bulgarian retail chains and ~1,900 shops, using the KZP "Колко струва" daily open data plus public retailer catalogues (eBag, Lidl, Kaufland, Avanti, BulMag, Metro, dm, T Market, Billa's text brochure) and the Glovo catalogues of supermarkets in Sofia, Plovdiv, Varna, Burgas, Ruse and Stara Zagora.

Python 3.10+ standard library only. No dependencies and no build step.

## Run

```bash
./refresh.sh                 # ingest all sources + rebuild derived tables. Sources run in parallel (each on its own
                             # host and delay), so a run takes as long as the slowest: T Market's crawl delay and the
                             # 16 Glovo stores, ~45 min. -j 1 runs them one after another; --glovo-stores picks some
python3 server.py            # http://127.0.0.1:8080
```

To refresh only some sources, pass their names: `./refresh.sh kzp lidl kaufland`.

## Pieces

| File | Role |
|---|---|
| `ingest.py` | Fetches the sources into `prices.db`, keeping the raw source IDs (see `DATA_PIPELINE_SPEC.md`) |
| `audit.py` | Data-quality report: suspicious group/family spreads, multipacks, leva prices, fake discounts, shrinkflation |
| `schema.sql` | Normalized tables: `stores`, `outlets`, `products`, `prices`, `promotions`, `ean_mappings`, `ingest_runs`, `product_name_history` (earlier names, kept by a trigger) |
| `derive.py` | Rebuilds the read model in one transaction: `product_current` (current price/promo per product, with the 30-day Omnibus check), `product_groups` + `group_members` (the same product across chains), `product_families` (flavours/variants of one product line), `shrinkflation`, location tables (`areas`, `store_info`, `store_area`, `product_area`, `outlet_area`), `products_fts` (search) |
| `overrides.json` | Optional: pinned matching decisions (`force_merge`, `force_split`, `family_split`) |
| `taxonomy.py` | Product type + department classifier, brand finder, Latin↔Cyrillic search keys |
| `ekatte.csv` | NSI settlement register (EKATTE → municipality, province). Maps KZP outlet codes to places |
| `server.py` | JSON API + static files |
| `web/` | Frontend: search with department chips and barcode scan, location picker, "Моите карти" (loyalty cards), лв. toggle, family cards with per-chain prices and €/кг, variants × chains sheet, product sheet, multi-store basket with trip planning, smart shopping list |

## API

Every listing takes the location scope `area=<municipality code>` (e.g. `SOF46`) and `online=0|1` (include delivery-only chains; default 1), and `cards=lidl,kaufland` (or `cards=*`): the shopper's loyalty cards, whose card prices then count as the price (`effective`, `unit_price`; `with_card=1` marks them).

| Endpoint | Notes |
|---|---|
| `GET /api/stats`, `GET /api/stores` | Counts, last update, per-source run status; stores carry `channel` (online/physical) and footprint |
| `GET /api/areas` | Municipalities with outlets (for the location picker) and the online-only chains |
| `GET /api/search?q=&store=&dept=&discounts=1&card=1&min_stores=2&sort=relevance\|price\|unit\|discount\|drop&collapse=family\|group\|none&page=&per_page=` | Real pagination. `collapse=family` (default) returns one card per family with `family.stores` (cheapest per chain); `group` one per same-product group; `none` every product. Returns `facets` (departments) and `intent`; items outside the intent have `off=1` and sort last |
| `GET /api/search?q=<barcode>` | An EAN-8/12/13 or GTIN-14 query returns the products carrying it and their cross-chain group (`barcode` in the response) |
| `GET /api/deals?honest=1&expiring=1`, `GET /api/drops` | Biggest current discounts / shelf-price drops vs. about a week ago (same source both days; items on promo are deals, not drops), rolled up per family. Items carry `prior_price` (lowest price in the 30 days before the promo), `real_discount_pct` and `fake_promo`; `honest=1` drops fake promos, `expiring=1` keeps promos ending within 2 days |
| `GET /api/upcoming?store=&limit=` | Promotions that start later (next week's Lidl / Kaufland leaflets, Billa's "Предстояща брошура"), soonest first |
| `GET /api/shrinkflation?store=&limit=` | Smaller packs whose price per kg/l did not fall, with old/new size and unit price |
| `GET /api/product/{id}` | Product, active promotions, price history, `availability` (online / municipalities with prices / chain footprint), outlets (in the chosen area), cross-chain comparison |
| `GET /api/family/{id}` | Variants × chains matrix: one row per flavour, cheapest offer per chain, availability in the chosen area. Cells carry `unit_price` (€/kg·l) or `piece_price` (€/бр.); `best_unit` marks the lowest per row and `family.best_unit_price` the lowest overall, since pack sizes vary within a family (80 vs 100 g). A chain column's `min_unit` is the unit price of its cheapest offer (`min`), not of another pack; search cards' `stores[].unit_min` likewise |
| `POST /api/basket` `{"items":[{"product_id":1,"qty":2},{"family_id":7},{"product_id":3,"allow_family_substitute":1}],"area":"SOF46","online":1,"max_stores":2,"min_savings_per_store":2.5,"cards":["lidl"]}` | Among what is sold in the area: `single_store` (chains with every line), `split` (cheapest offer per line, any number of chains) and `plan`, the recommended trip of at most `max_stores` chains (default 2) where each extra chain must save at least `min_savings_per_store` (default 2.50 €), more lines covered always winning; `plans` lists the best plan per number of chains. A line is a `product_id` (its cross-chain group), a `group_id` or a `family_id` (any variant); `allow_family_substitute` lets a chain without the exact product offer a sibling (same flavour in another pack first), marked `substitute`. Multibuy promos only apply when `qty` reaches them. Unknown lines are listed in `unavailable`; split lines keep the requested `product_id` and name the offer in `offer_product_id` |

## Cross-chain matching

`derive.py` groups "the same product" in two steps:
1. **GTIN links**, from KZP codes and Kaufland image file names.
2. **Name matching:** IDF-weighted token overlap after normalising POS-style names (`КИС.МЛЯКО`, `КМ`, `K.M.` →
   `КИСЕЛО МЛЯКО`, `КР-Н` → `КРОАСАН`, KZP's `3 6%` → 3.6 %, `#K#`/`/12` noise removed). A name without its pack size
   (`ВЕРЕЯ КИСЕЛО МЛЯКО 3.6%`) takes its group's, so it gets a price per kg. A volume beats the grams Kaufland appends
   to drinks (`0,5 л кен 500g` is 500 ml).

Name matching has hard vetoes on:
- pack size (±2%), fat/alcohol %, and stray numbers (class 1 vs 2, model numbers)
- packs: piece counts (`10 бр.`), multipacks (`3+1`, `6 бр x 1,5 л`, `20гр Х30`, `1КГ*10`) vs single pieces, and
  loose goods priced per kg (`Картофи кг`, Metro `~1,9КГ`) vs bags (`2,5КГ`)
- age (`12YO`, `Сливова РЕЗ. 25г.` is 25 years, not 25 g)
- brand: two names with different brands (`Fairy` / `Exo`), or a branded name and one that does not name that brand.
  A brand counts as named when another spelling of it appears in the other name: `POMORIE` / `Поморийска`, by
  vowel-blind consonants (a brand of fewer than 3 consonants must be spelled out, so `KARO` is not `Крео`)
- flavour (`taxonomy.FLAVOURS`, one concept per word in either script: `ягода` = `ягодов` = `strawberry`):
  - two names that each have a flavour the other lacks (`Мерло` / `Мавруд`)
  - a plain name vs a flavoured one (`Absolut` / `Absolut Грейпфрут`; for chocolate `бял`/`черен` count too)
  - a strict variety on one side only: Zero, decaf, lactose-free, aged, alcohol-free, and for drinks `без захар`.
    `Zero` and `без захар` are the same thing.
- price: a group's regular prices may not spread more than 3× (a per-kg deli price is not the 120 g pack)
- KZP category
- two products from the same chain

A group holds at most one product per chain, and all its members must agree on size and %. This stops size-less names from bridging 90 g and 100 g variants. Flavours are checked member by member, so `Бочко банан/ягода` cannot bridge the banana and strawberry pastes.

Before scoring, words are reduced to one key each: the flavour concept, else a phonetic skeleton (so `Dalmore` = `Далмор`), else a Latin transliteration. English generic words are mapped to Bulgarian (`WHISKY` → `УИСКИ`). Phrase abbreviations are expanded (`П.З.` → паста за зъби, `Ш-Н` → шампоан). Avanti's bilingual names (`РАКИЯ ... / RAKIA ...`) are compared one language at a time. When both names carry words the other lacks, those words cost extra (two different extras usually mean two products). Metro's case packs (`24 бр 500 мл`) are cases, and their unit text is not counted twice.

`python3 audit.py [db]` section 9 checks matching against catalogue barcodes (Metro, dm, image file names): name links between different barcodes, barcodes split across groups, and groups mixing conflicting flavours.

On 2026-10-13 data, 7,660 groups span 2+ chains. For example, Верея кисело мляко 2.9% 400 g is matched across 21 chains.

## Families (variant roll-up)

The same product across chains is a *group*. A *family* rolls up the flavours of one product line: same brand, same product type, similar pack size.
- **Type and department** come from `taxonomy.py`. Rules run over the name (the earliest and then longest phrase wins, so `Шоколад с мляко` is chocolate). POS abbreviations (`Ш-Д`, `ЧЗ`, `Ен.напитка`) are expanded first. Next come the retailer category path (leaf first) and the BulMag `productTypeSlug`, then the KZP basket category. The retailer category decides the department, so a "Monster" dog toy is a pet product.
- **Brand** comes from the eBag/Lidl/Metro/dm brand fields and is found in other chains' names by literal or transliterated tokens. Distinctive brands also match by phonetic key, so `MONSTER` = `МОНСТЪР` and `ROSHEN` = `РОШЕН`. Words that name a product type (`Елена`) and generic words are not treated as brands.
  - Two words may spell a one-word brand (`Fit Spo` = `FitSpo`, `7 Days` = `7Days`), and numbers may be written out
    (`Севън Дейс`, `7ДЕЙС`: `taxonomy.BRAND_SPELLINGS`).
  - A three-letter brand counts only in its own department: `Fit` is a detergent, so `Neo Fit протеинов бар` is not Fit.
  - eBag's Cyrillic brand fields merge with the Latin brand their names carry, when the consonants agree
    (`Дав` → `Dove`, `Сейфгард` → `Safeguard`; `BrandIndex.merge_spellings`).
  - A product line filed as a brand (`7 DAYS MAX`, `Верея Чудно`) is its brand's, and the line word stays in the
    variant label.
- **Sub-types** split broad types: coffee into beans / ground / instant / capsules / pods, shaving into razors /
  disposables / blades / foam / depilation (`taxonomy.SUBKINDS`). A 1 kg bag of beans and an instant sachet are
  different products.
- **Sizes** within 12% of a neighbour chain together, up to a 1.3× span (`80–100 g` chocolate bars). Only sizes
  that 2+ chains stock chain clusters together: one shop's 85 g croissant joins the nearest cluster but cannot bridge
  the 80 g and 92 g lines. Drinks cluster within 3%, so a 473 ml US can, the 500 ml can and a 553 ml one are three
  families, and bags of minis (`Mini`, `Мини`) are their own families. Groups without a size cluster by piece count
  (`10 бр.` capsules). Groups with neither join the cluster whose
  median price they are within 2× of, else stay apart; a group priced over 3× off its cluster's median is split off.
- **No roll-up** applies to types whose same-brand items are different products, not flavours (wine, spirits, supplements, kitchenware, toys…).
- **Variant label** is the name minus brand, type phrases (`Кисело мляко`, `Протеинов бар`), size, POS noise (`БДС`,
  `ЗНП`, `Каси`, protein claims) and words shared by ≥80% of the variants (`Енергийна Напитка Monster Mango Loco` →
  `Mango Loco`). A fat or alcohol % joins the label only for dairy and drinks.
- **Variant rows:** labels saying the same thing share a row in the family sheet. Words compare by flavour in either
  script (`Ананас` = `Pineapple`), sub-line synonym (`Мах` = `Max`, `Double` = `двоен` = `ДУО`) or phonetic key, in any
  order; `краве` and `крем` do not count, and a short POS word stands for the one family word it starts (`ABS` →
  `Absolutely`). A label that adds only sub-line words to another's joins it (`Golden Pineapple` → `Ананас`); one that
  adds a flavour is another variant (`Max какао` ≠ `Max лешник какао`). Rows with the same meaning merge even when a
  chain lists the product twice; the cell keeps its cheapest offer.

On 2026-10-13 data, 4,069 families roll up 22,305 variants. For example, `monster` gives one card (24 variants, eBag 0.99 / Lidl 1.09 / Avanti 1.15 / BulMag 1.45 €) instead of 37.

## Search relevance

- **Cross-script matching:** FTS has an `alt` column with normalised Latin spellings and phonetic keys, plus every
  retailer spelling of the product's brand. So `roshen` finds `РОШЕН`, `лакми` finds `Lacmi`, `монстър` finds
  `Monster` and `дав` finds Dove at every chain. Two query words also match as one (`fit spo` finds `FitSpo`).
- **Phonetic hits are scoped:** a phonetic key drops the vowels, so `dallmayr` and `ДАЛМОР` share one. A product
  found *only* by its phonetic key is kept when it is in a department holding a real share (≥ 25% of the largest) of
  the spelled-out hits and not another brand (no Dalmore whisky for `dallmayr`). The same goes for a hit found only
  by a prefix of its other-script spelling: `monster*` also starts `МОНСТЕРА` (a houseplant) and `fit*` starts
  `ФИТНЕС`. Brand keys merge spellings phonetically only within one department.
- **Latin-typed Bulgarian:** `q`=я, `w`=в, `x`=х, `4`=ч are tried next to the plain transliteration, so `mlqko` finds
  `мляко` and `aqua` still finds `Aquafresh`. A bare number matches whole words only (`pampers 4` is not `48 бр.`).
- **Typos:** when nothing matches, a vowel-less key (5+ consonants) is tried, so `кашкавл` finds `кашкавал`.
- **Intent:** the departments that hold most of the matches are the query's intent (`monster` → drinks). Other matches (toys, cloths, toothbrushes) are kept but ranked below a "Други резултати" divider, and the department chips filter to one department.

## Promo honesty, shrinkflation, overrides

- **Fake discounts (EU Omnibus).** Directive 98/6/EC art. 6a measures a price reduction against the lowest price
  applied in the 30 days before it. For every product on promo, `derive.py` takes the source with the longest
  history, finds when the promo began (`valid_from`, or the first day of the current run of promo prices) and
  stores `prior_price` (30-day low), `prior_median` and `real_discount_pct`. `fake_promo=1` when the claimed regular
  price is more than 5% (and 0.05 €) above the 30-day median shelf price. Needs history: daily runs plus
  `ingest.py kzp --kzp-backfill N`. Cards show "⚠ реално -X%"; the deals feed has a "само честни" filter.
- **Shrinkflation.** A product renamed to a smaller pack (`400 г` → `370 г`, recorded in `product_name_history` by a
  trigger on `products`), or a smaller pack of the same family and chain that replaced a discontinued one within 3
  weeks, 1.5–25% smaller, whose price per kg/l did not fall.
- **`overrides.json`.** Pins matches the heuristics get wrong, without loosening the global rules in `taxonomy.py`:
  `{"force_merge": [["lidl:0080123", "kaufland:00412345"]], "force_split": [["ebag:143410", "bulmag:7789"]],
  "family_split": [["ebag:1", "ebag:2"]]}`. Products are `<store slug>:<external id>` (stable across rebuilds) or
  ids. A forced merge still keeps one product per chain; `--overrides PATH` picks another file.
- **Atomic rebuild.** `derive.py` rebuilds every derived table inside one transaction. In WAL mode `server.py`
  keeps reading the previous tables until the commit, and an interrupted run (SIGTERM during `refresh.sh`, an error)
  rolls back instead of leaving empty tables.

## Location

- KZP outlet `ekatte` codes map to municipalities via `ekatte.csv`, so "София" means Столична община, including Банкя, Лозен, Кокаляне…
- A chain whose every outlet is a website (eBag) is `online`. It shows as "🚚 Онлайн доставка" and is included in any area unless `online=0`. Its delivery zones are not in the data.
- Glovo catalogues are recorded at a `Glovo доставка (<city>)` outlet with that city's EKATTE, so a Glovo-only product
  is offered in its city's municipality only (Пловдив `PDV22`, Варна `VAR06`, Бургас `BGS04`, Русе `RSE27`,
  Стара Загора `SZR31`, София `SOF46`).
- With an area chosen, a product is shown when:
  - it has a KZP price at an outlet there (and that local price is used), or
  - it is a chain-wide catalogue price (BulMag, Lidl and Kaufland feeds) from a chain with a shop there, or
  - its chain is online.
- Without an area, cards from small regional chains say where they are ("📍 само в Шумен, Варна, Търговище, Бургас").

## Catalogues vs. the KZP basket

KZP covers a regulated basket of essential goods (about 700–2,500 SKUs per chain), not full assortments: Metro files
~1,900 SKUs, so champagne, spirits and most non-food never appear there. Retailer catalogues add the rest:

- A catalogue row and a KZP row of the same chain share one `products` row when the chain files its own article
  code with KZP (Metro `displayId` such as `61818001001`, BulMag `number`). KZP then supplies per-outlet local
  prices; the catalogue supplies the name, brand, category, image, GTINs and promo dates.
- Catalogue-only products have a chain-wide price (no outlet) and are shown wherever the chain has a shop.
- Franchisees that file a chain's shops with KZP under its article codes are that chain (`ingest.EIK_ALIASES`: ДАР
  Г.Н.'s Fantastico shops are Фантастико). `ingest.py` folds a store created before its EIK was listed into the chain
  the next time it opens the database.
- `metro` reads shop.metro.bg's search and article APIs for store 00010 (София, Цариградско шосе; ~10,500 items).
  It stores the VAT-inclusive price (the API leads with net prices for business customers) and the sales unit:
  many items are sold by the case (`12 бр x 1000 мл`).
- `dm` reads dm-drogeriemarkt.bg's product sitemap (~9,900 products) and the tile API its pages call
  (`products.dm.de/product/products/tiles/BG/dans/{up to 200 DANs}`): GTIN, brand, title, EUR price, strike price,
  base-price text and category. dm's product-search API is not used (its robots.txt disallows everything). dm files
  the same DANs with KZP, so catalogue and KZP rows merge, and its GTINs bridge Pampers, Nivea, Ariel… to every
  chain selling them.
- `tmarket` reads tmarketonline.bg's category pages (CloudCart, `Crawl-Delay: 3`): prices and promos; GTINs come from
  up to `--tmarket-details N` product pages per run (default 200), so they accumulate over a few days.
- `billa_accessible` parses Billa's text brochures: this week and next ("Предстояща брошура"), with validity windows,
  multibuys (`multibuy_qty`/`multibuy_price`), Billa Card/App prices, cashback, origin and pack size. ssbbilla.site's
  robots.txt disallows crawling, so the live fetch is skipped; `--billa-html FILE` (repeatable) parses saved pages.
  Upcoming promotions are stored with their dates and change no current price (the same holds for Lidl's and
  Kaufland's next-week offers).
- `glovo` reads the Glovo catalogues of chains without a web shop (`GLOVO_STORES` in `ingest.py`): Магазини ДАР,
  Фантастико, Billa, Kaufland and CBA in Sofia; Billa and Kaufland in Plovdiv, Varna, Burgas, Ruse and Stara Zagora;
  Fantastico in Plovdiv (T Market and CBA are not on Glovo outside Sofia). The store page embeds the menu tree; each
  menu section is one call to
  `api.glovoapp.com/v4/stores/{store}/addresses/{address}/content/partial?component=section&id=…` with the
  header `glovo-location-city-code: SOF|PDV|VAR|BOJ|RDU|SZR`. Glovo's `externalId` is the chain's own code, so items the chain also
  files with KZP share its `products` row (about 40–55% of Dar, Billa and Kaufland items); the POS code Glovo
  appends to names (`(010623)`, `Dx-009823`, `/ 38107134`) is removed. Weighed produce that Glovo sells in 100 g
  steps (`Лимони 100 г` at 0.199 €) is stored per kg (`Лимони`, 1.99 €, unit `кг`). Item prices equal the shelf price (delivery
  is a fee), and are recorded as source `glovo_delivery` at a `Glovo доставка (<city>)` outlet, so Glovo-only
  products are offered in that city only. `derive.py` ignores Glovo prices and promos for any product another source
  prices. Sections done today are recorded in `crawl_progress`, so an interrupted run resumes;
  `--glovo-stores` picks stores.

## Currency

All prices are euro (Bulgaria adopted it on 2026-01-01 at 1.95583 BGN/EUR).
- `ingest.py` checks the KZP header by column name and refuses a file whose header names leva or whose columns
  are reordered (recorded in `ingest_runs.note`). Feeds with a currency field (Avanti, Metro) must say EUR.
- `derive.py` rescales an outlet whose prices sit at ~1.956× its chain's other outlets, or a chain (outlets or
  catalogue) at ~1.956× the other chains, for at least 30% of 30+ products, and records it in `quality_flags`.

## Caveats

- Retailer endpoints are undocumented and can change.
- Glovo item prices match the shelf price (delivery is a separate fee), but they are the app's prices: `derive.py`
  uses them only for products no shelf source (KZP, a chain's own catalogue) prices, and ignores Glovo-only promos
  (Glovo Prime prices are never stored).
- Kolichka.bg closed on 2025-07-23 and KAM Market publishes image-only PDF leaflets, so neither is ingested (see
  `DATA_PIPELINE_SPEC.md` §8).
- `ssbbilla.site` (Billa's accessible brochure) disallows crawling in robots.txt. The `billa_accessible` source skips it unless robots allows; `--billa-html FILE` parses a manually saved page.
- Matching is heuristic. The UI shows how each match was made (barcode or % name score). Families and departments are rule-based too; extend `taxonomy.KINDS` when a product type is misclassified.
- `ekatte.csv` comes from the NSI register (2018 snapshot), so settlements created later would be missing. Unknown codes are skipped.
