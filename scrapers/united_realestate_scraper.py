import csv
import json
import os
import re
import sys
import time
from random import randint
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)

from app.database import init_db, insert_properties  # noqa: E402


BASE_URL = "https://unitedrealestate.es"
SEARCH_URL = "https://unitedrealestate.es/propiedades/"
CACHE_DIR = os.path.join(PROJECT_ROOT, "cached_pages")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_CSV = "united_realestate_properties.csv"
RELEVANT_AREAS = (
    "campoamor",
    "dehesa de campoamor",
    "aguamarina",
    "cabo roig",
    "orihuela costa",
)


def get_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }


def fetch_page(url: str) -> str | None:
    try:
        response = requests.get(url, headers=get_headers(), timeout=20)
        print(f"United Real Estate {response.status_code}: {url}")
        if response.status_code == 200:
            return response.text
    except requests.RequestException as error:
        print(f"Error descargando {url}: {error}")
    return None


def save_html_locally(html: str, name: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    with open(path, "w", encoding="utf-8") as file:
        file.write(html)


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


def clean_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    return int(float(match.group().replace(",", ".")))


def normalize_type(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    replacements = {
        "apartamentos": "apartamento",
        "casas adosadas": "adosado",
        "dúplex": "duplex",
        "ático": "atico",
        "áticos": "atico",
        "villa de lujo": "villa",
        "villas": "villa",
    }
    return replacements.get(value, value)


def is_relevant(text: str) -> bool:
    lowered = text.lower()
    return any(area in lowered for area in RELEVANT_AREAS)


def extract_images(container: BeautifulSoup) -> list[str]:
    urls = []
    for image in container.select("img"):
        src = image.get("src") or image.get("data-src")
        if src and src.startswith("http") and "logo" not in src.lower():
            urls.append(src)
    return list(dict.fromkeys(urls))


def get_detail_url(card) -> str | None:
    link = card.find("a", href=True, string=lambda value: value and "Información" in value)
    if link:
        return urljoin(BASE_URL, link["href"])
    links = [
        urljoin(BASE_URL, link["href"])
        for link in card.find_all("a", href=True)
        if "/propiedad/" in link["href"]
    ]
    return links[0] if links else None


def parse_card(card) -> dict | None:
    title_tag = card.find(["h2", "h3"])
    title_raw = clean_text(title_tag.get_text(" ")) if title_tag else None
    if not title_raw or not is_relevant(title_raw):
        return None

    title_parts = [clean_text(part) for part in title_raw.split("·")]
    property_type = normalize_type(title_parts[0]) if title_parts else None
    location = title_parts[1] if len(title_parts) > 1 else None

    price_tag = card.find(string=re.compile(r"\d[\d.]*\s*€"))
    price_raw = clean_text(price_tag) if price_tag else None
    price = clean_price(price_raw)

    ref_match = re.search(r"Ref\.\s*([A-Za-z0-9\-]+)", card.get_text(" "))
    reference = ref_match.group(1) if ref_match else None

    metric_values = [
        clean_text(item.get_text(" "))
        for item in card.select(".listing-card-info-icon span, .property-info span, li, .detail")
        if clean_text(item.get_text(" "))
    ]
    card_text = clean_text(card.get_text(" ")) or ""
    numbers_after_ref = []
    if reference and reference in card_text:
        tail = card_text.split(reference, 1)[1]
        numbers_after_ref = re.findall(r"\d+(?:[.,]\d+)?", tail)

    bedrooms = clean_number(metric_values[0]) if metric_values else None
    bathrooms = clean_number(metric_values[1]) if len(metric_values) > 1 else None
    area_m2 = clean_number(metric_values[2]) if len(metric_values) > 2 else None
    if bedrooms is None and numbers_after_ref:
        bedrooms = clean_number(numbers_after_ref[0])
    if bathrooms is None and len(numbers_after_ref) > 1:
        bathrooms = clean_number(numbers_after_ref[1])
    if area_m2 is None and len(numbers_after_ref) > 2:
        area_m2 = clean_number(numbers_after_ref[2])

    images = extract_images(card)
    url = get_detail_url(card)
    if not url or price is None:
        return None

    listing = {
        "source": "united_realestate",
        "title": title_raw,
        "price": price,
        "price_raw": price_raw,
        "bedrooms": bedrooms,
        "bedrooms_raw": f"{bedrooms} dormitorios" if bedrooms is not None else None,
        "bathrooms": bathrooms,
        "area_m2": area_m2,
        "area_raw": f"{area_m2} m2" if area_m2 is not None else None,
        "location": location,
        "reference": reference,
        "distance_to_beach_m": None,
        "description": None,
        "image_url": images[0] if images else None,
        "image_urls": json.dumps(images, ensure_ascii=False),
        "property_type": property_type,
        "extra": None,
        "url": url,
    }
    listing["score"] = calculate_score(listing)
    return listing


def extract_labeled_value(text: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s+(.+?)(?=\s+(?:Referencia|Población|Zona|Dormitorios|Baños|Aseos|Orientación|Construidos|Parcela|Parking|IBI|Descripción)\s+|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else None


def enrich_from_detail(listing: dict) -> dict:
    html = fetch_page(listing["url"])
    if not html:
        return listing

    save_html_locally(html, f"united_realestate_detail_{listing['reference'] or listing['url'].rstrip('/').split('/')[-1]}.html")
    soup = BeautifulSoup(html, "html.parser")
    full_text = clean_text(soup.get_text(" ")) or ""

    description = extract_labeled_value(full_text, "Descripción")
    if description:
        listing["description"] = description

    reference = extract_labeled_value(full_text, "Referencia")
    if reference:
        listing["reference"] = reference

    location = extract_labeled_value(full_text, "Población")
    zone = extract_labeled_value(full_text, "Zona")
    if location and zone:
        listing["location"] = f"{location} - {zone}"
    elif location:
        listing["location"] = location

    detail_images = extract_images(soup)
    if detail_images:
        listing["image_url"] = detail_images[0]
        listing["image_urls"] = json.dumps(detail_images, ensure_ascii=False)

    parking = extract_labeled_value(full_text, "Parking")
    extras = []
    if parking and parking.lower().startswith("s"):
        extras.append("parking")
    for word in ("terraza", "piscina", "jardín", "jardin", "gimnasio", "jacuzzi"):
        if word in full_text.lower():
            extras.append(word)
    listing["extra"] = " | ".join(sorted(set(extras))) if extras else listing.get("extra")
    listing["score"] = calculate_score(listing)
    return listing


def parse_listings(html: str, fetch_details: bool = True) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    seen_urls = set()
    for card in soup.select(".property-listing"):
        listing = parse_card(card)
        if not listing or listing["url"] in seen_urls:
            continue
        if fetch_details:
            listing = enrich_from_detail(listing)
            time.sleep(randint(1, 3))
        listings.append(listing)
        seen_urls.add(listing["url"])
    return listings


def get_listing_url_for_page(page: int) -> str:
    if page <= 1:
        return SEARCH_URL
    return f"{SEARCH_URL}?{page}/"


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
        elif area_m2 >= 80:
            score += 18
        elif area_m2 >= 60:
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
    if "terraza" in text:
        score += 8
    if "piscina" in text:
        score += 8
    if "parking" in text or "garaje" in text:
        score += 6

    if "parking" in (listing.get("property_type") or "") and not bedrooms:
        score = 5

    return min(score, 100)


def scrape_united_realestate(max_pages: int = 100) -> list[dict]:
    all_listings = []
    seen_urls = set()
    for page in range(1, max_pages + 1):
        url = get_listing_url_for_page(page)
        html = fetch_page(url)
        if not html:
            break
        save_html_locally(html, f"united_realestate_page_{page}.html")
        listings = parse_listings(html)
        new_listings = [
            listing for listing in listings if listing["url"] not in seen_urls
        ]
        if not new_listings:
            print("United Real Estate: no hay anuncios nuevos. Fin de paginacion.")
            break
        all_listings.extend(new_listings)
        seen_urls.update(listing["url"] for listing in new_listings)
        print(f"United Real Estate pagina {page}: {len(new_listings)} viviendas")
        if page < max_pages:
            time.sleep(randint(2, 5))
    return all_listings


def save_to_csv(listings: list[dict], filename: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    if not listings:
        return
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(listings[0].keys()))
        writer.writeheader()
        writer.writerows(listings)


if __name__ == "__main__":
    init_db()
    listings = scrape_united_realestate()
    save_to_csv(listings, OUTPUT_CSV)
    summary = insert_properties(listings)
    print("=" * 80)
    print(f"Total procesadas: {summary['total']}")
    print(f"Nuevas: {summary['new']}")
    print(f"Ya existentes: {summary['existing']}")
