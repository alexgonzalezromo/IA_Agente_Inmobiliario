import csv
import json
import os
import sys
import time
from random import randint
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURACIÓN DE RUTAS
# ============================================================

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)

from app.database import init_db, insert_properties  # noqa: E402


BASE_URL = "https://www.idealista.com"

SEARCH_URL = (
    "https://www.idealista.com/areas/venta-viviendas/"
    "con-precio-hasta_300000,chalets/"
    "?shape=%28%28iehfFlatC%7D%7E%40kD%7De%40yw%40wEc%7B%40lJ_UjMyC%60_BhmAgKxeA%29%29"
)

CACHE_DIR = os.path.join(PROJECT_ROOT, "cached_pages")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_CSV = "properties.csv"


# ============================================================
# DESCARGA / CARGA HTML LOCAL
# ============================================================

def fetch_page(url: str, page: int = 1) -> str | None:
    """
    Para Idealista:
    1. Intenta descargar con requests.
    2. Si da 403 o falla, carga el HTML local guardado manualmente.
    """

    local_path = os.path.join(CACHE_DIR, f"idealista_page_{page}.html")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)

        print(f"Status code requests: {response.status_code}")

        if response.status_code == 200:
            print("HTML descargado con requests.")
            return response.text

        print("Requests no ha funcionado. Cargando HTML local...")

    except requests.RequestException as e:
        print(f"Error en requests: {e}")
        print("Cargando HTML local...")

    if os.path.exists(local_path):
        print(f"Cargando HTML local desde: {local_path}")

        with open(local_path, "r", encoding="utf-8") as file:
            return file.read()

    print(f"No existe HTML local: {local_path}")
    return None


def save_page_locally(html: str, page: int) -> None:
    """
    Guarda el HTML usado por el scraper.
    Ojo: si estamos usando HTML local, lo vuelve a guardar igual.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    path = os.path.join(CACHE_DIR, f"idealista_page_{page}.html")

    with open(path, "w", encoding="utf-8") as file:
        file.write(html)

    print(f"HTML guardado en: {path}")


def get_url_for_page_number(page: int) -> str:
    """
    Construye la URL de cada página usando la búsqueda real de Idealista.
    """
    if page == 1:
        return SEARCH_URL

    base, query = SEARCH_URL.split("?")
    return f"{base}pagina-{page}.htm?{query}"


# ============================================================
# LIMPIEZA DE DATOS
# ============================================================

def clean_text(text: str | None) -> str | None:
    if not text:
        return None

    return " ".join(text.strip().split())


def clean_price(price_text: str | None) -> int | None:
    if not price_text:
        return None

    cleaned = (
        price_text
        .replace("€", "")
        .replace(".", "")
        .replace(",", "")
        .replace(" ", "")
        .strip()
    )

    try:
        return int(cleaned)
    except ValueError:
        return None


def clean_area(area_text: str | None) -> int | None:
    if not area_text:
        return None

    cleaned = (
        area_text
        .lower()
        .replace("m²", "")
        .replace("m2", "")
        .replace(".", "")
        .replace(",", "")
        .strip()
    )

    parts = cleaned.split()

    if not parts:
        return None

    try:
        return int(parts[0])
    except ValueError:
        return None


def clean_bedrooms(bedrooms_text: str | None) -> int | None:
    if not bedrooms_text:
        return None

    parts = bedrooms_text.split()

    if not parts:
        return None

    try:
        return int(parts[0])
    except ValueError:
        return None


def extract_image_url(card) -> str | None:
    urls = extract_image_urls(card)
    return urls[0] if urls else None


def extract_image_urls(card) -> list[str]:
    article = card.find_parent("article") or card
    urls = []
    for source in article.find_all("source"):
        srcset = source.get("srcset")
        if srcset and srcset.startswith("http"):
            urls.append(srcset.split(",")[0].strip().split()[0])

    for image in article.find_all("img"):
        for attr in ("src", "data-src"):
            src = image.get(attr)
            if src and src.startswith("http"):
                urls.append(src)

    return list(dict.fromkeys(urls))


# ============================================================
# SCORING
# ============================================================

def calculate_score(listing: dict) -> int:
    """
    Score inicial para valorar si una vivienda puede ser interesante.
    """
    score = 0

    title = (listing.get("title") or "").lower()
    price = listing.get("price")
    area_m2 = listing.get("area_m2")
    bedrooms = listing.get("bedrooms")
    extra = (listing.get("extra") or "").lower()

    text = f"{title} {extra}"

    # Precio
    if price is not None:
        if price <= 250000:
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

    # Zona
    if "campoamor" in text:
        score += 15

    if "mil palmeras" in text:
        score += 5

    # Características interesantes
    if "terraza" in text:
        score += 10

    if "garaje" in text or "parking" in text:
        score += 10

    if "piscina" in text:
        score += 5

    return min(score, 100)


# ============================================================
# PARSEO HTML
# ============================================================

def parse_listings(html: str) -> list[dict]:
    """
    Extrae los anuncios del HTML.
    Detecta habitaciones y metros por texto, no por posición.
    """
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.find_all("div", class_="item-info-container")

    print(f"Cards encontradas en HTML: {len(cards)}")

    listings = []

    for card in cards:
        try:
            title_tag = card.find("a", class_="item-link")
            price_tag = card.find("span", class_="item-price")
            detail_tags = card.find_all("span", class_="item-detail")

            title = clean_text(title_tag.get_text()) if title_tag else None

            if title_tag and title_tag.has_attr("href"):
                url = urljoin(BASE_URL, title_tag["href"])
            else:
                url = None

            price_raw = clean_text(price_tag.get_text()) if price_tag else None
            price = clean_price(price_raw)

            details = [
                clean_text(d.get_text())
                for d in detail_tags
                if clean_text(d.get_text())
            ]

            bedrooms_raw = None
            area_raw = None
            extra_parts = []

            for detail in details:
                detail_lower = detail.lower()

                if "hab" in detail_lower:
                    bedrooms_raw = detail

                elif "m²" in detail_lower or "m2" in detail_lower:
                    area_raw = detail

                else:
                    extra_parts.append(detail)

            bedrooms = clean_bedrooms(bedrooms_raw)
            area_m2 = clean_area(area_raw)
            extra = " | ".join(extra_parts) if extra_parts else None

            listing = {
                "source": "idealista",
                "title": title,
                "price": price,
                "price_raw": price_raw,
                "bedrooms": bedrooms,
                "bedrooms_raw": bedrooms_raw,
                "area_m2": area_m2,
                "area_raw": area_raw,
                "extra": extra,
                "image_url": extract_image_url(card),
                "image_urls": json.dumps(extract_image_urls(card), ensure_ascii=False),
                "url": url,
            }

            listing["score"] = calculate_score(listing)

            if title and url:
                listings.append(listing)

        except Exception as e:
            print(f"Error parseando anuncio: {e}")

    return listings


# ============================================================
# GUARDADO CSV
# ============================================================

def save_to_csv(listings: list[dict], filename: str) -> None:
    """
    Guarda los anuncios en CSV.
    El CSV es solo para revisar/debuggear.
    La base real es SQLite.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    path = os.path.join(DATA_DIR, filename)

    if not listings:
        print("No hay anuncios para guardar en CSV.")
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

def random_sleep() -> None:
    seconds = randint(5, 12)
    print(f"Esperando {seconds} segundos...")
    time.sleep(seconds)


def scrape_idealista(
    start_page: int = 1,
    end_page: int | None = None,
    max_pages: int = 100,
) -> list[dict]:
    all_listings = []
    seen_urls = set()
    final_page = end_page if end_page is not None else start_page + max_pages - 1

    for page in range(start_page, final_page + 1):
        url = get_url_for_page_number(page)

        print("=" * 80)
        print(f"Scrapeando página {page}")
        print(url)

        html = fetch_page(url, page)

        if not html:
            print(f"No se pudo obtener HTML para la página {page}")
            break

        save_page_locally(html, page)

        listings = parse_listings(html)

        print(f"Anuncios extraídos en página {page}: {len(listings)}")
        new_listings = [
            listing for listing in listings if listing.get("url") not in seen_urls
        ]
        if not new_listings:
            print("No hay anuncios nuevos. Fin de paginación.")
            break
        all_listings.extend(new_listings)
        seen_urls.update(listing["url"] for listing in new_listings)

        if page < final_page:
            random_sleep()

    return all_listings


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    init_db()

    listings = scrape_idealista(start_page=1)

    print("=" * 80)
    print(f"Total anuncios extraídos: {len(listings)}")

    for listing in listings[:5]:
        print("-" * 80)
        print(f"Título: {listing['title']}")
        print(f"Precio: {listing['price']}")
        print(f"m²: {listing['area_m2']}")
        print(f"Habitaciones: {listing['bedrooms']}")
        print(f"Score: {listing['score']}")
        print(f"URL: {listing['url']}")

    save_to_csv(listings, OUTPUT_CSV)

    summary = insert_properties(listings)

    print("=" * 80)
    print("Resumen SQLite")
    print(f"Total procesadas: {summary['total']}")
    print(f"Nuevas: {summary['new']}")
    print(f"Ya existentes: {summary['existing']}")
