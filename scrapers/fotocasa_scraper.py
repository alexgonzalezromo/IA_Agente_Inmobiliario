import csv
import json
import os
import re
import sys
import time
import certifi
from random import randint
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURACIÓN
# ============================================================

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)

from app.database import init_db, insert_properties  # noqa: E402


BASE_URL = "https://www.fotocasa.es"

SEARCH_URL = (
    "https://www.fotocasa.es/es/comprar/viviendas/orihuela/orihuela-costa/l"
    "?combinedLocationIds=724%2C19%2C3%2C368%2C718%2C3099%2C0%2C3512%2C1013"
    "%3B724%2C19%2C3%2C368%2C718%2C3099%2C0%2C3512%2C1008"
    "&maxPrice=350000"
    "&propertySubtypeIds=3%3B9%3B5%3B1%3B2%3B6%3B7%3B8%3B52%3B54"
)

CACHE_DIR = os.path.join(PROJECT_ROOT, "cached_pages")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

OUTPUT_CSV = "fotocasa_properties.csv"

# Para no meterle 69 detalles de golpe mientras probamos.
# Luego puedes subirlo a 50, 100 o quitar límite.
MAX_DETAIL_PAGES = None


# ============================================================
# REQUESTS
# ============================================================

def get_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }

def fetch_page(url: str) -> str | None:
    """
    Descarga una página.
    Si tarda demasiado, falla o hay problema SSL, devuelve None y el scraper sigue.
    """
    try:
        response = requests.get(
            url,
            headers=get_headers(),
            timeout=(8, 12),  # 8s conexión, 12s lectura
            verify=certifi.where(),
        )

        print(f"Status code requests: {response.status_code} -> {url}")

        if response.status_code == 200:
            return response.text

        print(f"No se pudo descargar: {url}")
        return None

    except requests.exceptions.Timeout:
        print(f"Timeout descargando: {url}")
        return None

    except requests.exceptions.SSLError as e:
        print(f"Error SSL descargando {url}: {e}")
        return None

    except requests.RequestException as e:
        print(f"Error en requests descargando {url}: {e}")
        return None

    except Exception as e:
        print(f"Error inesperado descargando {url}: {e}")
        return None

def save_html_locally(html: str, filename: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)

    path = os.path.join(CACHE_DIR, filename)

    with open(path, "w", encoding="utf-8") as file:
        file.write(html)

    print(f"HTML guardado en: {path}")


def clean_text(text: str | None) -> str | None:
    if not text:
        return None

    return " ".join(
        text.replace("\xa0", " ")
        .replace("·", " ")
        .replace("\n", " ")
        .replace("\t", " ")
        .strip()
        .split()
    )


def clean_price(text: str | None) -> int | None:
    if not text:
        return None

    cleaned = (
        text.replace("€", "")
        .replace(".", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("\xa0", "")
        .strip()
    )

    match = re.search(r"\d+", cleaned)

    if not match:
        return None

    try:
        return int(match.group())
    except ValueError:
        return None


def extract_price(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return None, None

    match = re.search(r"(\d{1,3}(?:\.\d{3})*)\s*€", text)

    if not match:
        return None, None

    price_raw = match.group(0)
    return clean_price(price_raw), price_raw


def extract_area(text: str | None) -> int | None:
    if not text:
        return None

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", text, flags=re.IGNORECASE)

    if not match:
        return None

    try:
        return int(float(match.group(1).replace(",", ".")))
    except ValueError:
        return None


def extract_bedrooms(text: str | None) -> int | None:
    if not text:
        return None

    patterns = [
        r"(\d+)\s*hab",
        r"(\d+)\s*dormitorios",
        r"(\d+)\s*habitaciones",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    return None


def extract_bathrooms(text: str | None) -> int | None:
    if not text:
        return None

    patterns = [
        r"(\d+)\s*baños",
        r"(\d+)\s*baño",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    return None


def guess_property_type(title: str | None) -> str | None:
    if not title:
        return None

    title_lower = title.lower()

    if "chalet" in title_lower:
        return "chalet"
    if "casa adosada" in title_lower:
        return "adosado"
    if "adosado" in title_lower or "adosada" in title_lower:
        return "adosado"
    if "casa" in title_lower:
        return "casa"
    if "apartamento" in title_lower:
        return "apartamento"
    if "piso" in title_lower:
        return "piso"
    if "estudio" in title_lower:
        return "estudio"
    if "dúplex" in title_lower or "duplex" in title_lower:
        return "duplex"

    return None


def extract_location(text: str | None) -> str | None:
    if not text:
        return None

    zones = [
        "Campoamor",
        "Orihuela Costa",
        "Cabo Roig",
        "La Zenia",
        "Punta Prima",
        "Mil Palmeras",
        "Aguamarina",
        "Playa Flamenca",
        "Villamartín",
        "Los Dolses",
    ]

    for zone in zones:
        if zone.lower() in text.lower():
            return zone

    return None


# ============================================================
# SCORING
# ============================================================

def calculate_score(listing: dict) -> int:
    score = 0

    title = (listing.get("title") or "").lower()
    location = (listing.get("location") or "").lower()
    extra = (listing.get("extra") or "").lower()
    description = (listing.get("description") or "").lower()

    text = f"{title} {location} {extra} {description}"

    price = listing.get("price")
    area_m2 = listing.get("area_m2")
    bedrooms = listing.get("bedrooms")
    bathrooms = listing.get("bathrooms")

    if price is not None:
        if price <= 220000:
            score += 35
        elif price <= 280000:
            score += 28
        elif price <= 350000:
            score += 18

    if area_m2 is not None:
        if area_m2 >= 110:
            score += 25
        elif area_m2 >= 85:
            score += 20
        elif area_m2 >= 60:
            score += 10

    if bedrooms is not None:
        if bedrooms >= 3:
            score += 20
        elif bedrooms == 2:
            score += 10
        elif bedrooms == 1:
            score += 2

    if bathrooms is not None:
        if bathrooms >= 2:
            score += 10
        elif bathrooms == 1:
            score += 5

    if "campoamor" in text:
        score += 20

    if "cabo roig" in text:
        score += 8

    if "terraza" in text:
        score += 10

    if "parking" in text or "garaje" in text:
        score += 10

    if "piscina" in text:
        score += 8

    if "obra nueva" in text or "reformad" in text:
        score += 7

    return min(score, 100)


# ============================================================
# EXTRACCIÓN DE URLS DEL LISTADO
# ============================================================

def normalize_fotocasa_url(href: str) -> str | None:
    if not href:
        return None

    if "/es/comprar/vivienda/" not in href:
        return None

    full_url = urljoin(BASE_URL, href)

    parsed = urlparse(full_url)

    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return clean_url


def extract_property_urls_from_listing(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    urls = set()

    # 1. Enlaces normales
    for link in soup.find_all("a", href=True):
        clean_url = normalize_fotocasa_url(link.get("href"))

        if clean_url:
            urls.add(clean_url)

    # 2. URLs que puedan venir incrustadas en JSON/scripts
    matches = re.findall(
        r'(/es/comprar/vivienda/[^"\']+?/d)',
        html,
        flags=re.IGNORECASE,
    )

    for match in matches:
        clean_url = normalize_fotocasa_url(match)

        if clean_url:
            urls.add(clean_url)

    urls = sorted(urls)

    return urls


def parse_listings_from_initial_props(html: str) -> list[dict]:
    """Extrae anuncios del JSON del listado sin solicitar cada detalle."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__initial_props__")
    if not script or not script.string:
        return []
    try:
        payload = json.loads(script.string)
        properties = payload["initialSearch"]["result"]["realEstates"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return []

    type_names = {
        "Apartment": "apartamento",
        "Flat": "piso",
        "SemidetachedHouse": "adosado",
        "House": "chalet",
        "Duplex": "duplex",
        "Studio": "estudio",
        "Penthouse": "ático",
    }
    listings = []
    for item in properties:
        relative_url = (item.get("detail") or {}).get("es-ES")
        if not relative_url:
            continue
        features = {
            feature.get("key"): feature.get("value")
            for feature in item.get("features", [])
            if feature.get("key")
        }
        subtype = item.get("buildingSubtype") or item.get("buildingType") or "Vivienda"
        property_type = type_names.get(subtype, subtype.lower())
        location = item.get("location") or (item.get("address") or {}).get("upperLevel")
        multimedia = item.get("multimedia") or []
        images = [
            media.get("src")
            for media in multimedia
            if media.get("type") == "image" and media.get("src")
        ]
        image = images[0] if images else None
        extras = [
            key
            for key in (
                "parking", "terrace", "community_pool", "private_pool",
                "elevator", "private_garden", "air_conditioner",
            )
            if key in features
        ]
        listing = {
            "source": "fotocasa",
            "title": f"{property_type.capitalize()} en venta en {location or 'Orihuela Costa'}",
            "price": item.get("rawPrice") or clean_price(item.get("price")),
            "price_raw": item.get("price"),
            "bedrooms": features.get("rooms"),
            "bedrooms_raw": f"{features['rooms']} habitaciones" if features.get("rooms") else None,
            "bathrooms": features.get("bathrooms"),
            "area_m2": features.get("surface"),
            "area_raw": f"{features['surface']} m²" if features.get("surface") else None,
            "location": location,
            "reference": str(item.get("id")) if item.get("id") else None,
            "distance_to_beach_m": None,
            "description": item.get("description"),
            "image_url": image,
            "image_urls": json.dumps(images, ensure_ascii=False),
            "property_type": property_type,
            "extra": " | ".join(extras) if extras else None,
            "url": normalize_fotocasa_url(relative_url),
        }
        listing["score"] = calculate_score(listing)
        if listing["url"] and listing["price"]:
            listings.append(listing)
    return listings


def get_listing_url_for_page(page: int) -> str:
    if page <= 1:
        return SEARCH_URL
    parsed = urlsplit(SEARCH_URL)
    path = parsed.path.rstrip("/")
    if not path.endswith("/l"):
        raise ValueError(f"Ruta de búsqueda Fotocasa no reconocida: {parsed.path}")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"{path}/{page}", parsed.query, parsed.fragment)
    )


# ============================================================
# PARSEO DETALLE
# ============================================================

def get_meta_content(soup: BeautifulSoup, property_name: str) -> str | None:
    tag = soup.find("meta", property=property_name)

    if tag and tag.get("content"):
        return clean_text(tag.get("content"))

    tag = soup.find("meta", attrs={"name": property_name})

    if tag and tag.get("content"):
        return clean_text(tag.get("content"))

    return None


def parse_json_ld(soup: BeautifulSoup) -> dict:
    """
    Intenta extraer datos de JSON-LD si Fotocasa los incluye.
    """
    data = {}

    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        raw = script.string

        if not raw:
            continue

        try:
            parsed = json.loads(raw)
        except Exception:
            continue

        items = parsed if isinstance(parsed, list) else [parsed]

        for item in items:
            if not isinstance(item, dict):
                continue

            if item.get("name") and not data.get("title"):
                data["title"] = clean_text(item.get("name"))

            if item.get("description") and not data.get("description"):
                data["description"] = clean_text(item.get("description"))

            if item.get("image") and not data.get("image_url"):
                image = item.get("image")

                if isinstance(image, list) and image:
                    data["image_url"] = image[0]
                    data["image_urls"] = image
                elif isinstance(image, str):
                    data["image_url"] = image
                    data["image_urls"] = [image]

            offers = item.get("offers")

            if isinstance(offers, dict):
                price = offers.get("price")

                if price and not data.get("price"):
                    try:
                        data["price"] = int(float(price))
                        data["price_raw"] = f"{data['price']} €"
                    except ValueError:
                        pass

    return data


def parse_detail_page(url: str, html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    full_text = clean_text(soup.get_text(" ")) or ""

    json_data = parse_json_ld(soup)

    title = json_data.get("title")

    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text()) if h1 else None

    if not title:
        title = get_meta_content(soup, "og:title")

    if not title:
        title_tag = soup.find("title")
        title = clean_text(title_tag.get_text()) if title_tag else None

    description = json_data.get("description")

    if not description:
        description = get_meta_content(soup, "og:description")

    if not description:
        description = get_meta_content(soup, "description")

    image_url = json_data.get("image_url")
    image_urls = json_data.get("image_urls") or []

    if not image_url:
        image_url = get_meta_content(soup, "og:image")
        if image_url:
            image_urls = [image_url]

    price = json_data.get("price")
    price_raw = json_data.get("price_raw")

    if price is None:
        price, price_raw = extract_price(full_text)

    area_m2 = extract_area(full_text)
    bedrooms = extract_bedrooms(full_text)
    bathrooms = extract_bathrooms(full_text)
    location = extract_location(full_text)

    property_type = guess_property_type(title)

    extra_parts = []

    for word in [
        "parking",
        "garaje",
        "terraza",
        "piscina",
        "jardín",
        "jardin",
        "ascensor",
        "obra nueva",
        "reformado",
        "amueblado",
    ]:
        if word in full_text.lower():
            extra_parts.append(word)

    extra = " | ".join(sorted(set(extra_parts))) if extra_parts else None

    listing = {
        "source": "fotocasa",
        "title": title,
        "price": price,
        "price_raw": price_raw,
        "bedrooms": bedrooms,
        "bedrooms_raw": f"{bedrooms} habitaciones" if bedrooms is not None else None,
        "bathrooms": bathrooms,
        "area_m2": area_m2,
        "area_raw": f"{area_m2} m²" if area_m2 is not None else None,
        "location": location,
        "reference": None,
        "distance_to_beach_m": None,
        "description": description,
        "image_url": image_url,
        "image_urls": json.dumps(image_urls, ensure_ascii=False),
        "property_type": property_type,
        "extra": extra,
        "url": url,
    }

    listing["score"] = calculate_score(listing)

    if not listing["url"] or not listing["title"] or listing["price"] is None:
        return None

    return listing


# ============================================================
# SCRAPER PRINCIPAL
# ============================================================

def scrape_fotocasa(max_pages: int = 100) -> list[dict]:
    print("=" * 80)
    print("Scrapeando Fotocasa")
    print(SEARCH_URL)

    listings_by_url = {}
    seen_urls = set()
    for page in range(1, max_pages + 1):
        page_url = get_listing_url_for_page(page)
        print(f"Listado Fotocasa página {page}: {page_url}")
        html = fetch_page(page_url)
        if not html:
            print("No se pudo descargar el listado. Fin de paginación.")
            break
        save_html_locally(html, f"fotocasa_page_{page}.html")
        page_urls = extract_property_urls_from_listing(html)
        new_urls = [url for url in page_urls if url not in seen_urls]
        print(f"URLs nuevas en página {page}: {len(new_urls)}")
        if not new_urls:
            print("No hay anuncios nuevos. Fin de paginación.")
            break
        for listing in parse_listings_from_initial_props(html):
            if listing["url"] in new_urls:
                listings_by_url[listing["url"]] = listing
        seen_urls.update(new_urls)
        if page < max_pages:
            time.sleep(randint(3, 7))

    listings = list(listings_by_url.values())
    print(f"URLs de viviendas encontradas: {len(seen_urls)}")
    print(f"Viviendas extraídas desde listados: {len(listings)}")
    return listings


# ============================================================
# GUARDADO CSV
# ============================================================

def save_to_csv(listings: list[dict], filename: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    path = os.path.join(DATA_DIR, filename)

    if not listings:
        print("No hay viviendas para guardar en CSV.")
        return

    fieldnames = listings[0].keys()

    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(listings)

    print(f"CSV guardado en: {path}")


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    init_db()

    listings = scrape_fotocasa()

    print("=" * 80)
    print(f"Total viviendas extraídas: {len(listings)}")

    for listing in listings[:15]:
        print("-" * 80)
        print(f"Título: {listing['title']}")
        print(f"Zona: {listing.get('location')}")
        print(f"Precio: {listing['price']}")
        print(f"m²: {listing['area_m2']}")
        print(f"Habitaciones: {listing['bedrooms']}")
        print(f"Baños: {listing.get('bathrooms')}")
        print(f"Tipo: {listing.get('property_type')}")
        print(f"Score: {listing['score']}")
        print(f"URL: {listing['url']}")

    save_to_csv(listings, OUTPUT_CSV)

    summary = insert_properties(listings)

    print("=" * 80)
    print("Resumen SQLite")
    print(f"Total procesadas: {summary['total']}")
    print(f"Nuevas: {summary['new']}")
    print(f"Ya existentes: {summary['existing']}")
