"""
Indexes the EFSA extracts into Chroma.

Usage:
    python src/indexing/build_additives_index.py
"""

import json
import logging
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
EXTRACTED_DIR = ROOT / "knowledge_base" / "additives" / "efsa_extracted"
VECTOR_STORE_DIR = ROOT / "vector_store"
COLLECTION_NAME = "additives"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_chunks() -> list[dict]:
    chunks = []
    for path in EXTRACTED_DIR.glob("*/*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for section, text in doc["sections"].items():
            if not text:
                continue
            chunks.append({
                "id": f"{doc['additive_id']}__{path.stem}__{section}",
                "text": text,
                "metadata": {
                    "additive_id": doc["additive_id"],
                    "section": section,
                    "source_url": doc["source_url"],
                    "local_pdf_path": doc["local_pdf_path"],
                },
            })
    return chunks


def main() -> None:
    chunks = load_chunks()
    if not chunks:
        logger.warning("No extracts found in %s — run extract_efsa_sections.py first.",
                        EXTRACTED_DIR.relative_to(ROOT))
        return

    logger.info("Loading embedding model (%s)...", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)

    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    logger.info("Embedding %d passages...", len(chunks))
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
        "Done: %d passages indexed in the '%s' collection (%s).",
        len(chunks), COLLECTION_NAME, VECTOR_STORE_DIR.relative_to(ROOT),
    )


if __name__ == "__main__":
    main()
