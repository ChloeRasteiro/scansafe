"""
Extracts the useful passages from EFSA opinions already downloaded.

Usage:
    python src/ingestion/extract_efsa_sections.py
"""

import json
import logging
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FILE = ROOT / "knowledge_base" / "additives" / "efsa_raw" / "manifest.json"
OUTPUT_DIR = ROOT / "knowledge_base" / "additives" / "efsa_extracted"

MAX_SECTION_CHARS = 6000
MAX_HEADING_LINE_LEN = 100
MIN_KEYWORD_COVERAGE = 0.4

SECTION_PATTERNS: dict[str, list[str]] = {
    "abstract": [r"\bABSTRACT\b", r"\bSUMMARY\b"],
    "toxicology": [
        r"\bTOXICOLOGICAL (?:DATA|ASSESSMENT|EVALUATION)\b",
        r"\bTOXICOLOGY\b",
        r"\bSAFETY EVALUATION\b",
    ],
    "adi": [r"\bACCEPTABLE DAILY INTAKE\b", r"\bADI\b", r"\bDJA\b"],
    "conclusions": [r"\bCONCLUSIONS?\b"],
}

NUMBERED_HEADING_BYPASS = {"toxicology", "adi", "conclusions"}

WATERMARK_RE = re.compile(
    r"Downloaded\s+from\s+https?://\S+\s+by\s+.+?Wiley\s+Online\s+Library\s+on\s+"
    r"\[?\d{1,2}/\d{1,2}/\d{4}\]?\.\s+See\s+the\s+Terms\s+and\s+Conditions\s*"
    r"\(https?://\S+\)\s+on\s+Wiley\s+Online\s+Library\s+for\s+rules\s+of\s+use;?"
    r"\s*OA\s+articles\s+are\s+governed\s+by\s+the\s+applicable\s+Creative\s+Commons\s+License",
    re.IGNORECASE,
)
PAGE_HEADER_RE = re.compile(r"^EFSA Journal \d{4};\d+\(\d+\):\S+\s*$", re.MULTILINE)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def extract_full_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n\n".join(pages)
    text = WATERMARK_RE.sub(" ", text)
    text = PAGE_HEADER_RE.sub("", text)
    return text


def find_section_starts(text: str) -> list[tuple[int, str]]:
    candidates: dict[str, list[tuple[int, bool]]] = {c: [] for c in SECTION_PATTERNS}
    pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        numbering = re.match(r"^\d{1,2}(?:\.\d{1,3})*\.\s+", stripped)
        body = stripped[numbering.end():] if numbering else stripped
        if body and len(stripped) <= MAX_HEADING_LINE_LEN:
            for category, patterns in SECTION_PATTERNS.items():
                for p in patterns:
                    m = re.search(p, body, re.IGNORECASE)
                    if not m:
                        continue
                    bypass = numbering and category in NUMBERED_HEADING_BYPASS
                    if bypass or (m.end() - m.start()) >= len(body) * MIN_KEYWORD_COVERAGE:
                        candidates[category].append((pos + line.find(stripped[0]), bool(numbering)))
                        break
        pos += len(line)

    starts = []
    for category, found in candidates.items():
        if not found:
            continue
        pool = [c for c in found if c[1]] or found
        starts.append((min(p for p, _ in pool), category))
    return sorted(starts)


def extract_sections(text: str) -> dict[str, str | None]:
    starts = sorted(find_section_starts(text))
    sections: dict[str, str | None] = {cat: None for cat in SECTION_PATTERNS}

    for i, (start, category) in enumerate(starts):
        next_start = starts[i + 1][0] if i + 1 < len(starts) else start + MAX_SECTION_CHARS
        end = min(next_start, start + MAX_SECTION_CHARS)
        sections[category] = text[start:end].strip()

    return sections


def output_path(additive_id: str, pdf_path: Path) -> Path:
    return OUTPUT_DIR / additive_id / (pdf_path.stem + ".json")


def process_entry(additive_id: str, url: str, entry: dict) -> str:
    pdf_path = ROOT / entry["local_path"]
    dest = output_path(additive_id, pdf_path)

    if dest.exists():
        existing = json.loads(dest.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == entry.get("sha256"):
            return "skip"

    try:
        text = extract_full_text(pdf_path)
    except Exception as exc:
        logger.error("Extraction failed [%s] %s: %s", additive_id, pdf_path.name, exc)
        return "error"

    sections = extract_sections(text)
    missing = [cat for cat, val in sections.items() if val is None]
    if missing:
        logger.warning("[%s] %s: sections not found: %s", additive_id, pdf_path.name, missing)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(
            {
                "additive_id": additive_id,
                "source_url": url,
                "local_pdf_path": entry["local_path"],
                "source_sha256": entry["sha256"],
                "full_text_char_count": len(text),
                "sections": sections,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Extracted: [%s] %s -> %s", additive_id, pdf_path.name, dest.relative_to(ROOT))
    return "ok"


def main() -> None:
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    counts = {"ok": 0, "skip": 0, "error": 0}
    for additive_id, per_additive in manifest.items():
        for url, entry in per_additive.items():
            if entry.get("status") != "ok":
                continue
            counts[process_entry(additive_id, url, entry)] += 1

    logger.info(
        "Done: %d extracted, %d already up to date (skip), %d errors.",
        counts["ok"], counts["skip"], counts["error"],
    )


if __name__ == "__main__":
    main()
