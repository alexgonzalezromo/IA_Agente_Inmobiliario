import os
import sqlite3
from datetime import datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "properties.db")


def get_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    return any(col["name"] == column_name for col in columns)


def add_column_if_not_exists(cursor, table_name: str, column_name: str, column_type: str):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def init_db():
    """
    Crea o actualiza la base de datos.
    Es compatible con la tabla antigua que ya tienes.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            price INTEGER,
            price_raw TEXT,
            bedrooms INTEGER,
            bedrooms_raw TEXT,
            area_m2 INTEGER,
            area_raw TEXT,
            extra TEXT,
            url TEXT UNIQUE,
            score INTEGER DEFAULT 0,
            first_seen_at TEXT,
            last_seen_at TEXT,
            is_favorite INTEGER DEFAULT 0,
            is_discarded INTEGER DEFAULT 0
        )
        """
    )

    # Nuevas columnas para hacer el agente más potente
    add_column_if_not_exists(cursor, "properties", "location", "TEXT")
    add_column_if_not_exists(cursor, "properties", "reference", "TEXT")
    add_column_if_not_exists(cursor, "properties", "bathrooms", "INTEGER")
    add_column_if_not_exists(cursor, "properties", "distance_to_beach_m", "INTEGER")
    add_column_if_not_exists(cursor, "properties", "description", "TEXT")
    add_column_if_not_exists(cursor, "properties", "image_url", "TEXT")
    add_column_if_not_exists(cursor, "properties", "image_urls", "TEXT")
    add_column_if_not_exists(cursor, "properties", "property_type", "TEXT")
    add_column_if_not_exists(cursor, "properties", "price_per_m2", "REAL")
    add_column_if_not_exists(cursor, "properties", "is_active", "INTEGER DEFAULT 1")
    add_column_if_not_exists(cursor, "properties", "last_price_change_at", "TEXT")
    add_column_if_not_exists(cursor, "properties", "previous_price", "INTEGER")
    add_column_if_not_exists(cursor, "properties", "estimated_price", "REAL")
    add_column_if_not_exists(cursor, "properties", "price_difference", "REAL")
    add_column_if_not_exists(cursor, "properties", "price_vs_estimate", "TEXT")
    add_column_if_not_exists(cursor, "properties", "estimated_at", "TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER,
            price INTEGER,
            seen_at TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(id)
        )
        """
    )

    conn.commit()
    conn.close()


def calculate_price_per_m2(price: int | None, area_m2: int | None) -> float | None:
    if not price or not area_m2:
        return None

    if area_m2 <= 0:
        return None

    return round(price / area_m2, 2)


def insert_price_history(cursor, property_id: int, price: int | None, seen_at: str):
    if price is None:
        return

    cursor.execute(
        """
        INSERT INTO price_history (
            property_id,
            price,
            seen_at
        )
        VALUES (?, ?, ?)
        """,
        (property_id, price, seen_at),
    )


def insert_property_if_new(property_data: dict) -> bool:
    """
    Inserta una vivienda si no existe.
    Si ya existe, actualiza datos y detecta cambios de precio.

    Devuelve True si es nueva.
    Devuelve False si ya existía.
    """
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().isoformat(timespec="seconds")

    url = property_data.get("url")

    if not url:
        conn.close()
        return False

    price = property_data.get("price")
    area_m2 = property_data.get("area_m2")
    price_per_m2 = calculate_price_per_m2(price, area_m2)

    cursor.execute(
        """
        SELECT id, price
        FROM properties
        WHERE url = ?
        """,
        (url,),
    )

    existing = cursor.fetchone()

    if existing:
        property_id = existing["id"]
        old_price = existing["price"]

        previous_price = None
        last_price_change_at = None

        if old_price is not None and price is not None and old_price != price:
            previous_price = old_price
            last_price_change_at = now
            insert_price_history(cursor, property_id, price, now)

        cursor.execute(
            """
            UPDATE properties
            SET
                source = ?,
                title = ?,
                price = ?,
                price_raw = ?,
                bedrooms = ?,
                bedrooms_raw = ?,
                bathrooms = ?,
                area_m2 = ?,
                area_raw = ?,
                location = ?,
                reference = ?,
                distance_to_beach_m = ?,
                description = ?,
                image_url = ?,
                image_urls = ?,
                property_type = ?,
                price_per_m2 = ?,
                extra = ?,
                score = ?,
                last_seen_at = ?,
                is_active = 1,
                previous_price = COALESCE(?, previous_price),
                last_price_change_at = COALESCE(?, last_price_change_at)
            WHERE url = ?
            """,
            (
                property_data.get("source"),
                property_data.get("title"),
                price,
                property_data.get("price_raw"),
                property_data.get("bedrooms"),
                property_data.get("bedrooms_raw"),
                property_data.get("bathrooms"),
                area_m2,
                property_data.get("area_raw"),
                property_data.get("location"),
                property_data.get("reference"),
                property_data.get("distance_to_beach_m"),
                property_data.get("description"),
                property_data.get("image_url"),
                property_data.get("image_urls"),
                property_data.get("property_type"),
                price_per_m2,
                property_data.get("extra"),
                property_data.get("score", 0),
                now,
                previous_price,
                last_price_change_at,
                url,
            ),
        )

        conn.commit()
        conn.close()
        return False

    cursor.execute(
        """
        INSERT INTO properties (
            source,
            title,
            price,
            price_raw,
            bedrooms,
            bedrooms_raw,
            bathrooms,
            area_m2,
            area_raw,
            location,
            reference,
            distance_to_beach_m,
            description,
            image_url,
            image_urls,
            property_type,
            price_per_m2,
            extra,
            url,
            score,
            first_seen_at,
            last_seen_at,
            is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            property_data.get("source"),
            property_data.get("title"),
            price,
            property_data.get("price_raw"),
            property_data.get("bedrooms"),
            property_data.get("bedrooms_raw"),
            property_data.get("bathrooms"),
            area_m2,
            property_data.get("area_raw"),
            property_data.get("location"),
            property_data.get("reference"),
            property_data.get("distance_to_beach_m"),
            property_data.get("description"),
            property_data.get("image_url"),
            property_data.get("image_urls"),
            property_data.get("property_type"),
            price_per_m2,
            property_data.get("extra"),
            url,
            property_data.get("score", 0),
            now,
            now,
            1,
        ),
    )

    property_id = cursor.lastrowid
    insert_price_history(cursor, property_id, price, now)

    conn.commit()
    conn.close()
    return True


def insert_properties(listings: list[dict]) -> dict:
    """
    Inserta una lista de viviendas.
    """
    new_count = 0
    existing_count = 0

    for listing in listings:
        is_new = insert_property_if_new(listing)

        if is_new:
            new_count += 1
        else:
            existing_count += 1

    return {
        "new": new_count,
        "existing": existing_count,
        "total": len(listings),
    }


def get_all_properties():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM properties
        ORDER BY score DESC, first_seen_at DESC
        """
    )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_new_properties():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM properties
        WHERE date(first_seen_at) = date('now')
        ORDER BY score DESC
        """
    )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_top_properties(min_score: int = 75):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM properties
        WHERE score >= ?
          AND is_discarded = 0
        ORDER BY score DESC, price ASC
        """,
        (min_score,),
    )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_price_drops():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM properties
        WHERE previous_price IS NOT NULL
          AND price IS NOT NULL
          AND price < previous_price
        ORDER BY last_price_change_at DESC
        """
    )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def mark_as_favorite(property_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE properties
        SET is_favorite = 1
        WHERE id = ?
        """,
        (property_id,),
    )

    conn.commit()
    conn.close()


def mark_as_discarded(property_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE properties
        SET is_discarded = 1
        WHERE id = ?
        """,
        (property_id,),
    )

    conn.commit()
    conn.close()
