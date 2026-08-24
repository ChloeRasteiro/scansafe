"""
Indexes the product sheets into Chroma.

Usage:
    python src/indexing/build_products_index.py
"""

import json
import logging
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
DATASET_FILE = ROOT / "scansafe_combined_dataset.json"
VECTOR_STORE_DIR = ROOT / "vector_store"
COLLECTION_NAME = "products"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def product_text(p: dict) -> str:
    parts = [
        p.get("product_name") or "",
        p.get("product_name_he") or "",
        p.get("brand") or "",
        ", ".join(p.get("categories") or []),
        p.get("ingredients_text_en") or "",
        p.get("ingredients_text_he") or "",
    ]
    return "\n".join(part for part in parts if part)


def product_metadata(p: dict) -> dict:
    kosher = p.get("kosher") or {}
    return {
        "product_id": p.get("product_id") or "",
        "product_name": p.get("product_name") or "",
        "brand": p.get("brand") or "",
        "categories": ", ".join(p.get("categories") or []),
        "additives": ", ".join(p.get("additives") or []),
        "allergens": ", ".join(p.get("allergens") or []),
        "kosher_status": kosher.get("status") or "",
        "country_of_origin": p.get("country_of_origin") or "",
        "has_ingredients": bool(p.get("has_ingredients")),
    }


def load_chunks() -> list[dict]:
    data = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    chunks = []
    for p in data["products"]:
        text = product_text(p)
        if not text.strip():
            continue
        chunks.append({"id": p["product_id"], "text": text, "metadata": product_metadata(p)})
    return chunks


def main() -> None:
    chunks = load_chunks()
    if not chunks:
        logger.warning("No products found in %s", DATASET_FILE.relative_to(ROOT))
        return

    logger.info("Loading embedding model (%s)...", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)

    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    logger.info("Embedding %d products...", len(chunks))
    embeddings = model.encode(
        [c["text"] for c in chunks], show_progress_bar=True, normalize_embeddings=True
    )

    collection.upsert(
        ids=[c["id"] for c in chunks],
        embeddings=embeddings.tolist(),
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )

    logger.info(
        "Done: %d products indexed in the '%s' collection (%s).",
        len(chunks), COLLECTION_NAME, VECTOR_STORE_DIR.relative_to(ROOT),
    )


if __name__ == "__main__":
    main()
