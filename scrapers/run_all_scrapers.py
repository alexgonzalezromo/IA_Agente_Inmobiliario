"""Orquesta los scrapers y actualiza las estimaciones del modelo de precios."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import DB_PATH, init_db, insert_properties  # noqa: E402
from ML.predict_houses_value import (  # noqa: E402
    DEFAULT_MODEL_PATH,
    predict_and_update,
    train_and_update,
)
from scrapers.fotocasa_scraper import scrape_fotocasa  # noqa: E402
from scrapers.idealista_scraper import scrape_idealista  # noqa: E402
from scrapers.milanuncios_scraper import scrape_milanuncios  # noqa: E402
from scrapers.moreno_schmidt_scraper import scrape_moreno_schmidt  # noqa: E402
from scrapers.united_realestate_scraper import scrape_united_realestate  # noqa: E402


Scraper = Callable[..., list[dict]]
SCRAPERS: dict[str, Scraper] = {
    "moreno_schmidt": scrape_moreno_schmidt,
    "fotocasa": scrape_fotocasa,
    "idealista": scrape_idealista,
    "milanuncios": scrape_milanuncios,
    "united_realestate": scrape_united_realestate,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta los scrapers y el pipeline de estimación."
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=tuple(SCRAPERS),
        default=list(SCRAPERS),
        help="Fuentes que se ejecutarán.",
    )
    parser.add_argument(
        "--retrain-threshold",
        type=int,
        default=50,
        help="Reentrena tras este número de viviendas válidas nuevas.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Límite de seguridad de páginas por fuente.",
    )
    parser.add_argument(
        "--retrain-days",
        type=int,
        default=7,
        help="Reentrena si el modelo tiene al menos esta antigüedad.",
    )
    parser.add_argument(
        "--skip-ml", action="store_true", help="No actualiza las estimaciones."
    )
    parser.add_argument(
        "--ml-only",
        action="store_true",
        help="No ejecuta scrapers; solo decide entre predecir o reentrenar.",
    )
    return parser.parse_args()


def run_scraper(name: str, scraper: Scraper) -> dict[str, Any]:
    started = perf_counter()
    print(f"\n[{name}] Iniciando")
    try:
        listings = scraper()
        if not isinstance(listings, list):
            raise TypeError("El scraper no devolvió una lista.")
        summary = insert_properties(listings)
        status = "ok" if listings else "warning"
        warning = None if listings else "El scraper no devolvió anuncios."
        result = {
            "source": name,
            "status": status,
            **summary,
            "seconds": round(perf_counter() - started, 2),
            "error": warning,
        }
    except Exception as error:
        result = {
            "source": name,
            "status": "error",
            "total": 0,
            "new": 0,
            "existing": 0,
            "seconds": round(perf_counter() - started, 2),
            "error": f"{type(error).__name__}: {error}",
        }

    print(
        f"[{name}] {result['status']} | total={result['total']} "
        f"nuevas={result['new']} existentes={result['existing']} "
        f"tiempo={result['seconds']}s"
    )
    if result["error"]:
        print(f"[{name}] {result['error']}")
    return result


def count_eligible_properties() -> int:
    with sqlite3.connect(DB_PATH) as connection:
        return int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM properties
                WHERE price > 0 AND area_m2 > 0 AND bedrooms > 0
                """
            ).fetchone()[0]
        )


def model_needs_retraining(
    model_path: Path, current_rows: int, row_threshold: int, day_threshold: int
) -> tuple[bool, str]:
    if not model_path.exists():
        return True, "no existe un modelo entrenado"

    artifact = joblib.load(model_path)
    trained_rows = int(artifact.get("training_rows", 0))
    added_rows = current_rows - trained_rows
    if added_rows >= row_threshold:
        return True, f"hay {added_rows} viviendas válidas nuevas"

    trained_at = datetime.fromisoformat(artifact["trained_at"])
    if trained_at.tzinfo is None:
        trained_at = trained_at.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - trained_at).total_seconds() / 86400
    if age_days >= day_threshold:
        return True, f"el modelo tiene {age_days:.1f} días"

    return False, f"modelo vigente; {max(added_rows, 0)} viviendas válidas nuevas"


def run_ml_pipeline(
    retrain_threshold: int, retrain_days: int
) -> dict[str, Any]:
    current_rows = count_eligible_properties()
    if current_rows < 10:
        return {
            "status": "skipped",
            "reason": f"solo hay {current_rows} viviendas válidas (mínimo 10)",
        }

    should_train, reason = model_needs_retraining(
        DEFAULT_MODEL_PATH, current_rows, retrain_threshold, retrain_days
    )
    print(f"\n[ML] {reason}")
    started = perf_counter()
    if should_train:
        result = train_and_update(
            Path(DB_PATH), DEFAULT_MODEL_PATH, near_threshold=0.05
        )
    else:
        result = predict_and_update(
            Path(DB_PATH), DEFAULT_MODEL_PATH, near_threshold=0.05
        )
    return {
        "status": "ok",
        "reason": reason,
        "seconds": round(perf_counter() - started, 2),
        **result,
    }


def print_summary(results: list[dict[str, Any]], ml_result: dict[str, Any] | None) -> None:
    print("\n" + "=" * 72)
    print("RESUMEN")
    for result in results:
        print(
            f"{result['source']:16} {result['status']:7} "
            f"total={result['total']:3} nuevas={result['new']:3} "
            f"existentes={result['existing']:3} {result['seconds']:7.2f}s"
        )
    if results:
        print(
            f"{'TOTAL':16} {'':7} "
            f"total={sum(r['total'] for r in results):3} "
            f"nuevas={sum(r['new'] for r in results):3} "
            f"existentes={sum(r['existing'] for r in results):3}"
        )
    if ml_result is not None:
        print(
            f"ML               {ml_result['status']:7} "
            f"modo={ml_result.get('mode', '-')} "
            f"filas={ml_result.get('rows', '-')} "
            f"{ml_result.get('seconds', 0):.2f}s"
        )
        print(f"ML: {ml_result['reason']}")
    print("=" * 72)


def main() -> int:
    args = parse_args()
    if args.retrain_threshold < 1 or args.retrain_days < 1 or args.max_pages < 1:
        raise SystemExit("Los umbrales y --max-pages deben ser positivos.")

    started_at = datetime.now().astimezone()
    print(f"Campoamor House Agent | inicio {started_at.isoformat(timespec='seconds')}")
    init_db()

    results = []
    if not args.ml_only:
        for source in args.sources:
            scraper = SCRAPERS[source]
            results.append(
                run_scraper(
                    source,
                    lambda scraper=scraper: scraper(max_pages=args.max_pages),
                )
            )

    ml_result = None
    if not args.skip_ml:
        try:
            ml_result = run_ml_pipeline(
                args.retrain_threshold, args.retrain_days
            )
        except Exception as error:
            ml_result = {
                "status": "error",
                "reason": f"{type(error).__name__}: {error}",
            }

    print_summary(results, ml_result)
    scraper_errors = any(result["status"] == "error" for result in results)
    ml_error = ml_result is not None and ml_result["status"] == "error"
    return 1 if scraper_errors or ml_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
