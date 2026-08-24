"""
Matching agent (RAG): finds the closest product sheet, then retrieves the
matching EFSA passages for each of its additives.

Usage:
    python src/retrieval/match_additives.py "product name"
"""

import argparse
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
VECTOR_STORE_DIR = ROOT / "vector_store"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
MAX_PRODUCT_DISTANCE = 1.0


def find_product(query: str, products_collection, model) -> dict | None:
    embedding = model.encode([query], normalize_embeddings=True).tolist()
    res = products_collection.query(query_embeddings=embedding, n_results=1)
    if not res["ids"][0] or res["distances"][0][0] > MAX_PRODUCT_DISTANCE:
        return None
    return {
        "product_id": res["ids"][0][0],
        "metadata": res["metadatas"][0][0],
        "distance": res["distances"][0][0],
    }


def match_additives(additive_ids: list[str], additives_collection) -> dict[str, dict]:
    results = {}
    for additive_id in additive_ids:
        got = additives_collection.get(where={"additive_id": additive_id})
        passages = [
            {"section": meta["section"], "text": doc, "source_url": meta["source_url"]}
            for doc, meta in zip(got["documents"], got["metadatas"])
        ]
        results[additive_id] = {"found": bool(passages), "passages": passages}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Product name to search for (EN or HE)")
    args = parser.parse_args()

    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    products_collection = client.get_or_create_collection("products")
    additives_collection = client.get_or_create_collection("additives")

    match = find_product(args.query, products_collection, model)
    if not match:
        print("No product found in the corpus.")
        return

    meta = match["metadata"]
    print(f"Product found: {meta['product_name']} (brand: {meta['brand']}, distance={match['distance']:.3f})")

    additive_ids = [a.strip() for a in meta["additives"].split(",") if a.strip()]
    if not additive_ids:
        print("No structured additives for this product (needs the Parsing agent).")
        return

    for additive_id, result in match_additives(additive_ids, additives_collection).items():
        if result["found"]:
            print(f"  - {additive_id}: {len(result['passages'])} passage(s) found")
        else:
            print(f"  - {additive_id}: NO data (EFSA collection incomplete for this additive)")


if __name__ == "__main__":
    main()
