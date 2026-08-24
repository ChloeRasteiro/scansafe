"""
Test interface: interactive loop over the full pipeline.

Usage:
    python -m src.cli
"""

import json
import sys
from pathlib import Path

import anthropic
import chromadb
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from src.evaluation.evaluate_additive import evaluate_additive
from src.report.generate_report import generate_report
from src.retrieval.match_additives import EMBEDDING_MODEL, VECTOR_STORE_DIR, find_product, match_additives

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
PARSED_ADDITIVES_FILE = ROOT / "data" / "parsed_additives.json"


def get_additive_ids(product_id: str, meta: dict, parsed: dict) -> tuple[list[str], str]:
    declared = [a.strip() for a in meta["additives"].split(",") if a.strip()]
    if declared:
        return declared, "declared"
    inferred = parsed.get(product_id, {}).get("additives_parsed", [])
    if inferred:
        return inferred, "inferred from ingredient text — not declared by the source"
    return [], "none"


def run_pipeline(query, embedding_model, products_collection, additives_collection, anthropic_client, parsed) -> None:
    print(f"\nSearching for '{query}'...")
    match = find_product(query, products_collection, embedding_model)
    if not match:
        print("No product found in the corpus.")
        return

    meta = match["metadata"]
    print(f"Product found: {meta['product_name']} (brand: {meta['brand']}, distance={match['distance']:.3f})")

    additive_ids, source = get_additive_ids(match["product_id"], meta, parsed)
    if not additive_ids:
        print("No additives detected (neither declared nor found in the ingredient text).")
        return
    print(f"Additives ({source}): {', '.join(additive_ids)}")

    matches = match_additives(additive_ids, additives_collection)
    evaluations = []
    for additive_id, result in matches.items():
        print(f"  Evaluating {additive_id}...", end=" ", flush=True)
        evaluation = evaluate_additive(anthropic_client, additive_id, result["passages"])
        print(f"-> {evaluation.classification}")
        sources = sorted({p["source_url"] for p in result["passages"]})
        evaluations.append({
            "additive_id": additive_id,
            "classification": evaluation.classification,
            "justification": evaluation.justification,
            "key_evidence": evaluation.key_evidence,
            "sources": sources,
        })

    print("Generating final report...")
    report = generate_report(anthropic_client, meta["product_name"], meta["brand"], evaluations)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f"{match['product_id']}.md"
    out_path.write_text(report, encoding="utf-8")

    print(f"\n{'=' * 70}\n{report}\n{'=' * 70}")
    print(f"(report also written to {out_path.relative_to(ROOT)})")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Loading embedding model and vector store...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    chroma_client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    products_collection = chroma_client.get_or_create_collection("products")
    additives_collection = chroma_client.get_or_create_collection("additives")
    anthropic_client = anthropic.Anthropic()
    parsed = json.loads(PARSED_ADDITIVES_FILE.read_text(encoding="utf-8")) if PARSED_ADDITIVES_FILE.exists() else {}

    print("Ready. Type a product name (EN or HE), or 'quit' to exit.\n")
    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in {"quit", "exit", "q"}:
            break
        try:
            run_pipeline(query, embedding_model, products_collection, additives_collection, anthropic_client, parsed)
        except anthropic.AuthenticationError:
            print("API authentication error — check ANTHROPIC_API_KEY in .env")
        except anthropic.APIStatusError as exc:
            print(f"API error: {exc}")

    print("\nGoodbye.")


if __name__ == "__main__":
    main()
