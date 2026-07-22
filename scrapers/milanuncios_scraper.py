import csv
import json
import os
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)

from app.database import init_db, insert_properties  # noqa: E402


BASE_URL = "https://www.milanuncios.com"
SEARCH_URL = "https://www.milanuncios.com/venta-de-apartamentos/dehesa-de-campoamor.htm"
CACHE_DIR = os.path.join(PROJECT_ROOT, "cached_pages")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_CSV = "milanuncios_properties.csv"


def get_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.replace("\xa0", " ").strip().split())


def clean_price(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = (
        value.replace(".", "")
        .replace(",", "")
        .replace("€", "")
        .replace(" ", "")
        .strip()
    )
    match = re.search(r"\d+", cleaned)
    return int(match.group()) if match else None


def clean_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group()) if match else None


def fetch_page(url: str, page: int = 1) -> str | None:
    local_path = os.path.join(CACHE_DIR, f"milanuncios_page_{page}.html")
    try:
        response = requests.get(url, headers=get_headers(), timeout=20)
        print(f"Milanuncios {response.status_code}: {url}")
        text = response.text
        if response.status_code == 200 and "Pardon Our Interruption" not in text:
            return text
        print("Milanuncios ha devuelto captcha/bloqueo; usando cache local si existe.")
    except requests.RequestException as error:
        print(f"Error descargando Milanuncios: {error}")

    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8") as file:
            return file.read()
    return None


def save_to_csv(listings: list[dict], filename: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    if not listings:
        return
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(listings[0].keys()))
        writer.writeheader()
        writer.writerows(listings)


def extract_images(card) -> list[str]:
    urls = []
    for image in card.find_all("img"):
        for attr in ("src", "data-src"):
            src = image.get(attr)
            if src and src.startswith("http"):
                urls.append(src)
    return list(dict.fromkeys(urls))


def card_candidates(soup: BeautifulSoup) -> list:
    selectors = [
        "article",
        "[class*='aditem']",
        "[class*='AdCard']",
        "[class*='ma-AdCard']",
    ]
    candidates = []
    for selector in selectors:
        candidates.extend(soup.select(selector))
    unique = []
    seen = set()
    for candidate in candidates:
        marker = id(candidate)
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return unique


def parse_card(card) -> dict | None:
    card_text = clean_text(card.get_text(" ")) or ""
    lowered = card_text.lower()
    if "campoamor" not in lowered and "orihuela" not in lowered:
        return None
    if "€" not in card_text or "m²" not in card_text:
        return None

    title = None
    for heading in card.find_all(["h2", "h3"]):
        candidate = clean_text(heading.get_text(" "))
        if candidate and len(candidate) > 4:
            title = candidate
            break
    if not title:
        title_match = re.search(r"(Ref:\s*.+?)(?:Hace|Orihuela|\d[\d.]*\s*€)", card_text)
        title = clean_text(title_match.group(1)) if title_match else "Apartamento en Dehesa de Campoamor"
    if title and title.lower() == "orihuela":
        ref_title = re.search(r"(Ref:\s*.+?)(?:Hace\s+\d+|Hace\s+[A-Za-z]|\Z)", card_text)
        if ref_title:
            title = clean_text(ref_title.group(1)) or title

    price_raw = None
    price_match = re.search(r"\d{1,3}(?:\.\d{3})*\s*€", card_text)
    if price_match:
        price_raw = price_match.group(0)
    price = clean_price(price_raw)
    if price is None:
        return None

    bedrooms = None
    bathrooms = None
    area_m2 = None
    bedrooms_match = re.search(r"(\d+)\s*dorm", lowered)
    bathrooms_match = re.search(r"(\d+)\s*bañ", lowered)
    area_match = re.search(r"(\d+)\s*m²", lowered)
    if bedrooms_match:
        bedrooms = clean_int(bedrooms_match.group(1))
    if bathrooms_match:
        bathrooms = clean_int(bathrooms_match.group(1))
    if area_match:
        area_m2 = clean_int(area_match.group(1))

    link = card.find("a", href=True)
    url = urljoin(BASE_URL, link["href"]) if link else None
    if not url:
        ref_match = re.search(r"Ref:\s*([A-Za-z0-9_\-]+)", card_text)
        reference_slug = ref_match.group(1) if ref_match else abs(hash(card_text))
        url = f"{BASE_URL}/venta-de-apartamentos/dehesa-de-campoamor.htm#{reference_slug}"

    images = extract_images(card)
    if not images:
        return None
    reference_match = re.search(r"Ref:\s*([A-Za-z0-9_\-]+)", card_text)
    reference = reference_match.group(1) if reference_match else None

    listing = {
        "source": "milanuncios",
        "title": title,
        "price": price,
        "price_raw": price_raw,
        "bedrooms": bedrooms,
        "bedrooms_raw": f"{bedrooms} dorm." if bedrooms is not None else None,
        "bathrooms": bathrooms,
        "area_m2": area_m2,
        "area_raw": f"{area_m2} m2" if area_m2 is not None else None,
        "location": "Orihuela - Dehesa de Campoamor",
        "reference": reference,
        "distance_to_beach_m": None,
        "description": card_text,
        "image_url": images[0] if images else None,
        "image_urls": json.dumps(images, ensure_ascii=False),
        "property_type": "apartamento",
        "extra": extract_extras(card_text),
        "url": url,
    }
    listing["score"] = calculate_score(listing)
    return listing


def extract_extras(value: str) -> str | None:
    lowered = value.lower()
    extras = [
        word
        for word in (
            "balcón",
            "balcon",
            "piscina",
            "parking",
            "ascensor",
            "terraza",
            "garaje",
            "aire acondicionado",
            "trastero",
        )
        if word in lowered
    ]
    return " | ".join(sorted(set(extras))) if extras else None


def calculate_score(listing: dict) -> int:
    score = 0
    text = " ".join(
        str(listing.get(key) or "").lower()
        for key in ("title", "location", "extra", "description")
    )
    price = listing.get("price")
    area_m2 = listing.get("area_m2")
    bedrooms = listing.get("bedrooms")
    bathrooms = listing.get("bathrooms")

    if price is not None:
        if price <= 220000:
            score += 35
        elif price <= 300000:
            score += 25
        elif price <= 350000:
            score += 15
    if area_m2 is not None:
        if area_m2 >= 100:
            score += 25
        elif area_m2 >= 75:
            score += 18
        elif area_m2 >= 55:
            score += 10
    if bedrooms is not None:
        if bedrooms >= 3:
            score += 20
        elif bedrooms == 2:
            score += 12
    if bathrooms is not None and bathrooms >= 2:
        score += 8
    if "campoamor" in text:
        score += 15
    if "piscina" in text:
        score += 8
    if "terraza" in text or "balc" in text:
        score += 8
    if "parking" in text or "garaje" in text:
        score += 6
    return min(score, 100)


def parse_listings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    seen = set()
    for card in card_candidates(soup):
        listing = parse_card(card)
        if not listing or listing["url"] in seen:
            continue
        seen.add(listing["url"])
        listings.append(listing)
    return listings


def scrape_milanuncios(max_pages: int = 100) -> list[dict]:
    html = fetch_page(SEARCH_URL, page=1)
    if not html:
        print(
            "Milanuncios no se puede descargar sin captcha. "
            "Guarda la pagina como cached_pages/milanuncios_page_1.html para parsearla."
        )
        return []
    listings = parse_listings(html)
    print(f"Milanuncios viviendas extraidas: {len(listings)}")
    return listings


if __name__ == "__main__":
    init_db()
    listings = scrape_milanuncios()
    save_to_csv(listings, OUTPUT_CSV)
    summary = insert_properties(listings)
    print("=" * 80)
    print(f"Total procesadas: {summary['total']}")
    print(f"Nuevas: {summary['new']}")
    print(f"Ya existentes: {summary['existing']}")
