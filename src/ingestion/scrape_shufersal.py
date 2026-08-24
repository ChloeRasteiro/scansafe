"""
Scrapes shufersal.co.il to grow scansafe_combined_dataset.json.

Usage:
    python -m src.ingestion.scrape_shufersal --terms חלב יוגורט --cap 10
    python -m src.ingestion.scrape_shufersal
"""

import argparse
import json
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from src.parsing.extract_additives_from_text import find_e_codes, load_known_ids

ROOT = Path(__file__).resolve().parents[2]
DATASET_FILE = ROOT / "scansafe_combined_dataset.json"
OUTPUT_FILE = ROOT / "data" / "shufersal_scraped.json"
BASE_URL = "https://www.shufersal.co.il/online/he/search?text={term}"

DELAY_BETWEEN_PRODUCTS = 1.5

DEFAULT_TERMS = {
    "dairy": ["חלב", "גבינה", "יוגורט"],
    "snacks": ["חטיפים", "במבה", "ביסקוויט"],
    "drinks": ["משקה", "מיץ", "קולה"],
    "grocery": ["אורז", "פסטה", "קמח"],
    "canned": ["שימורים", "טונה"],
    "cereals": ["דגני בוקר", "גרנולה"],
    "sauces": ["רוטב", "קטשופ", "מיונז"],
    "frozen": ["קפואים", "גלידה"],
    "bakery": ["לחם", "עוגות", "מאפים"],
    "produce": ["ירקות", "פירות"],
    "meat_fish": ["בשר", "עוף", "דגים"],
    "pantry": ["תבלינים", "שמן", "חומץ"],
    "beverages_extra": ["קפה", "תה"],
    "sweets": ["שוקולד", "ממתקים"],
    "other": ["ביצים", "חמוצים"],
}

NUTRITION_KEY_BY_HEBREW = {
    "אנרגיה": "energy_kcal",
    "חלבונים": "protein_g",
    "שומנים": "fat_g",
    "פחמימות": "carbs_g",
    "סוכרים מתוך פחמימות": "sugars_g",
    "נתרן": "sodium_mg",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def extract_data_list(modal) -> dict[str, str]:
    fields = {}
    for box in modal.locator(".dataList .box").all():
        name = box.locator(".name").inner_text().strip().rstrip(":")
        text_el = box.locator(".text")
        value = (text_el.get_attribute("title") or text_el.inner_text()).strip()
        if name and value:
            fields[name] = value
    return fields


def extract_nutrition(modal) -> dict[str, float]:
    nutrition = {}
    for item in modal.locator(".nutritionItem").all():
        hebrew_name = item.locator(".text").inner_text().strip()
        key = NUTRITION_KEY_BY_HEBREW.get(hebrew_name)
        if not key:
            continue
        raw = item.locator(".number").get_attribute("title")
        try:
            nutrition[key] = float(raw)
        except (TypeError, ValueError):
            pass
    return nutrition


def extract_product(page: Page, known_additive_ids: set[str]) -> dict | None:
    modal = page.locator("#productModal")
    gtm_raw = modal.locator(".modal-dialog").first.get_attribute("data-gtm")
    gtm = json.loads(gtm_raw) if gtm_raw else {}

    fields = extract_data_list(modal)
    barcode = fields.get('מק"ט', "")
    if not re.fullmatch(r"\d{13}", barcode):
        logger.warning("Invalid barcode (%r), skipping product: %s", barcode, gtm.get("productName"))
        return None

    components = modal.locator(".componentsText")
    ingredients_he = components.first.inner_text().strip() if components.count() else ""
    ingredients_he = re.sub(r"\s+", " ", ingredients_he)

    return {
        "product_id": barcode,
        "product_name": gtm.get("productName", ""),
        "product_name_he": gtm.get("productName", ""),
        "brand": fields.get("מותג/יצרן") or gtm.get("brand", ""),
        "categories": [c for c in [gtm.get("categoryLevel1"), gtm.get("categoryLevel2"),
                                    gtm.get("categoryLevel3"), gtm.get("categoryLevel4")] if c],
        "ingredients_text_he": ingredients_he,
        "ingredients_text_en": None,
        "allergens": [],
        "additives": sorted(find_e_codes(ingredients_he, known_additive_ids)),
        "nutrition_per_100g": extract_nutrition(modal),
        "kosher": {
            "status": fields.get("חלבי/בשרי/פרווה", ""),
            "authority": fields.get("כשרות", ""),
            "passover_status": fields.get("פסח", ""),
        },
        "country_of_origin": fields.get("ארץ ייצור", ""),
        "source": "shufersal_scraped",
    }


def collect_tiles(page: Page, cap: int) -> None:
    tiles = page.locator("li.tileBlock")
    previous = -1
    while tiles.count() < cap and tiles.count() != previous:
        previous = tiles.count()
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1500)


def scrape_term(page: Page, term: str, cap: int, seen_ids: set[str], known_additive_ids: set[str]) -> list[dict]:
    page.goto(BASE_URL.format(term=term), timeout=30000, wait_until="networkidle")
    collect_tiles(page, cap)

    tiles = page.locator("li.tileBlock")
    n = min(tiles.count(), cap)
    logger.info("[%s] %d product(s) to process", term, n)

    results = []
    for i in range(n):
        try:
            link = tiles.nth(i).locator("a.imgContainer")
            link.scroll_into_view_if_needed(timeout=10000)
            link.click(timeout=10000)
            page.wait_for_selector("#productModal", state="visible", timeout=10000)
            try:
                page.wait_for_function(
                    '/^\\d{13}$/.test(document.querySelector(".productCode .text")?.getAttribute("title") || "")',
                    timeout=6000,
                )
            except Exception:
                pass
            product = extract_product(page, known_additive_ids)
            if product and product["product_id"] not in seen_ids:
                seen_ids.add(product["product_id"])
                results.append(product)
                logger.info("  OK [%s] %s", product["product_id"], product["product_name"])
            elif product:
                logger.info("  Duplicate skipped: %s", product["product_id"])
        except Exception as exc:
            logger.error("  Error on product %d/%d: %s", i + 1, n, exc)
        finally:
            try:
                close_btn = page.locator("#productModal .btnClose")
                if close_btn.count():
                    close_btn.click(timeout=5000)
            except Exception as exc:
                logger.warning("  Modal close failed (ignored): %s", exc)
            page.wait_for_timeout(int(DELAY_BETWEEN_PRODUCTS * 1000))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms", nargs="*", help="Search terms (default: predefined list by category)")
    parser.add_argument("--cap", type=int, default=30, help="Max number of products per term")
    args = parser.parse_args()

    terms = args.terms or [t for group in DEFAULT_TERMS.values() for t in group]
    known_additive_ids = load_known_ids()
    existing_ids = {p["product_id"] for p in json.loads(DATASET_FILE.read_text(encoding="utf-8"))["products"]}

    all_results = json.loads(OUTPUT_FILE.read_text(encoding="utf-8")) if OUTPUT_FILE.exists() else []
    seen_ids = existing_ids | {p["product_id"] for p in all_results}
    logger.info("Resuming: %d products already scraped in this batch, %d in the existing dataset", len(all_results), len(existing_ids))

    errors = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 2000})
        for term in terms:
            try:
                all_results.extend(scrape_term(page, term, args.cap, seen_ids, known_additive_ids))
            except Exception as exc:
                errors += 1
                logger.error("Term '%s' failed: %s", term, exc)
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT_FILE.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(DELAY_BETWEEN_PRODUCTS)
        browser.close()
    logger.info(
        "Done: %d products collected, %d term(s) failed -> %s",
        len(all_results), errors, OUTPUT_FILE.relative_to(ROOT),
    )


if __name__ == "__main__":
    main()
