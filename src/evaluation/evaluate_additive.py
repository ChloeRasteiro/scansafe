"""
Evaluation agent: classifies an additive (OK / controversial / avoid /
insufficient data) from the EFSA extracts retrieved by the Matching agent.

Usage:
    python -m src.evaluation.evaluate_additive "product name"
"""

import argparse
from typing import Literal

import anthropic
import chromadb
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

from src.retrieval.match_additives import EMBEDDING_MODEL, VECTOR_STORE_DIR, find_product, match_additives

load_dotenv()

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You evaluate a food additive for a safety report aimed at the general \
public, based ONLY on the provided EFSA opinion extracts (abstract, toxicology, ADI, \
panel conclusions). Never use outside knowledge not present in these extracts.

Classify the additive into one of these 4 categories:
- "OK": the EFSA panel reports no safety concern at typical usage levels, an ADI is \
established with a sufficient safety margin, no carcinogenic classification mentioned.
- "controversial": the extracts mention elements that justify caution without \
establishing a proven hazard — ADI revised downward, conflicting study results, \
sensitive populations specifically singled out, IARC 2B classification (possibly \
carcinogenic) or scientific uncertainty flagged by the panel.
- "avoid": the extracts mention an IARC 1 or 2A classification (proven or probable \
carcinogen), significant established toxicological effects (genotoxicity, confirmed \
reproductive effects), or an ADI that could not be established/was withdrawn for \
safety reasons.
- "insufficient data": the provided extracts don't allow a call to be made (missing \
section, information too vague). Never force a classification when the information \
isn't there.

Justify in English, citing precise facts from the extracts — never a claim that isn't \
explicitly backed by the provided text."""


class AdditiveEvaluation(BaseModel):
    classification: Literal["OK", "controversial", "avoid", "insufficient data"]
    justification: str = Field(description="Justification in English, based only on the provided extracts")
    key_evidence: list[str] = Field(description="Precise facts or quotes from the extracts that support the classification")


def build_user_prompt(additive_id: str, passages: list[dict]) -> str:
    blocks = [f"Additive: {additive_id}\n"]
    for p in passages:
        blocks.append(f"--- Section: {p['section']} (source: {p['source_url']}) ---\n{p['text']}")
    return "\n\n".join(blocks)


def evaluate_additive(client: anthropic.Anthropic, additive_id: str, passages: list[dict]) -> AdditiveEvaluation:
    if not passages:
        return AdditiveEvaluation(
            classification="insufficient data",
            justification=f"No EFSA data indexed for {additive_id} — collection incomplete for this additive.",
            key_evidence=[],
        )

    response = client.messages.parse(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(additive_id, passages)}],
        output_format=AdditiveEvaluation,
    )
    return response.parsed_output


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
    print(f"Product: {meta['product_name']} (brand: {meta['brand']})\n")

    additive_ids = [a.strip() for a in meta["additives"].split(",") if a.strip()]
    if not additive_ids:
        print("No structured additives for this product (needs the Parsing agent).")
        return

    matches = match_additives(additive_ids, additives_collection)
    for additive_id, result in matches.items():
        evaluation = evaluate_additive(anthropic_client, additive_id, result["passages"])
        print(f"[{additive_id}] -> {evaluation.classification}")
        print(f"  Justification: {evaluation.justification}")
        for evidence in evaluation.key_evidence:
            print(f"  - {evidence}")
        print()


if __name__ == "__main__":
    main()
