"""Entrena un modelo de valoración y guarda las estimaciones en properties.db."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "properties.db"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "house_price_model.joblib"

NUMERIC_FEATURES = [
    "area_m2",
    "bedrooms",
    "bathrooms",
    "distance_to_beach_m",
    "has_pool",
    "has_garage",
    "has_terrace",
    "has_elevator",
    "has_sea_view",
]
CATEGORICAL_FEATURES = ["source", "location", "property_type"]
OUTPUT_COLUMNS = {
    "estimated_price": "REAL",
    "price_difference": "REAL",
    "price_vs_estimate": "TEXT",
    "estimated_at": "TEXT",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estima el valor de mercado de las viviendas de properties.db."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument(
        "--mode",
        choices=("train", "predict"),
        default="train",
        help="'train' reentrena y valida; 'predict' reutiliza el modelo guardado.",
    )
    parser.add_argument(
        "--near-threshold",
        type=float,
        default=0.05,
        help="Margen relativo para considerar el precio cercano a la estimación (0.05 = 5%%).",
    )
    return parser.parse_args()


def load_properties(connection: sqlite3.Connection) -> pd.DataFrame:
    query = """
        SELECT id, source, title, price, bedrooms, bathrooms, area_m2,
               distance_to_beach_m, location, property_type, extra, description
        FROM properties
        WHERE price IS NOT NULL AND price > 0
          AND area_m2 IS NOT NULL AND area_m2 > 0
          AND bedrooms IS NOT NULL AND bedrooms > 0
    """
    return pd.read_sql_query(query, connection)


def add_derived_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    text = (
        result[["title", "extra", "description"]]
        .fillna("")
        .agg(" ".join, axis=1)
        .str.lower()
    )
    keywords = {
        "has_pool": r"piscina|pool",
        "has_garage": r"garaje|parking|aparcamiento",
        "has_terrace": r"terraza|balc[oó]n",
        "has_elevator": r"ascensor",
        "has_sea_view": r"vista[s]? al mar|sea view|primera l[ií]nea",
    }
    for column, pattern in keywords.items():
        result[column] = text.str.contains(pattern, regex=True).astype(int)

    for column in CATEGORICAL_FEATURES:
        result[column] = result[column].fillna("desconocido").str.strip().str.lower()
    return result


def build_model() -> Pipeline:
    numeric_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ]
    )
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    preprocessing = ColumnTransformer(
        [
            ("numeric", numeric_pipeline, NUMERIC_FEATURES),
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
        ]
    )
    regressor = RandomForestRegressor(
        n_estimators=500,
        min_samples_leaf=2,
        max_features=0.8,
        random_state=42,
        n_jobs=-1,
    )
    return Pipeline([("preprocessing", preprocessing), ("regressor", regressor)])


def ensure_output_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row[1] for row in connection.execute("PRAGMA table_info(properties)").fetchall()
    }
    for name, sql_type in OUTPUT_COLUMNS.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE properties ADD COLUMN {name} {sql_type}")
    connection.commit()


def classify_price(
    offered_price: float, estimated_price: float, near_threshold: float
) -> str:
    relative_difference = (offered_price - estimated_price) / estimated_price
    if abs(relative_difference) <= near_threshold:
        return "near"
    return "above" if relative_difference > 0 else "below"


def write_predictions(
    connection: sqlite3.Connection,
    data: pd.DataFrame,
    predictions: np.ndarray,
    near_threshold: float,
    timestamp: str,
) -> None:
    predictions = np.maximum(predictions, 1.0)
    updates = []
    for property_id, price, prediction in zip(
        data["id"], data["price"].astype(float), predictions, strict=True
    ):
        estimate = round(float(prediction), 2)
        difference = round(float(price - estimate), 2)
        position = classify_price(float(price), estimate, near_threshold)
        updates.append((estimate, difference, position, timestamp, int(property_id)))

    connection.executemany(
        """
        UPDATE properties
        SET estimated_price = ?,
            price_difference = ?,
            price_vs_estimate = ?,
            estimated_at = ?
        WHERE id = ?
        """,
        updates,
    )
    connection.commit()


def train_and_update(
    db_path: Path, model_path: Path, near_threshold: float
) -> dict[str, float | int]:
    if not 0 <= near_threshold < 1:
        raise ValueError("--near-threshold debe estar entre 0 y 1.")
    if not db_path.exists():
        raise FileNotFoundError(f"No existe la base de datos: {db_path}")

    with sqlite3.connect(db_path) as connection:
        ensure_output_columns(connection)
        raw = load_properties(connection)

        if len(raw) < 10:
            raise ValueError(
                f"Solo hay {len(raw)} viviendas válidas; se necesitan al menos 10."
            )

        data = add_derived_features(raw)
        features = data[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
        target = data["price"].astype(float)
        folds = min(5, len(data))
        cross_validation = KFold(n_splits=folds, shuffle=True, random_state=42)

        model = build_model()
        predictions = cross_val_predict(
            model, features, target, cv=cross_validation, n_jobs=1
        )

        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_predictions(
            connection, data, predictions, near_threshold, timestamp
        )

    model.fit(features, target)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model": model,
        "features": NUMERIC_FEATURES + CATEGORICAL_FEATURES,
        "trained_at": timestamp,
        "training_rows": len(data),
        "near_threshold": near_threshold,
    }
    joblib.dump(artifact, model_path)

    return {
        "mode": "train",
        "rows": len(data),
        "mae_eur": round(float(mean_absolute_error(target, predictions)), 2),
        "mape_percent": round(
            float(mean_absolute_percentage_error(target, predictions) * 100), 2
        ),
        "r2": round(float(r2_score(target, predictions)), 3),
    }


def predict_and_update(
    db_path: Path, model_path: Path, near_threshold: float
) -> dict[str, str | int]:
    if not db_path.exists():
        raise FileNotFoundError(f"No existe la base de datos: {db_path}")
    if not model_path.exists():
        raise FileNotFoundError(
            f"No existe el modelo {model_path}. Ejecuta primero con --mode train."
        )

    artifact = joblib.load(model_path)
    model = artifact["model"]
    with sqlite3.connect(db_path) as connection:
        ensure_output_columns(connection)
        raw = load_properties(connection)
        if raw.empty:
            raise ValueError("No hay viviendas válidas para estimar.")
        data = add_derived_features(raw)
        features = data[artifact["features"]]
        predictions = model.predict(features)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_predictions(
            connection, data, predictions, near_threshold, timestamp
        )

    return {
        "mode": "predict",
        "rows": len(data),
        "model_trained_at": artifact["trained_at"],
    }


def main() -> None:
    args = parse_args()
    if args.mode == "train":
        metrics = train_and_update(
            args.db.resolve(), args.model_out.resolve(), args.near_threshold
        )
    else:
        metrics = predict_and_update(
            args.db.resolve(), args.model_out.resolve(), args.near_threshold
        )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
