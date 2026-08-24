"""
Merges data/shufersal_scraped.json into scansafe_combined_dataset.json.

Usage:
    python -m src.ingestion.merge_shufersal
"""

import json
import logging
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET_FILE = ROOT / "scansafe_combined_dataset.json"
SCRAPED_FILE = ROOT / "data" / "shufersal_scraped.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    dataset = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    scraped = json.loads(SCRAPED_FILE.read_text(encoding="utf-8"))

    existing_ids = {p["product_id"] for p in dataset["products"]}
    overlap = existing_ids & {p["product_id"] for p in scraped}
    if overlap:
        raise SystemExit(f"{len(overlap)} product_id(s) already present — merge aborted, check deduplication.")

    dataset["products"].extend(scraped)

    products = dataset["products"]
    brand_counts = Counter(p.get("brand") for p in products if p.get("brand"))
    dataset["metadata"].update({
        "total_products": len(products),
        "sources": {**dataset["metadata"].get("sources", {}), "shufersal_scraped": len(scraped)},
        "products_with_ingredients": sum(1 for p in products if p.get("ingredients_text_he") or p.get("ingredients_text_en")),
        "unique_brands": len(brand_counts),
        "brand_distribution": dict(brand_counts.most_common()),
    })

    DATASET_FILE.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Merged: %d products added, %d in total (was %d).",
        len(scraped), len(products), len(existing_ids),
    )


if __name__ == "__main__":
    main()
