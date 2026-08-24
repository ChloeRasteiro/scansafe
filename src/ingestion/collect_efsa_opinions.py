"""
Downloads the EFSA opinions (PDF) referenced in efsa_sources.json into
knowledge_base/additives/efsa_raw/<additive_id>/.

Usage:
    python src/ingestion/collect_efsa_opinions.py
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
SOURCES_FILE = ROOT / "src" / "ingestion" / "efsa_sources.json"
OUTPUT_DIR = ROOT / "knowledge_base" / "additives" / "efsa_raw"
MANIFEST_FILE = OUTPUT_DIR / "manifest.json"
CHECKLIST_FILE = OUTPUT_DIR / "TODO_manual_downloads.md"

STATUS_OK = "ok"
STATUS_MANUAL = "manual_required"

REQUEST_TIMEOUT = 30
DELAY_BETWEEN_REQUESTS = 2
HEADERS = {"User-Agent": "ScanSafe-research-bot/0.1 (personal, non-commercial use)"}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_sources() -> dict[str, list[str]]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    data.pop("_comment", None)
    return data


def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def entry_status(manifest: dict, additive_id: str, url: str) -> str | None:
    return manifest.get(additive_id, {}).get(url, {}).get("status")


def set_entry(manifest: dict, additive_id: str, url: str, **fields) -> None:
    manifest.setdefault(additive_id, {})[url] = {
        "local_path": None,
        "retrieved_at": None,
        "sha256": None,
        "status": STATUS_MANUAL,
        "reason": None,
        "auto_paired": False,
        "copied_from_shared_url": False,
        **fields,
    }


def propagate_to_shared_urls(
    sources: dict[str, list[str]], manifest: dict, url: str, source_additive_id: str,
    source_path: Path, auto_paired: bool,
) -> None:
    content = source_path.read_bytes()
    for other_id, other_urls in sources.items():
        if other_id == source_additive_id or url not in other_urls:
            continue
        if entry_status(manifest, other_id, url) == STATUS_OK:
            continue

        dest_dir = OUTPUT_DIR / other_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / source_path.name
        dest_path.write_bytes(content)

        set_entry(
            manifest, other_id, url,
            local_path=str(dest_path.relative_to(ROOT)),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            sha256=sha256_of(dest_path),
            status=STATUS_OK,
            reason=None,
            auto_paired=auto_paired,
            copied_from_shared_url=True,
        )
        logger.info(
            "Auto-copied (URL shared with %s): [%s] %s -> %s",
            source_additive_id, other_id, url, dest_path.relative_to(ROOT),
        )


def filename_from_url(url: str, is_pdf: bool) -> str:
    name = Path(urlparse(url).path).name or "page"
    name = name if is_pdf or "." in name else name + ".html"
    if is_pdf and not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_one(additive_id: str, url: str, manifest: dict, sources: dict[str, list[str]]) -> None:
    if entry_status(manifest, additive_id, url) == STATUS_OK:
        logger.info("Already downloaded, skip: [%s] %s", additive_id, url)
        return

    dest_dir = OUTPUT_DIR / additive_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        is_pdf = response.content[:5] == b"%PDF-"
        dest_path = dest_dir / filename_from_url(url, is_pdf)
        dest_path.write_bytes(response.content)

        set_entry(
            manifest, additive_id, url,
            local_path=str(dest_path.relative_to(ROOT)),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            sha256=sha256_of(dest_path) if is_pdf else None,
            status=STATUS_OK if is_pdf else STATUS_MANUAL,
            reason=None if is_pdf else "non-PDF response (HTML page/anti-bot) — needs manual download",
        )
        if is_pdf:
            logger.info("OK: [%s] %s -> %s", additive_id, url, dest_path.relative_to(ROOT))
            propagate_to_shared_urls(sources, manifest, url, additive_id, dest_path, auto_paired=False)
        else:
            logger.warning("Not a PDF, added to the manual checklist: [%s] %s", additive_id, url)

    except requests.RequestException as exc:
        set_entry(
            manifest, additive_id, url,
            status=STATUS_MANUAL,
            reason=f"request failed ({exc}) — needs manual download",
        )
        logger.error("Failed: [%s] %s (%s)", additive_id, url, exc)


def mark_ok(manifest: dict, additive_id: str, url: str, path: Path, auto_paired: bool) -> None:
    set_entry(
        manifest, additive_id, url,
        local_path=str(path.relative_to(ROOT)),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        sha256=sha256_of(path),
        status=STATUS_OK,
        reason=None,
        auto_paired=auto_paired,
    )
    flag = " (auto-paired, needs review)" if auto_paired else ""
    logger.info("Manual drop validated%s: [%s] %s -> %s", flag, additive_id, url, path.relative_to(ROOT))


def reconcile_manual_downloads(sources: dict[str, list[str]], manifest: dict) -> None:
    for additive_id, urls in sources.items():
        pending = [u for u in urls if entry_status(manifest, additive_id, u) != STATUS_OK]
        if not pending:
            continue

        folder = OUTPUT_DIR / additive_id
        if not folder.exists():
            continue

        claimed = {
            e["local_path"] for e in manifest.get(additive_id, {}).values()
            if e.get("local_path") and e["status"] == STATUS_OK
        }
        candidates = sorted(
            p for p in folder.glob("*.pdf")
            if str(p.relative_to(ROOT)) not in claimed and p.read_bytes()[:5] == b"%PDF-"
        )
        if not candidates:
            continue

        by_name = {p.name: p for p in candidates}
        for url in list(pending):
            expected = filename_from_url(url, is_pdf=True)
            if expected in by_name:
                path = by_name.pop(expected)
                candidates.remove(path)
                pending.remove(url)
                mark_ok(manifest, additive_id, url, path, auto_paired=False)
                propagate_to_shared_urls(sources, manifest, url, additive_id, path, auto_paired=False)

        if not pending or not candidates:
            continue

        if len(pending) == 1 and len(candidates) == 1:
            mark_ok(manifest, additive_id, pending[0], candidates[0], auto_paired=False)
            propagate_to_shared_urls(sources, manifest, pending[0], additive_id, candidates[0], auto_paired=False)
        elif len(pending) == len(candidates):
            for url, path in zip(pending, sorted(candidates)):
                mark_ok(manifest, additive_id, url, path, auto_paired=True)
                propagate_to_shared_urls(sources, manifest, url, additive_id, path, auto_paired=True)
        else:
            logger.warning(
                "%s: %d pending URL(s) vs %d valid PDF(s) found in %s"
                " -> ambiguous pairing, left as manual_required. Files: %s",
                additive_id, len(pending), len(candidates), folder.relative_to(ROOT),
                [p.name for p in candidates],
            )


def generate_checklist(sources: dict[str, list[str]], manifest: dict) -> None:
    lines = [
        "# EFSA — remaining manual downloads",
        "",
        "Auto-generated by `collect_efsa_opinions.py` — overwritten on every run,"
        " do not edit by hand (links already retrieved automatically don't appear here).",
        "Save the downloaded PDF under the exact suggested name, in the destination folder:"
        " the next run will detect it and update the manifest automatically.",
        "",
    ]
    pending_total = 0

    for additive_id, urls in sources.items():
        pending = [u for u in urls if entry_status(manifest, additive_id, u) == STATUS_MANUAL]
        if not pending:
            continue
        dest_dir = (OUTPUT_DIR / additive_id).relative_to(ROOT)
        lines.append(f"## {additive_id}")
        lines.append(f"Destination: `{dest_dir}/`")
        lines.append("")
        for url in pending:
            reason = manifest[additive_id][url].get("reason") or ""
            expected_name = filename_from_url(url, is_pdf=True)
            lines.append(f"- [ ] {url}")
            lines.append(f"  - Reason: _{reason}_")
            lines.append(f"  - Save as: `{dest_dir}/{expected_name}`")
            pending_total += 1
        lines.append("")

    if pending_total == 0:
        lines.append("Everything was retrieved automatically, nothing left to do by hand.")

    CHECKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKLIST_FILE.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Manual checklist written: %s (%d link(s))", CHECKLIST_FILE.relative_to(ROOT), pending_total)


def main() -> None:
    sources = load_sources()
    manifest = load_manifest()

    reconcile_manual_downloads(sources, manifest)
    save_manifest(manifest)

    total_pairs = sum(len(urls) for urls in sources.values())
    if total_pairs == 0:
        logger.warning(
            "No URLs set in %s — fill in the list per additive before rerunning.",
            SOURCES_FILE.relative_to(ROOT),
        )
        return

    for additive_id, urls in sources.items():
        for url in urls:
            download_one(additive_id, url, manifest, sources)
            save_manifest(manifest)
            time.sleep(DELAY_BETWEEN_REQUESTS)

    generate_checklist(sources, manifest)

    all_entries = [e for per_additive in manifest.values() for e in per_additive.values()]
    ok_count = sum(1 for e in all_entries if e["status"] == STATUS_OK)
    manual_count = sum(1 for e in all_entries if e["status"] == STATUS_MANUAL)
    auto_paired_count = sum(1 for e in all_entries if e.get("auto_paired"))
    copied_count = sum(1 for e in all_entries if e.get("copied_from_shared_url"))
    logger.info(
        "Done: %d PDFs ok (of which %d auto-paired to review, %d auto-copied from"
        " a shared URL), %d left to do manually (out of %d additive/URL pairs) -> see %s",
        ok_count, auto_paired_count, copied_count, manual_count, total_pairs, CHECKLIST_FILE.relative_to(ROOT),
    )


if __name__ == "__main__":
    main()
