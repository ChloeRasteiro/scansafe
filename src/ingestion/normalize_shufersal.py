"""
Normalizes data/shufersal_scraped.json to match the main dataset schema.

Usage:
    python -m src.ingestion.normalize_shufersal
"""

import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRAPED_FILE = ROOT / "data" / "shufersal_scraped.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

COUNTRY_EN = {
    "ישראל": "Israel", "איטליה": "Italy", "תאילנד": "Thailand", "בלגיה": "Belgium",
    "הולנד": "Netherlands", "צרפת": "France", "מקדוניה": "North Macedonia", "סרביה": "Serbia",
    "ספרד": "Spain", "הודו": "India", "ליטא": "Lithuania", "וייטנאם": "Vietnam",
    "אזרבייג'אן": "Azerbaijan", "פולין": "Poland", "סין": "China", 'ארה"ב': "USA",
    "אוקראינה": "Ukraine", "גרמניה": "Germany", "בריטניה": "United Kingdom", "צ'כיה": "Czech Republic",
    "מצרים": "Egypt", "שוודיה": "Sweden", "אוסטריה": "Austria", "בוסניה": "Bosnia and Herzegovina",
    "יוון": "Greece", "קנדה": "Canada", "רוסיה הלבנה": "Belarus", "קולומביה": "Colombia",
    "פרגוואי": "Paraguay", "בולגריה": "Bulgaria", "סינגפור": "Singapore", "שוויץ": "Switzerland",
    "רומניה": "Romania", "צ'ילה": "Chile", "לטביה": "Latvia", "פיליפינים": "Philippines",
    "קוסטה ריקה": "Costa Rica", "הפדרציה הרוסית": "Russian Federation", "פורטוגל": "Portugal",
    "סרי-לנקה": "Sri Lanka", "תורכיה": "Turkey", "פינלנד": "Finland", "ברזיל": "Brazil",
}

CATEGORY_EN = {
    "סופרמרקט": None,
    "בישול אפיה ושימורים": "cooking_baking_and_preserves",
    "חטיפים מתוקים ודגני בוקר": "sweet_snacks_and_cereals",
    "מוצרי חלב וביצים": "dairy_and_eggs",
    "בחזרה לבית ספר ולגן": None,
    "ארוחת עשר": "kids_snacks",
    "עוגות עוגיות וופלים - ארוז": "packaged_cakes_cookies_and_wafers",
    "SUPER SALE": None,
    "לחמים ומוצרי מאפה": "bread_and_bakery",
    "יינות משקאות כהליים ותירוש": "wine_and_alcoholic_beverages",
    "שימורים": "canned_goods",
    "משקאות קלים": "soft_drinks",
    "מזון מהמקרר ומהמקפיא": "refrigerated_and_frozen_food",
    "חטיפים מלוחים": "salty_snacks",
    "לחמי מחמצת, חלות ולחמים פרוסים": "sourdough_challah_and_sliced_bread",
    "פסטה אורז קוסקוס וקטניות": "pasta_rice_couscous_and_legumes",
    "עוגיות ארוזות": "packaged_cookies",
    "שימורי דגים וטונה": "canned_fish_and_tuna",
    "חלב טרי": "fresh_milk",
    "ממרחים": "spreads",
    "פירות וירקות": "fruits_and_vegetables",
    "דגנים וחטיפי דגנים": "cereals_and_cereal_bars",
    "לחמים וחלות במאפיה": "bakery_bread_and_challah",
    "חטיפים שונים": "assorted_snacks",
    "ירקות ופירות קפואים": "frozen_fruits_and_vegetables",
    "פורים": None,
    "ראש השנה": None,
    "גרנולה וקוואקר": "granola_and_oats",
    "אורגני ובריאות": "organic_and_health",
    "רטבים ותוספות": "sauces_and_condiments",
    "תחליפי חלב וטופו": "dairy_alternatives_and_tofu",
    "תחליפי חלב": "dairy_alternatives",
    "קמח": "flour",
    "מוצרים בפיקוח": None,
    "מוצרי יסוד ותבלינים": "staples_and_spices",
    "קורנפלס וחטיפי דגנים": "cornflakes_and_cereal_snacks",
    "ירקות קפואים": "frozen_vegetables",
    "מיץ סחוט טרי": "fresh_squeezed_juice",
    "מאפים מלוחים ומתוקים": "savory_and_sweet_pastries",
    "מאפה מתוק ודונאט'ס ": "sweet_pastries_and_donuts",
    "ביסקוויטים": "biscuits",
    "אורז": "rice",
    "פסטה ואטריות": "pasta_and_noodles",
    "קטשופ מיונז וחרדל": "ketchup_mayo_and_mustard",
    "ירקות ופירות מצוננים": "chilled_fruits_and_vegetables",
    "רטבים לסלט": "salad_dressings",
    "משקאות מוגזים ": "carbonated_drinks",
    "מוצרים ללא גלוטן": "gluten_free_products",
    "ממתקים וחטיפים למשלוח מנות": None,
    "מדף הגבינות": "cheese_shelf",
    "יוגורטים": "yogurts",
    "בוסט רעננות": None,
    "משקאות אישיים": "single_serve_drinks",
    " אפיה ובישול": "baking_and_cooking",
    "עזרי אפיה ובישול": "baking_and_cooking_aids",
    "אוכל מוכן / להכנה מהירה": "ready_to_eat_or_quick_prep",
    "מנות להכנה מהירה": "quick_prep_meals",
    "שמן חומץ ומיץ לימון": "oil_vinegar_and_lemon_juice",
    "חומץ ומיץ לימון": "vinegar_and_lemon_juice",
    "משקאות תוססים מארזים": "sparkling_drinks_multipacks",
    "שימורי עגבניות": "canned_tomatoes",
    "מזון מקורר וקפוא": "chilled_and_frozen_food",
    "חטיפי בוטנים": "peanut_snacks",
    "green בריאות וטבע": None,
    "מוצרי בשר, עוף ודגים ": "meat_poultry_and_fish",
    "רטבים לפסטה": "pasta_sauces",
    "גבינות מלוחות": "salty_cheeses",
    "מוצרי חירום": None,
    "ללא גלוטן": "gluten_free",
    "דגנים גרנולה וקווקאר": "cereals_granola_and_oats",
    "דגני בוקר וגרנולה ללא גלוטן": "gluten_free_cereal_and_granola",
    "שולחן חג 10": None,
    "עשרות מבצעים ב-10 ש\"ח": None,
    "פסטות ואורז": "pasta_and_rice",
    "לחמים ארוזים": "packaged_bread",
    "ירקות טריים": "fresh_vegetables",
    "מוצרים לבישול ואפיה": "cooking_and_baking_products",
    "רטבים לבישול ותיבול": "cooking_and_seasoning_sauces",
    "בצקים ומאפים קפואים": "frozen_dough_and_pastries",
    "גבינות מעדנייה": "deli_cheeses",
    "גבינות מלוחות וצפתיות": "brined_and_salty_cheeses",
    "גבינות צהובות ומגורדות": "yellow_and_grated_cheeses",
    "מה חדש": None,
    "דגים": "fish",
    "דגים קפואים": "frozen_fish",
    "דיאט וללא סוכר": "diet_and_sugar_free",
    "קורנפלקס וגרנולה דיאטטים": "diet_cornflakes_and_granola",
    "וופלים וגביעי גלידה": "wafers_and_ice_cream_cones",
    "גלידות": "ice_cream",
    "עוגות ארוזות": "packaged_cakes",
    "חטיפים/מאפים מתוקים/ממתקים": "sweet_snacks_pastries_and_candy",
    "בשר עוף ודגים": "meat_poultry_and_fish",
    "קפה ותה": "coffee_and_tea",
    "ממתקים": "candy",
    "מוצרי עוף והודו": "poultry_and_turkey_products",
    "בשר בקר וכבש": "beef_and_lamb",
    "חפיסות שוקולד": "chocolate_bars",
    "פירות וירקות אורגני": "organic_fruits_and_vegetables",
    "ירקות, פירות ואגוזים": "vegetables_fruits_and_nuts",
    "פיצוחים ופירות יבשים": "nuts_and_dried_fruits",
    "ירקות אורגניים": "organic_vegetables",
    "תבלינים": "spices",
    "בקר וכבש קפוא": "frozen_beef_and_lamb",
    "תה ירוק": "green_tea",
    "דגנים, משקאות ומתוקים": "cereals_beverages_and_sweets",
    "ירקות ופירות אורגניים": "organic_vegetables_and_fruits",
    "עשבי תיבול אורגניים": "organic_herbs",
    "ללא תוספת סוכר": "no_added_sugar",
    "בשר טרי": "fresh_meat",
    "תה רגיל וארל גריי": "regular_and_earl_grey_tea",
    "מרקים קרוטונים ותבשילים": "soups_croutons_and_prepared_dishes",
    "עוף / אווז קפוא": "frozen_chicken_and_goose",
    "טעמי המזרח הרחוק": "far_east_flavors",
    "פירות אורגניים": "organic_fruits",
    "בשר": "meat",
    "עוף": "chicken",
    "שמנים צמחיים": "vegetable_oils",
    "מלפפונים חמוצים / במלח": "pickled_or_salted_cucumbers",
    "תה צמחים וחליטות": "herbal_tea_and_infusions",
    "דגני בוקר קוואקר וגרנולה": "cereal_oats_and_granola",
    "קפה נמס שוקו ומלבין": "instant_coffee_cocoa_and_creamer",
    "פירות וירקות אורגניים": "organic_fruits_and_vegetables",
    "קפה שחור": "black_coffee",
    "פריכיות וקרקרים": "crackers_and_crispbread",
    "אגוזים ופירות יבשים אורגניים": "organic_nuts_and_dried_fruits",
    "פירות יבשים אורגניים": "organic_dried_fruits",
    "עוף טרי מהדרין": "fresh_chicken_mehadrin",
    "עוף טרי שופרסל": None,
    "ממתיקים": "sweeteners",
    "פיצוחים טבעי": "natural_nuts_and_seeds",
    "שמן זית": "olive_oil",
}


def is_hebrew(text: str) -> bool:
    return any("֐" <= ch <= "׿" for ch in text)


def translate_categories(categories: list[str]) -> list[str]:
    result = []
    for c in categories:
        if not is_hebrew(c):
            mapped = c
        else:
            mapped = CATEGORY_EN.get(c, "__unmapped__")
            if mapped == "__unmapped__":
                logger.debug("Unmapped category, dropped: %s", c)
                continue
            if mapped is None:
                continue
        if mapped not in result:
            result.append(mapped)
    return result


def normalize_product(p: dict) -> dict:
    p["has_ingredients"] = bool(p.get("ingredients_text_he"))
    p["ingredients_text_en"] = p.get("ingredients_text_en") or ""
    p["country_of_origin"] = COUNTRY_EN.get(p["country_of_origin"], p["country_of_origin"])
    p["categories"] = translate_categories(p.get("categories") or [])
    return p


def main() -> None:
    products = json.loads(SCRAPED_FILE.read_text(encoding="utf-8"))
    normalized = [normalize_product(p) for p in products]

    no_category = sum(1 for p in normalized if not p["categories"])
    unmapped_countries = {p["country_of_origin"] for p in normalized if p["country_of_origin"] not in COUNTRY_EN.values()}

    SCRAPED_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Normalized: %d products.", len(normalized))
    logger.info("Products with no category after noise filtering: %d/%d", no_category, len(normalized))
    if unmapped_countries:
        logger.warning("Untranslated countries (left in Hebrew): %s", unmapped_countries)


if __name__ == "__main__":
    main()
