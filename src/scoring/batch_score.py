"""
Runs the scoring engine over many products at once and stores the results,
so a future lookup (mobile interface, alternatives feature) never has to
call the API live.

Additive evaluations are cached by additive_id and reused across every
product that shares that additive, since an evaluation only depends on the
additive itself, not on the product. This is what keeps the cost down.

Usage:
    python -m src.scoring.batch_score --sample-size 80   # demo-scale run
    python -m src.scoring.batch_score                    # full dataset
"""

import argparse
import json
import sys
from pathlib import Path

import anthropic
import chromadb
from dotenv import load_dotenv

from src.evaluation.evaluate_additive import evaluate_additive
from src.report.generate_report import generate_report
from src.retrieval.match_additives import VECTOR_STORE_DIR, match_additives
from src.scoring.score_product import combine_verdict, score_additive_severity, score_transformation

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
DATASET_FILE = ROOT / "scansafe_combined_dataset.json"
PARSED_ADDITIVES_FILE = ROOT / "data" / "parsed_additives.json"
OUTPUT_FILE = ROOT / "data" / "precomputed_scores.json"


def additive_ids_for(product: dict, parsed: dict) -> list[str]:
    declared = product.get("additives") or []
    if declared:
        return declared
    return parsed.get(product["product_id"], {}).get("additives_parsed", [])


def select_sample(products: list[dict], parsed: dict, target_with_additives: int, target_without: int) -> list[dict]:
    with_additives = [p for p in products if additive_ids_for(p, parsed)]
    without_additives = [p for p in products if not additive_ids_for(p, parsed)]

    def spread(items: list[dict], n: int) -> list[dict]:
        if len(items) <= n:
            return items
        step = len(items) / n
        return [items[int(i * step)] for i in range(n)]

    return spread(with_additives, target_with_additives) + spread(without_additives, target_without)


def get_or_evaluate(additive_id: str, additives_collection, anthropic_client, cache: dict) -> dict:
    if additive_id not in cache:
        result = match_additives([additive_id], additives_collection)[additive_id]
        evaluation = evaluate_additive(anthropic_client, additive_id, result["passages"])
        sources = sorted({p["source_url"] for p in result["passages"]})
        cache[additive_id] = {
            "additive_id": additive_id,
            "classification": evaluation.classification,
            "justification": evaluation.justification,
            "key_evidence": evaluation.key_evidence,
            "sources": sources,
        }
    return cache[additive_id]


def score_one(product: dict, additive_ids: list[str], additives_collection, anthropic_client, cache: dict) -> dict:
    evaluations = [get_or_evaluate(aid, additives_collection, anthropic_client, cache) for aid in additive_ids]

    transformation, transformation_detail = score_transformation(product.get("ingredients_text_en") or "", additive_ids)
    severity, severity_detail = score_additive_severity(
        [{"additive_id": e["additive_id"], "classification": e["classification"]} for e in evaluations]
    )
    verdict = combine_verdict(transformation, severity, severity_detail, transformation_detail)

    report = (
        generate_report(anthropic_client, product["product_name"], product.get("brand", ""), evaluations)
        if evaluations else None
    )

    return {
        "product_id": product["product_id"],
        "product_name": product["product_name"],
        "brand": product.get("brand", ""),
        "verdict": verdict,
        "additive_ids": additive_ids,
        "report": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, help="Total products to score (default: everything)")
    parser.add_argument("--with-additives-share", type=float, default=0.75, help="Share of the sample that must have additives")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    dataset = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    parsed = json.loads(PARSED_ADDITIVES_FILE.read_text(encoding="utf-8"))
    products = dataset["products"]

    if args.sample_size:
        n_with = int(args.sample_size * args.with_additives_share)
        targets = select_sample(products, parsed, n_with, args.sample_size - n_with)
    else:
        targets = products

    results = json.loads(OUTPUT_FILE.read_text(encoding="utf-8")) if OUTPUT_FILE.exists() else {}
    cache: dict[str, dict] = {}

    chroma_client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    additives_collection = chroma_client.get_or_create_collection("additives")
    anthropic_client = anthropic.Anthropic()

    n_done, n_skipped, n_errors = 0, 0, 0
    for i, product in enumerate(targets, 1):
        if product["product_id"] in results:
            n_skipped += 1
            continue
        additive_ids = additive_ids_for(product, parsed)
        try:
            result = score_one(product, additive_ids, additives_collection, anthropic_client, cache)
        except anthropic.APIError as exc:
            n_errors += 1
            print(f"[{i}/{len(targets)}] ERROR ({exc}) - {product['product_name']}")
            continue
        results[product["product_id"]] = result
        n_done += 1
        print(f"[{i}/{len(targets)}] {result['verdict']['label']}  {result['product_name']}  ({len(additive_ids)} additive(s), {len(cache)} unique so far)")

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDone: {n_done} newly scored, {n_skipped} already present, {n_errors} error(s), {len(cache)} unique additives evaluated -> {OUTPUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
