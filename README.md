# ScanSafe

A RAG pipeline that looks up an Israeli supermarket product, pulls its additives, and tells you whether they're fine, controversial, or worth avoiding, citing actual EFSA safety opinions instead of a language model's guess.

## Why I built this

I wanted to know what's actually in the products I buy, in a market (Israel) where the usual apps (Yuka, Open Food Facts) barely have coverage. I checked Open Food Facts specifically and the Israeli product coverage is too thin to be useful, so this uses data scraped directly from retailer sites instead.

The scoring philosophy is the part I care about most. Most food apps lean on fat, sugar, and calorie counts, so a block of real cheese or a bottle of olive oil gets flagged right next to a diet soda full of synthetic sweeteners. That's not the distinction I think matters. A calorie-dense product can still be a single, minimally processed ingredient, and a "light" one can be industrially reformulated with half a dozen additives to get there. So this project deliberately does not score on `nutrition_per_100g`. It looks at what's actually in the additive list, each one checked against real EFSA evidence, and at how industrially processed the product is (ingredient count, presence of synthetic sweeteners or flavor enhancers, a NOVA-style heuristic), and combines the two into a verdict.

It's also a portfolio project. I wanted to build something with a real multi-agent RAG pipeline rather than a single prompt wrapped in a chat UI: retrieval, parsing, matching against a real knowledge base, structured evaluation, and report generation, each as its own step, each one testable on its own.

The one rule I held myself to throughout: every health claim in a report has to trace back to an actual EFSA passage. The LLM never gets to answer from its own training memory. If the knowledge base doesn't have data on an additive, the pipeline says so instead of guessing.

## How it works

```
product name / barcode
        │
        ▼
Retrieval   → semantic search for the product sheet
        │
        ▼
Parsing     → if additives aren't listed explicitly, spot them in the ingredient text
        │
        ▼
Matching    → exact lookup of each additive in the indexed EFSA knowledge base
        │
        ▼
Evaluation  → classify each additive: OK / controversial / avoid / insufficient data
        │
        ▼
Report      → plain-language write-up, sourced, in reports/<product_id>.md
```

Two Chroma collections back this: one indexing ~2000 product sheets (name, brand, category, ingredients, in Hebrew and English), one indexing EFSA opinion excerpts for 87 additives. Both use the same multilingual embedding model so a Hebrew query can retrieve an English passage and vice versa.

The knowledge base isn't hand-written additive fact sheets. It's the actual EFSA re-evaluation opinions (PDF), with the useful sections (abstract, toxicology, ADI, conclusions) extracted and chunked. The idea is that retrieval should hit real source documents, not a paraphrase I typed up myself, so I can't quietly get something wrong when converting it into a "TL;DR of additive X."

## What's here

- `src/ingestion/`: scripts to collect the EFSA PDFs and to scrape shufersal.co.il for product data
- `src/parsing/`: heuristic E-code/name detection in ingredient text
- `src/indexing/`: builds the two Chroma collections
- `src/retrieval/`: the matching agent
- `src/evaluation/`: the Claude-backed classification agent (structured output via Pydantic)
- `src/report/`: final report generation
- `src/scoring/`: the processing-score / additive-severity verdict described above (new, Phase 2)
- `src/cli.py`: interactive loop to try the whole pipeline against a live product query

Run the full pipeline on one product:

```bash
python -m src.report.generate_report "product name"
```

or the interactive version:

```bash
python -m src.cli
```

You'll need an Anthropic API key in a `.env` file (`ANTHROPIC_API_KEY=...`). Note that this is billed separately from a Claude.ai or Claude Code subscription, since they're different products. Everything else (embeddings, vector store) runs locally and free.

## Data

- **Products**: ~2000 items, mixing an initial hand-collected batch (Tnuva, Strauss/Danone, Rami Levy, and a few others) with ~1500 scraped from Shufersal. Skews dairy-heavy: Tnuva alone is a large share of the original batch.
- **Additives**: 87 EFSA re-evaluation opinions, covering the 81 unique additive codes that actually show up in the product data.

## Known limitations

I'd rather list these than have someone discover them the hard way:

- **EFSA source freshness isn't guaranteed.** I went additive by additive to find opinions, but I didn't systematically check every one for a more recent follow-up assessment. The documents used are real and were authoritative when published, but some might not be the latest version for that additive.
- **Section extraction is keyword-based, not layout-aware.** Abstract and toxicology sections extract cleanly on almost all documents. ADI and conclusions sometimes grab a nearby subsection instead of the exact one, because the heuristic can't see the PDF's actual formatting (font size, real heading structure). Retrieval is semantic, so a neighboring passage is usually still relevant, but it's not perfect.
- **Additive detection in free ingredient text only works reliably for E-codes.** For products without a structured additive list, the parser can pick out things like "E202" or "carrageenan" from the text, but Hebrew-only ingredient descriptions (most of the scraped Shufersal products) won't match the English name dictionary. It still catches E-codes fine since those show up in Latin script regardless of surrounding language.
- **Category granularity isn't unified between the two data sources.** The original dataset uses short category slugs; the Shufersal data uses translated category breadcrumbs. Both are in English now, but they don't line up one-to-one, which matters if you're trying to group products by category.
- **This is a demo-scale project, not a consumer app.** No caching layer for the LLM calls yet, so evaluating a product with several additives costs a few real API calls each time you look it up (roughly $0.25 per product on `claude-opus-5`). Phase 2 below is about fixing exactly this.

## What's next

The MVP pipeline works end to end, but it's not built for standing in a supermarket aisle and getting an instant answer: every lookup still re-runs the LLM calls. Phase 2 is about pre-computing:

1. ~~Scoring engine~~ (done): combines the processing score and additive severity into a green/orange/red verdict.
2. Batch-score the whole dataset once, store the results, so nothing needs to hit the API live except products that aren't in the dataset at all.
3. Suggest healthier alternatives: once everything's pre-scored, comparing a product against others in its category is free.
4. A minimal mobile-friendly page for barcode lookup against the pre-computed results (product IDs in the dataset are already barcodes).

Further out: OCR so you can photograph a label instead of typing a product name.

## Stack

Python, Chroma (local vector store), `sentence-transformers` for multilingual embeddings, Claude (`claude-opus-5`) for classification and report writing, Playwright for scraping, pdfplumber for PDF text extraction.
