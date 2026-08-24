"""
Report agent: generates the final natural-language report for a product.

Usage:
    python -m src.report.generate_report "product name"
"""

import argparse
import sys
from pathlib import Path

import anthropic
import chromadb
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from src.evaluation.evaluate_additive import MODEL, evaluate_additive
from src.retrieval.match_additives import EMBEDDING_MODEL, VECTOR_STORE_DIR, find_product, match_additives

load_dotenv()

REPORT_SYSTEM_PROMPT = """You write a food safety report for a general audience (not \
experts), in English, from a list of additives already classified \
(OK / controversial / avoid / insufficient data) with their justification and \
supporting evidence. Do NOT add any medical or toxicological information that isn't \
already present in the provided classifications — you simplify and structure, you \
invent nothing.

Expected structure:
1. A short overall verdict (1-2 sentences) about the product
2. For each additive: its name, its classification, a simple explanation (2-4 \
sentences, no toxicological jargon) of why, citing the source(s) (URL) in parentheses
3. If an additive is "insufficient data", say so clearly instead of ignoring it or \
guessing

Neutral, factual tone — never alarmist nor more reassuring than what the source says."""


def build_report_input(product_name: str, brand: str, evaluations: list[dict]) -> str:
    lines = [f"Product: {product_name} (brand: {brand})", ""]
    for e in evaluations:
        lines.append(f"## Additive: {e['additive_id']}")
        lines.append(f"Classification: {e['classification']}")
        lines.append(f"Justification: {e['justification']}")
        for evidence in e["key_evidence"]:
            lines.append(f"- {evidence}")
        lines.append(f"Sources: {', '.join(e['sources']) or '(none)'}")
        lines.append("")
    return "\n".join(lines)


def generate_report(client: anthropic.Anthropic, product_name: str, brand: str, evaluations: list[dict]) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=REPORT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_report_input(product_name, brand, evaluations)}],
    )
    return next(block.text for block in response.content if block.type == "text")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Product name to search for (EN or HE)")
    args = parser.parse_args()

    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    chroma_client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    products_collection = chroma_client.get_or_create_collection("products")
    additives_collection = chroma_client.get_or_create_collection("additives")
    anthropic_client = anthropic.Anthropic()

    match = find_product(args.query, products_collection, embedding_model)
    if not match:
        print("No product found in the corpus.")
        return

    meta = match["metadata"]
    additive_ids = [a.strip() for a in meta["additives"].split(",") if a.strip()]
    if not additive_ids:
        print("No structured additives for this product (needs the Parsing agent).")
        return

    matches = match_additives(additive_ids, additives_collection)
    evaluations = []
    for additive_id, result in matches.items():
        evaluation = evaluate_additive(anthropic_client, additive_id, result["passages"])
        sources = sorted({p["source_url"] for p in result["passages"]})
        evaluations.append({
            "additive_id": additive_id,
            "classification": evaluation.classification,
            "justification": evaluation.justification,
            "key_evidence": evaluation.key_evidence,
            "sources": sources,
        })

    report = generate_report(anthropic_client, meta["product_name"], meta["brand"], evaluations)

    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f"{match['product_id']}.md"
    out_path.write_text(report, encoding="utf-8")

    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    print(f"\n(report also written to {out_path})")


if __name__ == "__main__":
    main()
