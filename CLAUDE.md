# Project: ScanSafe — food safety RAG (Israel)

## Goal
An app that analyzes an Israeli supermarket product and generates a report
on its composition, flagging potentially harmful ingredients/additives
(controversial, possibly carcinogenic, ultra-processing). Built on a RAG
system (two corpora: product sheets + additive knowledge base) rather than
the LLM's raw memory, so every claim can cite a verifiable source.
Future feature: suggesting healthier alternative products. Future feature
(v2): photo/OCR label scanning (V1 starts with text input: product name or
barcode).

## Stack
- Language: Python
- Vector DB: Chroma (default choice to get started, local, simple)
- LLM: Claude via the Anthropic API
- Product data: local JSON, scraped manually/via script directly from brand
  websites (Tnuva, Strauss/Danone, Rami Levy, Yehiam, Tivall) — not Open
  Food Facts (insufficient coverage of Israeli products, tried and dropped)

## Project structure
```
scansafe/
├── CLAUDE.md
├── data/
│   └── scansafe_combined_dataset.json   # 460 products (schema below)
├── knowledge_base/
│   └── additives/                        # additive sheets (RAG corpus #2)
├── src/
│   ├── ingestion/                        # retrieval/cleanup scripts
│   ├── indexing/                         # embeddings + vector store
│   ├── retrieval/                        # search across both corpora
│   ├── evaluation/                       # OK / controversial / avoid ranking
│   └── report/                           # final report generation
└── tests/
```
(to be adjusted as we go — don't create all these folders at once, only
when actually needed)

## Product data schema (current dataset)
Main fields available per product (JSON):
`product_id, product_name, product_name_he, brand, categories,
ingredients_text_he, ingredients_text_en, allergens, additives (list of
E-codes or names), nutrition_per_100g, kosher, country_of_origin`.
417/460 products have a usable ingredient list. 254/460 have additives
listed explicitly (no text parsing needed for those).
Known bias: 74% of products come from Tnuva (mostly dairy).

## Additive knowledge base (RAG corpus #2)

**Decision (revised)**: we do NOT write sheets by hand. The RAG itself must
query the official source documents directly — hand-writing sheets would
short-circuit the whole point of retrieval. Instead, we **ingest the raw
source documents** into the vector store:
- EFSA re-evaluation opinions (PDF, one per additive or additive group)
- IARC classification list (carcinogens, full table)
- Open Food Facts additive taxonomy (broad, structured coverage)
- JECFA / ANSES as a supplement when a controversial additive warrants it

These documents are chunked (split into passages) and indexed as-is. The
Matching agent retrieves the right passage at query time; it's the Report
agent that rephrases for the end user — simplification happens via the
generation prompt, not as a manual rewrite upstream.

The two hand-written sheets (E202, aspartame) served as a prototype to
validate what *type of information* to cover (ADI, effects of excessive
consumption, carcinogenic status, sources) — useful as a reference for what
the Report agent's prompt should surface, but won't be used as-is as the
final corpus.

Priority additives for the first ingestion pass (by frequency in the
dataset): E1442, E202, acesulfame_k, E1422, sucralose, aspartame, E450iii,
E471, potassium_sorbate, guar_gum, methyl_cellulose, E407, E412,
xanthan_gum, E306.

### ⚠️ Known limitation: source freshness not guaranteed
The `efsa_sources.json` file was filled in via additive-by-additive
research, without systematically checking for a possibly more recent EFSA
opinion for each of the 71 additives covered. For some (aspartame,
sucralose, acesulfame K, xanthan gum...) the most recent follow-up found
was indeed included. For others (caramel colors, curcumin, benzoic acid...),
only the first relevant opinion found was kept — a more recent follow-up
opinion could exist without having been caught. The documents used are real
and were authoritative at the time of publication, but aren't guaranteed to
be the most up-to-date version.
Decision: move forward with this base as-is, and fix things case by case if
doubt arises on a specific additive (e.g. recent media controversy, a value
that looks inconsistent).

### EFSA opinion processing (PDF) — DONE
Decision: do NOT index the whole PDF (too long, too much
methodological/bibliographic noise). Extract 4 sections via a keyword
heuristic (`src/ingestion/extract_efsa_sections.py`, uses `pdfplumber`):
Abstract/Summary, Toxicology, ADI, Conclusions. Output as JSON per document
in `knowledge_base/additives/efsa_extracted/`, with the source URL/DOI and
sha256 kept as metadata for citation.

**Actual status after several rounds of fixes** (false positives on the
Wiley watermark, mis-detected section numbering, etc.):
- Abstract and Toxicology: reliable on nearly all 63 documents
- ADI and Conclusions: work but sometimes latch onto an isolated mention or
  a themed sub-conclusion instead of the actual general section (e.g. "
  Conclusion on genotoxicity" instead of the panel's final conclusion).
  Structural limitation of the keyword-based approach (no access to the
  PDF's actual layout/font size to tell a real heading from a mention in
  running text).
- **Decision**: don't polish this further for now — vector retrieval works
  by semantic similarity, not exact document structure, so a nearby
  relevant passage still stays useful. Revisit with real PDF layout
  analysis only if actual use (generated reports) shows poorly relevant
  citations.

Tool: `pdfplumber` for PDF text extraction (not BeautifulSoup, which is for
HTML, not PDF).

## Target pipeline (agents)
```
[Product name / barcode]
        │
        ▼
Retrieval agent       → fetches the product sheet (semantic search)
        │
        ▼
Parsing agent          → (if additives aren't structured) spots additives
                          in the ingredient text
        │
        ▼
Matching agent (RAG)   → for each additive, exact search in the indexed
                          EFSA knowledge base
        │
        ▼
Evaluation agent       → classifies each additive: OK / controversial /
                          avoid / insufficient data (LLM + structured schema)
        │
        ▼
Report agent           → generates the final natural-language report, sourced
```
V2 (later): add an OCR agent upstream to start from an actual label photo
instead of a product name.

## Working conventions
- We move step by step: one feature = one session, validated before moving
  to the next
- No file generated in one shot over 150 lines
- Always explain what a block of code does before moving on
- One Git commit per working step
- Every health claim must be sourced (EFSA extracts retrieved by the RAG)
  — never an invented claim or the LLM's raw memory

## Vector indexing — DONE
Two separate Chroma collections, same multilingual embedding model
(`paraphrase-multilingual-MiniLM-L12-v2`, sentence-transformers, local and
free) — chosen to natively handle the dataset's Hebrew and English:
- `additives`: 339 passages (87 EFSA documents × extracted sections)
- `products`: 460 products (EN+HE name, brand, categories, ingredients)
Tested: cross-language queries work (searching in Hebrew retrieves the
right products), a semantic query for aspartame/cancer retrieves the right
passages.

## EFSA collection — COMPLETE (87/87)
Two bugs found and fixed along the way:
1. The manifest was indexed by URL alone → an additive sharing a URL with
   another one wrongly "inherited" the ok status even with an empty folder.
   Fixed: key = (additive, URL).
2. The filter excluding "already claimed" files blocked recognition of a
   file re-dropped at the same path as an old invalid attempt. Fixed: only
   consider files already marked `ok`.
Feature added: automatic propagation — a PDF validated for one additive is
copied into the folders of other additives sharing the same source URL
(e.g. a single drop is enough for E1442/E1422/E1420/E1414/E1404, which
share the same opinion on modified starches).
Final result: 87/87 additive/URL pairs collected, 0 left in
`manual_required`.

## Parsing agent — DONE (`src/parsing/extract_additives_from_text.py`)
For the 206 products without explicitly listed additives (186 with usable
ingredient text): spots E-codes (regex) and known additive names (alias
dictionary, e.g. "soy lecithin" → `soy_lecithin`) in `ingredients_text_en`,
limited to the 81 additives already covered by the EFSA knowledge base (no
point tagging an additive with no data to cite for it).
Result: 19/186 detections, all manually verified as correct (e.g.
"tricalcium phosphate" → phosphates, "rapeseed lecithin" → lecithin).
Written to `data/parsed_additives.json`, kept separate from the original
`additives` field (declared vs. inferred distinction preserved). **Not yet
wired into the Matching agent** — decision to be made later.

## Matching agent — DONE (`src/retrieval/match_additives.py`)
Semantic product search (embeddings, tolerates an approximate name/other
language) → for each of the product's additives (`additives` field, known
codes so no need to approximate), exact filter on `additive_id` in the
`additives` collection. Returns all associated passages + an explicit
`found=False` if no data (never invented).

## Evaluation agent — DONE (`src/evaluation/evaluate_additive.py`)
Calls the Anthropic API (`client.messages.parse`, `claude-opus-5` model,
structured output via a Pydantic schema) to classify an additive as
OK / controversial / avoid / insufficient data, **using only the EFSA
passages provided by the Matching agent** (never the LLM's raw memory).
Justification + textually cited evidence required in the prompt.
Tested on "Yoplait Diet with Citrus Fruits" (3 additives): nuanced,
well-sourced results (e.g. aspartame classified "controversial" despite a
fairly reassuring EFSA conclusion, because of the PKU restriction and an
equivocal genotoxicity result flagged in the text).

## Report agent — DONE (`src/report/generate_report.py`)
Takes the evaluations + evidence + sources, generates a final report in
plain, accessible language, structured (overall verdict then per-additive
detail with cited sources). Strict rule: simplify without adding any
information not present in the provided evaluations. Output written to
`reports/<product_id>.md` (not just printed to the terminal, to avoid
truncation and encoding issues).

## Full pipeline — WORKING END TO END
```
python -m src.report.generate_report "product name"
```
chains semantic Retrieval → Parsing (if needed) → Matching → Evaluation →
Report, tested successfully.

## API authentication — API key required (NOT the Pro subscription)
Point clarified after verification: the **Claude Pro** subscription covers
claude.ai and **Claude Code** (the tool used to build this together), but
**not** the Anthropic API (`console.anthropic.com`), which our scripts
(`evaluate_additive.py`, `generate_report.py`) call directly via the Python
SDK — these are two separate Anthropic products, billed separately.
Solution in place: an API key created on console.anthropic.com, stored in a
`.env` file at the project root (never committed, added to `.gitignore`
along with `__pycache__/`, `*.pyc`, `vector_store/`), loaded automatically
via `python-dotenv`.

## Phase 2 — Towards a real-world app (decided, not started yet)

**Context for the decision**: the MVP (pipeline + CLI) works, but the
intended real-world use is "at the supermarket, scan and decide fast" — not
a command-line search. Two new features requested: barcode scanning,
healthier-alternative suggestions. Important architectural decision tied to
the API costs observed in real use (see below).

**Non-negotiable principle: nothing existing gets removed.** The 5-agent
pipeline (Retrieval/Parsing/Matching/Evaluation/Report) and the CLI stay
fully functional as-is — useful in particular for a product absent from the
dataset. Everything below is added as a layer on top.

### New concept: processing level ≠ risky additives
The current pipeline evaluates additives, not a product's overall
processing level (NOVA-style: unprocessed / minimally processed /
processed / ultra-processed). A product can be heavily processed without
having any additive classified "avoid". Decision: add a processing-score
heuristic (based on the type/number of ingredients), combined with the
already-evaluated additive severity, into an overall verdict.

### Architectural decision: pre-computation rather than on-demand
Since barcode scanning + alternative comparison would mean a lot of
repeated API calls for "at the supermarket" use (slow, costly, depends on
internet), decision: **pre-compute the score and report for every product
in the dataset once**, store the result, and only make a live API call for
a product absent from the dataset (the exception, not the rule).

### 4-step plan
1. **Scoring engine**: processing score + additive severity → combined
   verdict (e.g. traffic light) + short explanation
2. **Mass computation**: a script that runs once over the whole dataset,
   stores score/verdict/report per product (local file, no recomputation
   on every use)
3. **Alternatives**: for a given product, compare against other already-
   scored products in the same category/brand, suggest the best-rated one
   (free and instant, everything is already computed in step 2)
4. **Mobile interface**: a web page usable from a phone browser, barcode
   scanning (the dataset's `product_id`s ARE already barcodes), instant
   lookup in the pre-computed results, verdict + suggested alternative
   display

### Dataset expansion — DONE (460 → 1999 products)
Scraped shufersal.co.il (Playwright — the site blocks `requests`/an
anti-bot WAF but responds to a real browser):
- `src/ingestion/scrape_shufersal.py`: searches by Hebrew term (34 terms
  covering dairy/snacks/drinks/grocery/canned goods/cereals/sauces/frozen/
  bakery/produce/meat-fish/spices/coffee-tea/sweets), opens the product
  sheet, extracts name/brand/categories from the modal's `data-gtm` JSON
  (more reliable than the displayed text), the 13-digit barcode from the
  `title` attribute of the מק"ט (filled in asynchronously by the site's JS
  — targeted wait on the regex pattern, not just attribute presence),
  ingredients (`.componentsText`), nutrition, kosher status. E-codes
  already detected on the fly from the Hebrew text (language-agnostic) via
  `find_e_codes` from `extract_additives_from_text.py`.
  Pagination via **infinite scroll** (the "טען עוד" button exists in the
  DOM but stays hidden via CSS — `window.miglog.loadMoreProductsButton =
  false` on the site's side, it's the scroll that triggers the AJAX load,
  verified manually).
  Two bugs found and fixed: (1) the modal-close click sitting in an
  unprotected `finally` block could wipe out ALL results already
  accumulated for a term (an exception in `finally` overrides and
  propagates past the exception already handled by `except`) — 363
  successful extractions lost, leaving only 40 products on the initial run.
  Fixed (nested try/except) + **incremental save after every term** (never
  a total loss again, even if the process gets killed mid-run, which
  happened once).
  (2) far-away tiles (past ~50, loaded via scroll) were sometimes unstable
  to click — fixed with `scroll_into_view_if_needed()` before every click.
  Result: 1539 unique products collected (0 invalid barcode, 0 duplicate),
  across 3 cumulative scraping sessions (automatic resume via dedup against
  the file already written).
- `src/ingestion/normalize_shufersal.py`: aligns the schema with the
  original dataset before merging — `has_ingredients` recomputed,
  `ingredients_text_en` `None` → `""` (dataset convention),
  `country_of_origin` and `categories` translated Hebrew→English (44
  countries, ~110 categories mapped by hand; the rest — mostly the site's
  promotional/seasonal noise like "SUPER SALE", "פורים", "ראש השנה" rather
  than real categories — is dropped rather than translated blindly, never
  an invented translation). Idempotent: a category already in English
  (previous run) is detected via the presence of Hebrew characters and left
  as-is, not reprocessed as unmapped.
- `src/ingestion/merge_shufersal.py`: merges into
  `scansafe_combined_dataset.json` (checks for no duplicate ID before
  writing), updates the metadata (totals, sources, brands).
- Pipeline resynced after the merge: product reindexing
  (`build_products_index.py`, 1999 products) and the Parsing agent rerun
  over the whole dataset — result unchanged (19/186) because the scraped
  products already had their E-codes detected at scrape time from the
  Hebrew text; the (English-only) additive name dictionary can't add
  anything on Hebrew text anyway.

**Known limitation**: `categories`/`country_of_origin` are now in English
for ALL products (original dataset + Shufersal), but category granularity
differs (short slugs like `dairy`/`cheese` for the original dataset vs.
translated Shufersal breadcrumbs like `dairy_and_eggs`/`fresh_milk`) — not
a unified taxonomy, worth keeping in mind if a future category-based
grouping (the "alternatives" feature, step 3) compares the two sources.

### Observed cost point (context for the decision)
The current pipeline uses `claude-opus-5` (the most expensive model) for
Evaluation + Report. For 2 test requests, ~$0.50 of credits consumed —
confirms the need for pre-computation rather than repeated live calls.
Ongoing: evaluating a move to `claude-sonnet-5` to cut the cost of the mass
pre-computation over 460+ products.

## Bugs fixed (Phase 2)
- **Evaluation agent**: `EOF while parsing a string` crash — `max_tokens`
  raised from 2000 to 4096 in `evaluate_additive.py` (same fix as
  `generate_report.py`). Verified on "Emek Gouda Cheese" (3 additives,
  including E202 which used to crash): all 3 get evaluated and the report
  generates all the way through.
- API credits confirmed working (topped up on the account) — the old
  blocker is lifted, the full pipeline is retestable.

## Step 1 — Scoring engine: DONE (`src/scoring/score_product.py`)
Combines two scores, with no LLM call of its own (just arithmetic over
evaluations already produced — see the pre-computation decision):
- **Transformation** (NOVA-inspired heuristic, not an official
  classifier): MINIMALLY_PROCESSED / PROCESSED / ULTRA_PROCESSED based on
  the number of ingredients (parses `ingredients_text_en`, ignores
  parentheses) and the number/type of additives — the presence of a
  synthetic sweetener or flavor enhancer (aspartame, acesulfame_k,
  sucralose, msg, maltitol) is a strong signal on its own, beyond the plain
  count.
- **Additive severity**: takes the WORST case among the classifications
  already produced by the Evaluation agent (never an average — a single
  "avoid" additive must flag the whole product).
- **Combined verdict** (traffic light + short explanation): "avoid" =
  straight to red; ultra-processed + controversial = red; controversial
  alone or ultra-processed alone = orange; otherwise green.

Tested on 3 contrasting products, results as expected:
- Tnuva White Cheese (milk, salt, 0 additives) → 🟢 green, free (no
  additive to evaluate)
- Emek Gilboa Yellow Cheese (E202 alone, controversial) → 🟠 orange
- Yoplait Diet (E1442 + aspartame + acesulfame K, aspartame controversial,
  2 synthetic sweeteners) → 🔴 red

**Next step (to validate before starting): step 2, mass computation** over
the 460 products — model decision (`claude-opus-5` vs. `claude-sonnet-5`
for cost) still to be settled before launching.

## Next step
~~Test interface~~ DONE (see below). MVP complete on the code side.

## Test interface — DONE (`src/cli.py`)
Interactive CLI loop: loads the embedding model and vector store once at
startup, then accepts product queries continuously (instead of relaunching
the whole pipeline every time). Automatically falls back to the additives
"inferred" by the Parsing agent when a product has no declared list —
clearly labeled as such in the output, never confused with data declared by
the source.

**Bug found and fixed while testing**: product search always returned a
result, even for a completely unrelated query (very poor similarity
distance, e.g. 1.4, but a result was still returned). Fixed with a maximum
distance threshold — beyond it, the system honestly answers "no product
found" instead of guessing.

**⚠️ Former blocker: API credits exhausted.** The key in `.env`
authenticates correctly but had no credit (`Your credit balance is too
low`) — confirmed the Pro/API separation already documented above. Action
taken: credits added on console.anthropic.com → Plans & Billing, full
pipeline retested successfully afterward.

## Cleanup performed
37 orphaned `.html` files removed from
`knowledge_base/additives/efsa_raw/` (invalid placeholders from download
attempts blocked by anti-bot measures, all since replaced with real PDFs),
plus `__pycache__/` folders.
Ahead of the public GitHub release: also removed the by-then-empty
`TODO_manual_downloads.md`, the local `.claude/settings.local.json`
(machine-specific IDE settings), and the now-redundant
`data/shufersal_scraped.json` (already merged into
`scansafe_combined_dataset.json`). The raw EFSA PDFs
(`knowledge_base/additives/efsa_raw/*.pdf`, ~400MB of third-party
copyrighted documents) are excluded from the public repo via `.gitignore`
— kept locally, not redistributed; only the short extracted text passages
(`efsa_extracted/`) are published, which is what actually powers the RAG.

## Current status (updated)
- [x] Product dataset collected: 1999 products (460 initial + 1539 via
      scraping shufersal.co.il, see the "Dataset expansion" section)
- [x] Additive knowledge base: 87/87 EFSA opinions collected, extracted,
      indexed (339 passages)
- [x] Product indexing: 1999/1999 (`products` collection)
- [x] Parsing agent (free text → additives): built, tested, not yet wired
      into Matching
- [x] Matching agent: built and tested
- [x] Evaluation agent (LLM + structured schema, sourced): built and tested
- [x] Report agent (final formatting): built and tested
- [x] Full pipeline working end to end
- [x] Test interface (interactive CLI, `src/cli.py`)
- [x] API credits added, full pipeline retested under real conditions
- [x] Phase 2 step 1 — Scoring engine (`src/scoring/score_product.py`):
      transformation + additive severity → traffic-light verdict, tested on
      3 contrasting products
- [ ] Phase 2 step 2 — Mass computation over the 460 products (not started)
- [ ] Phase 2 step 3 — Healthier alternatives (not started)
- [ ] Phase 2 step 4 — Mobile interface / barcode scanning (not started)
- [ ] OCR/photo scan (future feature, v2)
