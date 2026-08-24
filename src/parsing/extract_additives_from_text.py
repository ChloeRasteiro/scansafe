"""
Parsing agent: spots known additives (E-codes or names) in ingredients_text_en
for products with no structured additive list.

Usage:
    python src/parsing/extract_additives_from_text.py
    python src/parsing/extract_additives_from_text.py --all
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET_FILE = ROOT / "scansafe_combined_dataset.json"
SOURCES_FILE = ROOT / "src" / "ingestion" / "efsa_sources.json"

NAME_ALIASES: dict[str, list[str]] = {
    "acesulfame_k": ["acesulfame k", "acesulfame-k", "acesulfame potassium"],
    "anthocyanin": ["anthocyanin", "anthocyanins"],
    "aspartame": ["aspartame"],
    "benzoic_acid": ["benzoic acid"],
    "calcium_propionate": ["calcium propionate"],
    "caramel_coloring": ["caramel color", "caramel colour"],
    "carrageenan": ["carrageenan", "carrageenans"],
    "curcumin": ["curcumin"],
    "glycerol": ["glycerol", "glycerin", "glycerine"],
    "guar_gum": ["guar gum"],
    "lactic_acid": ["lactic acid"],
    "lecithin": ["lecithin"],
    "lycopene": ["lycopene"],
    "maltitol": ["maltitol"],
    "methyl_cellulose": ["methyl cellulose", "methylcellulose"],
    "msg": ["msg", "monosodium glutamate"],
    "phosphates": ["phosphate", "phosphates"],
    "potassium_sorbate": ["potassium sorbate"],
    "sodium_benzoate": ["sodium benzoate"],
    "sodium_nitrite": ["sodium nitrite"],
    "sorbic_acid": ["sorbic acid"],
    "soy_lecithin": ["soy lecithin", "soya lecithin"],
    "stevia": ["stevia", "steviol glycoside"],
    "sucralose": ["sucralose"],
    "tocopherols": ["tocopherol", "tocopherols"],
    "xanthan_gum": ["xanthan gum"],
}

E_CODE_RE = re.compile(r"\bE[\s-]?(\d{3,4})\s*([ivx]{1,4})?\b", re.IGNORECASE)
SOY_LECITHIN_RE = re.compile(r"\bsoy(?:a)?\s+lecithin\b")


def load_known_ids() -> set[str]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return set(data.keys())


def find_e_codes(text: str, known_ids: set[str]) -> set[str]:
    found = set()
    for digits, roman in E_CODE_RE.findall(text):
        code = f"E{digits}{roman.lower()}"
        if code in known_ids:
            found.add(code)
    return found


def find_named_additives(text: str) -> set[str]:
    lower = text.lower()
    found = set()
    has_soy_lecithin = bool(SOY_LECITHIN_RE.search(lower))
    if has_soy_lecithin:
        found.add("soy_lecithin")

    for additive_id, aliases in NAME_ALIASES.items():
        if additive_id == "soy_lecithin":
            continue
        if additive_id == "lecithin" and has_soy_lecithin:
            remainder = SOY_LECITHIN_RE.sub("", lower)
            if not re.search(r"\blecithin\b", remainder):
                continue
        if any(re.search(rf"\b{re.escape(alias)}\b", lower) for alias in aliases):
            found.add(additive_id)

    return found


def extract_additives_from_text(text: str, known_ids: set[str]) -> list[str]:
    if not text:
        return []
    found = find_e_codes(text, known_ids) | find_named_additives(text)
    return sorted(found & known_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Process all matching products (default: sample)")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--output", type=Path, help="Write the results (products with at least one match) as JSON")
    args = parser.parse_args()

    known_ids = load_known_ids()
    data = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    candidates = [
        p for p in data["products"]
        if not (p.get("additives") or []) and p.get("ingredients_text_en")
    ]
    targets = candidates if args.all else candidates[: args.sample_size]

    results = {}
    n_with_match = 0
    for p in targets:
        matches = extract_additives_from_text(p["ingredients_text_en"], known_ids)
        if matches:
            n_with_match += 1
            results[p["product_id"]] = {
                "additives_parsed": matches,
                "source_field": "ingredients_text_en",
            }
        if not args.output:
            print(f"[{p['product_id']}] {p['product_name']}")
            print(f"  ingredients: {p['ingredients_text_en'][:150]}")
            print(f"  additives detected: {matches or '(none)'}")
            print()

    print(f"Summary: {n_with_match}/{len(targets)} products (out of {len(candidates)} matching in total) with at least one additive detected.")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Written: {args.output}")


if __name__ == "__main__":
    main()
