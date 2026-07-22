import csv
import json
import os
import re
import sys
import time
from random import randint
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURACIÓN DE RUTAS
# ============================================================

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)

from app.database import init_db, insert_properties  # noqa: E402


BASE_URL = "https://morenoschmidt.com"

SEARCH_URL = (
    "https://morenoschmidt.com/venta/"
    "?precio_hasta=300000&zona=campoamor"
)

CACHE_DIR = os.path.join(PROJECT_ROOT, "cached_pages")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_CSV = "moreno_schmidt_properties.csv"


# ============================================================
# DESCARGA HTML
# ============================================================

def get_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }


def fetch_page(url: str, page: int = 1) -> str | None:
    """
    Descarga la página de listado de Moreno Schmidt.
    """
    try:
        response = requests.get(url, headers=get_headers(), timeout=20)
        print(f"Status code requests: {response.status_code}")

        if response.status_code == 200:
            return response.text

        print(f"No se pudo descargar la página: {url}")
        return None

    except requests.RequestException as e:
        print(f"Error en requests: {e}")
        return None


def fetch_detail_page(url: str) -> str | None:
    """
    Descarga la ficha individual de una vivienda.
    """
    try:
        response = requests.get(url, headers=get_headers(), timeout=20)
        print(f"Detalle {response.status_code}: {url}")

        if response.status_code == 200:
            return response.text

        return None

    except requests.RequestException as e:
        print(f"Error descargando detalle {url}: {e}")
        return None


def save_page_locally(html: str, page: int) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)

    path = os.path.join(CACHE_DIR, f"moreno_schmidt_page_{page}.html")

    with open(path, "w", encoding="utf-8") as file:
        file.write(html)

    print(f"HTML guardado en: {path}")


# ============================================================
# LIMPIEZA
# ============================================================

def clean_text(text: str | None) -> str | None:
    if not text:
        return None

    return " ".join(text.replace("\xa0", " ").strip().split())


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


def extract_int_before(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)

    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_area(text: str) -> int | None:
    """
    Busca cosas tipo '90 m² Construidos'.
    """
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*m²\s*Construidos",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    value = match.group(1).replace(",", ".")

    try:
        return int(float(value))
    except ValueError:
        return None


def extract_distance_to_beach(text: str) -> int | None:
    """
    Busca cosas tipo:
    - '400 m a la playa'
    - '400 mts de la playa'
    - '400 a la playa'
    - 'Distancia a la playa 400'
    """
    patterns = [
        r"(\d+)\s*(?:mts|m)?\s*a\s*la\s*playa",
        r"(\d+)\s*(?:mts|m)?\s*de\s*la\s*playa",
        r"distancia\s*a\s*la\s*playa\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    return None


def extract_image_url_from_html(soup: BeautifulSoup) -> str | None:
    meta_image = soup.find("meta", property="og:image")
    if meta_image and meta_image.get("content"):
        return urljoin(BASE_URL, meta_image["content"])

    for selector in [
        ".pcs-carousel-slide img",
        ".woocommerce-product-gallery img",
        ".wp-post-image",
        "img",
    ]:
        image = soup.select_one(selector)
        if not image:
            continue
        for attr in ("src", "data-src", "data-lazy-src"):
            src = image.get(attr)
            if src and not src.startswith("data:"):
                return urljoin(BASE_URL, src)

    return None


def extract_image_url_from_block(block) -> str | None:
    urls = extract_image_urls_from_block(block)
    return urls[0] if urls else None


def extract_image_urls_from_block(block) -> list[str]:
    container = block.find_parent(class_="pcs-card") or block
    gallery = container.select_one("[data-pcs-gallery]")
    if gallery and gallery.get("data-pcs-gallery"):
        try:
            urls = json.loads(gallery["data-pcs-gallery"])
            return [
                urljoin(BASE_URL, url)
                for url in urls
                if isinstance(url, str) and not url.lower().endswith(".pdf")
            ]
        except json.JSONDecodeError:
            pass

    urls = []
    for image in container.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src"):
            src = image.get(attr)
            if src and not src.startswith("data:"):
                urls.append(urljoin(BASE_URL, src))

    return list(dict.fromkeys(urls))


def extract_image_url_from_image_tag(image) -> str | None:
    for attr in ("src", "data-src", "data-lazy-src"):
        src = image.get(attr)
        if src and not src.startswith("data:"):
            return urljoin(BASE_URL, src)

    return None
# ============================================================
# DETALLE DE FICHA
# ============================================================

def parse_detail_page(html: str) -> dict:
    """
    Extrae datos de la ficha individual.
    Primero intenta con pcs-meta.
    Si no funciona, usa regex sobre todo el texto de la ficha.
    """
    soup = BeautifulSoup(html, "html.parser")

    data = {
        "bedrooms": None,
        "bathrooms": None,
        "area_m2": None,
        "distance_to_beach_m": None,
        "description": None,
        "image_url": extract_image_url_from_html(soup),
    }

    # ========================================================
    # 1. Intento con bloques pcs-meta
    # ========================================================

    meta_items = soup.find_all(["span", "div"], class_="pcs-meta-item")

    for item in meta_items:
        value_tag = item.find(["span", "div"], class_="pcs-meta-value")
        label_tag = item.find(["span", "div"], class_="pcs-meta-label")

        value = clean_text(value_tag.get_text()) if value_tag else None
        label = clean_text(label_tag.get_text()) if label_tag else None

        if not value or not label:
            continue

        label_lower = label.lower()

        try:
            numeric_value = int(
                value.replace(".", "")
                .replace(",", "")
                .replace("m", "")
                .replace("M", "")
                .strip()
            )
        except ValueError:
            numeric_value = None

        if "habitaciones" in label_lower:
            data["bedrooms"] = numeric_value

        elif "baños" in label_lower or "banos" in label_lower:
            data["bathrooms"] = numeric_value

        elif "m²" in label_lower or "m2" in label_lower or "construidos" in label_lower:
            data["area_m2"] = numeric_value

        elif "playa" in label_lower:
            data["distance_to_beach_m"] = numeric_value

    # ========================================================
    # 2. Fallback por texto completo
    # ========================================================

    full_text = clean_text(soup.get_text(" ")) or ""

    if data["bedrooms"] is None:
        data["bedrooms"] = extract_int_before(
            r"(\d+)\s*Habitaciones",
            full_text,
        )

    if data["bathrooms"] is None:
        data["bathrooms"] = extract_int_before(
            r"(\d+)\s*(?:Baños|Baths)",
            full_text,
        )

    if data["area_m2"] is None:
        data["area_m2"] = extract_area(full_text)

    if data["distance_to_beach_m"] is None:
        data["distance_to_beach_m"] = extract_distance_to_beach(full_text)

    # ========================================================
    # 3. Descripción
    # ========================================================

    description = None

    description_title = soup.find(
        string=lambda text: text and "Descripción" in text
    )

    if description_title:
        parent = description_title.parent

        if parent:
            next_texts = []

            for sibling in parent.find_all_next(["p", "div"], limit=8):
                text = clean_text(sibling.get_text(" "))

                if not text:
                    continue

                if "Características" in text:
                    break

                if len(text) > 80:
                    next_texts.append(text)

            if next_texts:
                description = " ".join(next_texts)

    if not description:
        candidates = soup.find_all(["p", "div"])

        best_description = None

        for candidate in candidates:
            text = clean_text(candidate.get_text(" "))

            if not text:
                continue

            if 120 <= len(text) <= 2500:
                if not best_description or len(text) > len(best_description):
                    best_description = text

        description = best_description

    data["description"] = description

    return data


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
    distance = listing.get("distance_to_beach_m")

    # Precio
    if price is not None:
        if price <= 220000:
            score += 35
        elif price <= 250000:
            score += 30
        elif price <= 300000:
            score += 20

    # Superficie
    if area_m2 is not None:
        if area_m2 >= 100:
            score += 25
        elif area_m2 >= 80:
            score += 20
        elif area_m2 >= 60:
            score += 10

    # Habitaciones
    if bedrooms is not None:
        if bedrooms >= 3:
            score += 20
        elif bedrooms == 2:
            score += 10
        elif bedrooms == 1:
            score += 2

    # Baños
    if bathrooms is not None:
        if bathrooms >= 2:
            score += 10
        elif bathrooms == 1:
            score += 5

    # Zona
    if "campoamor" in text:
        score += 15

    # Extras
    if "terraza" in text:
        score += 10

    if "parking" in text or "garaje" in text:
        score += 10

    if "piscina" in text:
        score += 8

    # Playa
    if distance is not None:
        if distance <= 400:
            score += 15
        elif distance <= 700:
            score += 10
        elif distance <= 1000:
            score += 5

    # Penalización para garajes sueltos
    if "garaje" in title and bedrooms is None:
        score = 5

    return min(score, 100)


# ============================================================
# PARSEO LISTADO
# ============================================================

def find_property_links(soup: BeautifulSoup) -> list:
    """
    Encuentra los enlaces principales de viviendas.
    """
    links = soup.find_all("a", href=True)

    property_links = []
    seen_urls = set()

    for link in links:
        title = clean_text(link.get_text())
        href = link.get("href", "")

        if not title or not href:
            continue

        title_lower = title.lower()

        is_property_title = title_lower.startswith("venta ")
        has_property_word = any(
            word in title_lower
            for word in [
                "piso",
                "apartamento",
                "duplex",
                "dúplex",
                "chalet",
                "estudio",
                "garaje",
            ]
        )

        if is_property_title and has_property_word:
            full_url = urljoin(BASE_URL, href)

            if full_url not in seen_urls:
                seen_urls.add(full_url)
                property_links.append(link)

    return property_links


def find_listing_container(link):
    """
    Encuentra el bloque pequeño del anuncio dentro del listado.
    """
    current = link

    for _ in range(8):
        if not current.parent:
            break

        current = current.parent
        text = clean_text(current.get_text(" "))

        if not text:
            continue

        has_price = "€" in text
        has_ref = "Ref:" in text or "REF:" in text or "ref:" in text

        title_links_inside = []

        for a in current.find_all("a", href=True):
            a_text = clean_text(a.get_text()) or ""
            if a_text.lower().startswith("venta "):
                title_links_inside.append(a)

        if has_price and has_ref and len(title_links_inside) <= 2:
            return current

    return link.parent


def parse_listings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    property_links = find_property_links(soup)

    print(f"Enlaces de viviendas encontrados: {len(property_links)}")

    listings = []
    seen_urls = set()

    for link in property_links:
        try:
            title = clean_text(link.get_text())
            url = urljoin(BASE_URL, link.get("href"))

            if url in seen_urls:
                continue

            seen_urls.add(url)

            block = find_listing_container(link)
            card_block = block.find_parent(class_="pcs-card") or block
            block_text = clean_text(block.get_text(" "))

            if not block_text:
                continue

            location = None
            location_match = re.search(
                r"\b(CAMPOAMOR|AGUAMARINA|MIL PALMERAS|LA ZENIA|PUNTA PRIMA|CABO ROIG|LA REGIA|REAL CLUB)\b",
                block_text,
                flags=re.IGNORECASE,
            )

            if location_match:
                location = location_match.group(1).upper()

            ref = None
            ref_match = re.search(
                r"Ref:\s*([A-Za-z0-9\-]+)",
                block_text,
                flags=re.IGNORECASE,
            )

            if ref_match:
                ref = ref_match.group(1)

            price_raw = None
            price_match = re.search(r"(\d{1,3}(?:\.\d{3})*)\s*€", block_text)

            if price_match:
                price_raw = price_match.group(0)

            price = clean_price(price_raw)

            detail_html = fetch_detail_page(url)
            detail_data = parse_detail_page(detail_html) if detail_html else {}

            time.sleep(randint(2, 5))

            bedrooms = detail_data.get("bedrooms") or extract_int_before(
                r"(\d+)\s*Habitaciones",
                block_text,
            )

            bathrooms = detail_data.get("bathrooms") or extract_int_before(
                r"(\d+)\s*Baños",
                block_text,
            )

            area_m2 = detail_data.get("area_m2") or extract_area(block_text)

            distance_to_beach_m = detail_data.get("distance_to_beach_m") or extract_distance_to_beach(
                block_text,
            )

            description = detail_data.get("description")
            image_url = detail_data.get("image_url") or extract_image_url_from_block(card_block)
            image_urls = extract_image_urls_from_block(card_block)
            if not image_urls and image_url:
                image_urls = [image_url]

            extra = block_text

            listing = {
                "source": "moreno_schmidt",
                "title": title,
                "price": price,
                "price_raw": price_raw,
                "bedrooms": bedrooms,
                "bedrooms_raw": f"{bedrooms} Habitaciones" if bedrooms is not None else None,
                "area_m2": area_m2,
                "area_raw": f"{area_m2} m²" if area_m2 is not None else None,
                "extra": extra,
                "url": url,
                "location": location,
                "reference": ref,
                "bathrooms": bathrooms,
                "distance_to_beach_m": distance_to_beach_m,
                "description": description,
                "image_url": image_url,
                "image_urls": json.dumps(image_urls, ensure_ascii=False),
            }

            listing["score"] = calculate_score(listing)

            if title and url:
                listings.append(listing)

        except Exception as e:
            print(f"Error parseando vivienda: {e}")

    return listings


# ============================================================
# PAGINACIÓN
# ============================================================

def get_listing_url_for_page(page: int) -> str:
    if page <= 1:
        return SEARCH_URL
    parsed = urlsplit(SEARCH_URL)
    base_path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{base_path}/page/{page}/",
            parsed.query,
            parsed.fragment,
        )
    )


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
# SCRAPER PRINCIPAL
# ============================================================

def scrape_moreno_schmidt(max_pages: int = 100) -> list[dict]:
    print("=" * 80)
    print("Scrapeando Moreno Schmidt")
    print(SEARCH_URL)

    all_listings = []
    seen_urls = set()
    for page in range(1, max_pages + 1):
        page_url = get_listing_url_for_page(page)
        print(f"Listado Moreno Schmidt página {page}: {page_url}")
        html = fetch_page(page_url, page=page)
        if not html:
            print("No se pudo descargar el listado. Fin de paginación.")
            break
        save_page_locally(html, page=page)

        soup = BeautifulSoup(html, "html.parser")
        page_urls = {
            urljoin(BASE_URL, link.get("href"))
            for link in find_property_links(soup)
            if link.get("href")
        }
        new_urls = page_urls - seen_urls
        if not new_urls:
            print("No hay anuncios nuevos. Fin de paginación.")
            break

        listings = [
            listing
            for listing in parse_listings(html)
            if listing.get("url") in new_urls
        ]
        all_listings.extend(listings)
        seen_urls.update(new_urls)
        print(f"Viviendas nuevas en página {page}: {len(listings)}")
        if page < max_pages:
            time.sleep(randint(3, 7))

    print(f"Viviendas extraídas: {len(all_listings)}")
    return all_listings


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    init_db()

    listings = scrape_moreno_schmidt()

    print("=" * 80)
    print(f"Total viviendas extraídas: {len(listings)}")

    for listing in listings[:10]:
        print("-" * 80)
        print(f"Título: {listing['title']}")
        print(f"Zona: {listing.get('location')}")
        print(f"Ref: {listing.get('reference')}")
        print(f"Precio: {listing['price']}")
        print(f"m²: {listing['area_m2']}")
        print(f"Habitaciones: {listing['bedrooms']}")
        print(f"Baños: {listing.get('bathrooms')}")
        print(f"Distancia playa: {listing.get('distance_to_beach_m')} m")
        print(f"Score: {listing['score']}")
        print(f"URL: {listing['url']}")

    save_to_csv(listings, OUTPUT_CSV)

    summary = insert_properties(listings)

    print("=" * 80)
    print("Resumen SQLite")
    print(f"Total procesadas: {summary['total']}")
    print(f"Nuevas: {summary['new']}")
    print(f"Ya existentes: {summary['existing']}")
