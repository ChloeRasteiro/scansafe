"""
Scoring engine (Phase 2): combines a processing-level score with additive
severity into an overall verdict (traffic light).

Usage (demo/validation on one product):
    python -m src.scoring.score_product "product name"
"""

import argparse
import json
from enum import IntEnum
from pathlib import Path

import anthropic
import chromadb
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from src.evaluation.evaluate_additive import evaluate_additive
from src.retrieval.match_additives import EMBEDDING_MODEL, VECTOR_STORE_DIR, find_product, match_additives

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
DATASET_FILE = ROOT / "scansafe_combined_dataset.json"


class TransformationLevel(IntEnum):
    MINIMALLY_PROCESSED = 1
    PROCESSED = 2
    ULTRA_PROCESSED = 3


ULTRA_PROCESSING_MARKERS = {"aspartame", "acesulfame_k", "sucralose", "msg", "maltitol"}

SEVERITY_BY_CLASSIFICATION = {"OK": 0, "insufficient data": 1, "controversial": 2, "avoid": 3}
VERDICT_LABELS = {"green": "🟢 green", "orange": "🟠 orange", "red": "🔴 red"}


def count_ingredients(ingredients_text: str) -> int:
    if not ingredients_text:
        return 0
    depth = 0
    count = 1
    for ch in ingredients_text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            count += 1
    return count


def score_transformation(ingredients_text: str, additive_ids: list[str]) -> tuple[TransformationLevel, str]:
    n_ingredients = count_ingredients(ingredients_text)
    n_additives = len(additive_ids)
    markers = ULTRA_PROCESSING_MARKERS & set(additive_ids)

    if markers or n_additives >= 3:
        detail = f"{n_additives} additive(s), including a synthetic sweetener/flavor enhancer ({', '.join(markers)})" if markers else f"{n_additives} additives"
        return TransformationLevel.ULTRA_PROCESSED, detail
    if n_additives >= 1 or n_ingredients >= 5:
        return TransformationLevel.PROCESSED, f"{n_ingredients} ingredients, {n_additives} additive(s)"
    return TransformationLevel.MINIMALLY_PROCESSED, f"{n_ingredients} ingredients, no additives"


def score_additive_severity(evaluations: list[dict]) -> tuple[int, str]:
    if not evaluations:
        return 0, "no additives"
    worst = max(evaluations, key=lambda e: SEVERITY_BY_CLASSIFICATION[e["classification"]])
    return SEVERITY_BY_CLASSIFICATION[worst["classification"]], f"{worst['additive_id']} ({worst['classification']})"


def combine_verdict(transformation: TransformationLevel, severity: int, severity_detail: str, transformation_detail: str) -> dict:
    ultra = transformation == TransformationLevel.ULTRA_PROCESSED

    if severity == 3:
        color, reason = "red", f'additive classified "avoid": {severity_detail}'
    elif severity == 2 and ultra:
        color, reason = "red", f"ultra-processed product ({transformation_detail}) with a controversial additive: {severity_detail}"
    elif severity == 2:
        color, reason = "orange", f"controversial additive: {severity_detail}"
    elif ultra:
        color, reason = "orange", f"ultra-processed product: {transformation_detail}"
    else:
        color, reason = "green", f"{transformation_detail}, additives with no concern"

    return {
        "color": color,
        "label": VERDICT_LABELS[color],
        "transformation_level": transformation.name,
        "additive_severity": severity,
        "explanation": reason,
    }


def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Product name to search for (EN or HE)")
    args = parser.parse_args()

    dataset = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    products_by_id = {p["product_id"]: p for p in dataset["products"]}

    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    chroma_client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    products_collection = chroma_client.get_or_create_collection("products")
    additives_collection = chroma_client.get_or_create_collection("additives")
    anthropic_client = anthropic.Anthropic()

    match = find_product(args.query, products_collection, embedding_model)
    if not match:
        print("No product found.")
        return

    meta = match["metadata"]
    ingredients_text = products_by_id.get(match["product_id"], {}).get("ingredients_text_en") or ""
    additive_ids = [a.strip() for a in meta["additives"].split(",") if a.strip()]

    evaluations = []
    if additive_ids:
        matches = match_additives(additive_ids, additives_collection)
        for additive_id, result in matches.items():
            print(f"Evaluating {additive_id}...", end=" ", flush=True)
            evaluation = evaluate_additive(anthropic_client, additive_id, result["passages"])
            print(f"-> {evaluation.classification}")
            evaluations.append({"additive_id": additive_id, "classification": evaluation.classification})

    transformation, transformation_detail = score_transformation(ingredients_text, additive_ids)
    severity, severity_detail = score_additive_severity(evaluations)
    verdict = combine_verdict(transformation, severity, severity_detail, transformation_detail)

    print(f"\nProduct: {meta['product_name']} ({meta['brand']})")
    print(f"Transformation: {transformation.name} ({transformation_detail})")
    print(f"Verdict: {verdict['label']}")
    print(f"Reason: {verdict['explanation']}")


if __name__ == "__main__":
    main()
