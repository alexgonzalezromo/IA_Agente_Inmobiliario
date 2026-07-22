"""Genera un portal HTML estatico con las viviendas seleccionadas."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import DB_PATH, init_db  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / "portal" / "index.html"


def money(value: int | float | None) -> str:
    if value is None:
        return "Precio no disponible"
    return f"{int(value):,} EUR".replace(",", ".")


def compact_money(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{round(float(value) / 1000):.0f}k EUR"


def number(value: int | float | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{int(value):,}{suffix}".replace(",", ".")


def text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    return html.escape(str(value))


def load_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def image_list(row: sqlite3.Row) -> list[str]:
    urls = load_json_list(row["image_urls"] if "image_urls" in row.keys() else None)
    if row["image_url"]:
        urls.insert(0, row["image_url"])
    return list(dict.fromkeys(url for url in urls if url))


def row_get(row: sqlite3.Row, key: str, fallback: object = None) -> object:
    if key not in row.keys():
        return fallback
    value = row[key]
    return fallback if value is None else value


def property_score(row: sqlite3.Row) -> int:
    return int(row_get(row, "score", 0) or 0)


def short_summary(row: sqlite3.Row, limit: int = 260) -> str:
    description = str(row_get(row, "description", "") or "").strip()
    if not description:
        return "Vivienda que encaja con los filtros principales de la busqueda."
    if len(description) <= limit:
        return description
    return description[: limit - 1].rsplit(" ", 1)[0] + "."


def combined_text(row: sqlite3.Row) -> str:
    pieces = [
        row_get(row, "title", ""),
        row_get(row, "extra", ""),
        row_get(row, "description", ""),
    ]
    return " ".join(str(piece or "") for piece in pieces).lower()


def automatic_strengths(row: sqlite3.Row) -> list[str]:
    content = combined_text(row)
    strengths: list[str] = []
    price_difference = row_get(row, "price_difference")
    if price_difference is not None and float(price_difference) < 0:
        strengths.append("Sale por debajo de la estimacion del modelo de precio.")
    if row_get(row, "bedrooms") and int(row_get(row, "bedrooms")) >= 2:
        strengths.append("Tiene al menos dos dormitorios.")
    if row_get(row, "area_m2") and int(row_get(row, "area_m2")) >= 70:
        strengths.append("Tiene una superficie interesante para la zona.")
    if row_get(row, "distance_to_beach_m") and int(row_get(row, "distance_to_beach_m")) <= 700:
        strengths.append("Esta cerca de la playa segun los datos disponibles.")
    if any(word in content for word in ("terraza", "balcon", "jardin", "piscina", "garaje", "parking")):
        strengths.append("Menciona extras valorables como terraza, piscina, jardin o parking.")
    if not strengths:
        strengths.append("Encaja con los filtros principales de precio, dormitorios y metros.")
    return strengths[:4]


def automatic_risks(row: sqlite3.Row) -> list[str]:
    risks: list[str] = []
    price_difference = row_get(row, "price_difference")
    if price_difference is not None and float(price_difference) > 0:
        risks.append("El precio esta por encima de la estimacion del modelo.")
    if not row_get(row, "bathrooms"):
        risks.append("No se ha podido confirmar el numero de banos.")
    if not row_get(row, "area_m2"):
        risks.append("Falta superficie fiable para comparar bien el precio.")
    if not image_list(row):
        risks.append("No hay fotos guardadas para revisar el estado visual.")
    if not row_get(row, "estimated_price"):
        risks.append("Todavia no tiene estimacion ML calculada.")
    if not risks:
        risks.append("Sin riesgos destacados en los datos disponibles.")
    return risks[:4]


def price_position_label(row: sqlite3.Row) -> str:
    labels = {
        "below": "por debajo del modelo",
        "near": "cerca del modelo",
        "above": "por encima del modelo",
    }
    return labels.get(str(row_get(row, "price_vs_estimate", "") or ""), "analizado")


def detail_path(row: sqlite3.Row) -> str:
    return f"properties/{int(row['id'])}.html"


def fetch_portal_properties(db_path: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT *
            FROM properties
            WHERE is_discarded = 0
              AND COALESCE(is_active, 1) = 1
              AND price >= 80000
              AND price <= 350000
              AND bedrooms >= 2
              AND area_m2 >= 50
              AND image_url IS NOT NULL
              AND image_url != ''
            ORDER BY score DESC, price_difference ASC, price ASC
            """
        ).fetchall()


def render_card(row: sqlite3.Row) -> str:
    image_url = row["image_url"] or ""
    image = (
        f'<img src="{text(image_url)}" alt="{text(row["title"], "Vivienda")}">'
        if image_url
        else '<div class="image-placeholder">Sin foto</div>'
    )
    strengths = automatic_strengths(row)
    risks = automatic_risks(row)
    source = row["source"] or "desconocido"
    property_type = row["property_type"] or "vivienda"
    tags = [property_type, source, price_position_label(row)]
    tag_html = "".join(f"<span>{text(tag)}</span>" for tag in tags if tag)
    strength_html = "".join(f"<li>{text(item)}</li>" for item in strengths)
    risk_html = "".join(f"<li>{text(item)}</li>" for item in risks)
    estimate = (
        f'<span class="estimate">Estimacion ML: {money(row["estimated_price"])}</span>'
        if row["estimated_price"]
        else ""
    )
    score = property_score(row)
    price_difference = row["price_difference"]
    deal_class = "near"
    deal_text = "Precio equilibrado"
    difference_label = ""
    if price_difference is not None:
        if price_difference > 0:
            difference_label = f'<span class="market above">+{money(price_difference)} vs ML</span>'
            deal_class = "above"
            deal_text = "Por encima del modelo"
        elif price_difference < 0:
            difference_label = f'<span class="market below">{money(price_difference)} vs ML</span>'
            deal_class = "below"
            deal_text = "Debajo del modelo"
        else:
            difference_label = '<span class="market near">En precio ML</span>'
    title = text(row["title"], "Vivienda en Dehesa de Campoamor")
    location = text(row["location"], "Dehesa de Campoamor")
    summary = text(short_summary(row))
    price = row["price"] or 0
    data_title = text(f"{row['title']} {row['location']} {source}".lower())

    return f"""
    <article class="listing" data-source="{text(source)}" data-score="{score}" data-price="{price}" data-delta="{price_difference or 0}" data-title="{data_title}">
      <a class="media" href="{detail_path(row)}">
        {image}
        <span class="badge">{score}/100</span>
        <span class="source-pill">{text(row["source"], "fuente")}</span>
      </a>
      <div class="content">
        <div class="card-kicker">
          <span class="deal {deal_class}">{deal_text}</span>
          <span>{text(price_position_label(row), "analizado")}</span>
        </div>
        <div class="price-row">
          <strong>{money(row["price"])}</strong>
          <div class="price-meta">{estimate}{difference_label}</div>
        </div>
        <h2>{title}</h2>
        <p class="location">{location}</p>
        <div class="metrics">
          <div><span>{number(row["bedrooms"])}</span><small>hab.</small></div>
          <div><span>{number(row["bathrooms"])}</span><small>banos</small></div>
          <div><span>{number(row["area_m2"], " m2")}</span><small>superficie</small></div>
          <div><span>{number(row["price_per_m2"], " EUR")}</span><small>por m2</small></div>
        </div>
        <div class="tags">{tag_html}</div>
        <p class="summary">{summary}</p>
        <div class="analysis">
          <section>
            <h3>Por que encaja</h3>
            <ul>{strength_html or "<li>Encaja con los filtros principales.</li>"}</ul>
          </section>
          <section>
            <h3>Riesgos</h3>
            <ul>{risk_html or "<li>Sin riesgos destacados en los datos disponibles.</li>"}</ul>
          </section>
        </div>
        <div class="actions">
          <a class="ghost-link" href="{detail_path(row)}">Ver ficha y fotos</a>
          <a class="cta" href="{text(row["url"], "#")}" target="_blank" rel="noreferrer">Ver anuncio original</a>
          <button class="ghost" type="button" data-copy="{text(row["url"], "#")}">Copiar enlace</button>
        </div>
      </div>
    </article>
    """


def render_page(rows: list[sqlite3.Row]) -> str:
    cards = "\n".join(render_card(row) for row in rows)
    average_score = round(
        sum(property_score(row) for row in rows) / len(rows)
    ) if rows else 0
    average_price = round(sum((row["price"] or 0) for row in rows) / len(rows)) if rows else 0
    below_model = sum(1 for row in rows if (row["price_difference"] or 0) < 0)
    source_names = sorted({row["source"] for row in rows if row["source"]})
    source_buttons = '<button class="filter active" type="button" data-source="all">Todos</button>'
    source_buttons += "".join(
        f'<button class="filter" type="button" data-source="{text(source)}">{text(source)}</button>'
        for source in source_names
    )
    hero_images = [row["image_url"] for row in rows if row["image_url"]][:5]
    hero_tiles = "".join(
        f'<figure><img src="{text(image)}" alt="Vivienda seleccionada {index}"></figure>'
        for index, image in enumerate(hero_images, start=1)
    )
    hero_tiles = hero_tiles or '<figure class="empty-photo">Sin fotos disponibles</figure>'
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Casas seleccionadas en Dehesa de Campoamor</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #667085;
      --soft: #eef3f1;
      --line: #d7dfdc;
      --accent: #0f766e;
      --accent-dark: #0a4f49;
      --gold: #c18b2c;
      --good: #137a3f;
      --bad: #a33b2f;
      --warm: #fbf6ec;
      --panel: #ffffff;
      --shadow: 0 18px 44px rgba(17, 24, 39, .11);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: #f4f7f6;
    }}
    a, button, input, select {{ font: inherit; }}
    header {{
      background:
        radial-gradient(circle at 10% 0%, rgba(193, 139, 44, .34), transparent 34%),
        linear-gradient(135deg, #092f34 0%, #0f766e 52%, #18212d 100%);
      color: #fff;
      overflow: hidden;
    }}
    .topbar, .hero, main {{
      max-width: 1180px;
      margin: 0 auto;
    }}
    .topbar {{
      padding: 18px 20px 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand strong {{ display: block; font-size: 23px; letter-spacing: 0; }}
    .brand span {{ color: rgba(255,255,255,.76); font-size: 14px; }}
    .count {{
      border: 1px solid rgba(255,255,255,.24);
      padding: 10px 13px;
      border-radius: 6px;
      background: rgba(255,255,255,.12);
      font-weight: 700;
      white-space: nowrap;
    }}
    .hero {{
      padding: 34px 20px 42px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 470px;
      gap: 34px;
      align-items: center;
    }}
    .hero h1 {{
      max-width: 720px;
      font-size: 46px;
      line-height: 1.02;
      margin: 0 0 16px;
      letter-spacing: 0;
    }}
    .hero p {{
      margin: 0;
      color: rgba(255,255,255,.78);
      max-width: 680px;
      line-height: 1.5;
      font-size: 17px;
    }}
    .hero-actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 22px; }}
    .hero-actions a {{
      color: #fff;
      text-decoration: none;
      border-radius: 8px;
      padding: 11px 14px;
      font-weight: 800;
      background: rgba(255,255,255,.14);
      border: 1px solid rgba(255,255,255,.22);
    }}
    .hero-actions a.primary {{ background: #fff; color: #0b4f49; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 24px;
    }}
    .stat {{
      border: 1px solid rgba(255,255,255,.22);
      border-radius: 8px;
      padding: 14px;
      background: rgba(255,255,255,.1);
      backdrop-filter: blur(12px);
    }}
    .stat strong {{ display: block; font-size: 23px; letter-spacing: 0; }}
    .stat span {{ color: rgba(255,255,255,.72); font-size: 13px; }}
    .photo-wall {{
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      grid-template-rows: 190px 150px;
      gap: 10px;
      min-height: 350px;
    }}
    .photo-wall figure {{
      margin: 0;
      border-radius: 8px;
      overflow: hidden;
      background: rgba(255,255,255,.12);
      box-shadow: 0 20px 50px rgba(0,0,0,.22);
    }}
    .photo-wall figure:first-child {{ grid-row: span 2; }}
    .photo-wall figure:nth-child(n+4) {{ display: none; }}
    .photo-wall img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    main {{
      padding: 24px 20px 58px;
    }}
    .control-panel {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto auto;
      gap: 12px;
      align-items: center;
      margin: -42px 0 22px;
      padding: 14px;
      background: rgba(255,255,255,.94);
      border: 1px solid rgba(215,223,220,.92);
      border-radius: 8px;
      box-shadow: var(--shadow);
      position: sticky;
      top: 12px;
      z-index: 5;
      backdrop-filter: blur(14px);
    }}
    .search input, .sort select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      background: #fff;
      color: var(--ink);
      outline: none;
    }}
    .search input:focus, .sort select:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15,118,110,.12); }}
    .source-filters {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .filter {{
      border: 1px solid var(--line);
      background: #fff;
      color: #344054;
      border-radius: 8px;
      padding: 10px 12px;
      cursor: pointer;
      font-weight: 700;
      font-size: 14px;
    }}
    .filter.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    .filters {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 18px;
      color: var(--muted);
      font-size: 14px;
    }}
    .filters span {{
      background: var(--warm);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 11px;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 14px;
      margin: 24px 0 14px;
    }}
    .section-head h2 {{
      margin: 0;
      font-size: 25px;
      letter-spacing: 0;
    }}
    .section-head p {{ margin: 4px 0 0; color: var(--muted); }}
    #visible-count {{ color: var(--muted); font-weight: 800; white-space: nowrap; }}
    .listings {{ display: grid; gap: 18px; }}
    .listing {{
      display: grid;
      grid-template-columns: 410px 1fr;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      min-height: 292px;
      box-shadow: 0 12px 32px rgba(17, 24, 39, .08);
    }}
    .listing.hidden {{ display: none; }}
    .media {{
      position: relative;
      min-height: 292px;
      background: #dbe4e2;
      color: inherit;
      text-decoration: none;
    }}
    .media img {{
      width: 100%;
      height: 100%;
      min-height: 292px;
      object-fit: cover;
      display: block;
    }}
    .media:after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(0,0,0,.08), transparent 42%, rgba(0,0,0,.38));
      pointer-events: none;
    }}
    .image-placeholder {{
      min-height: 292px;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-weight: 700;
    }}
    .badge {{
      position: absolute;
      top: 12px;
      left: 12px;
      background: #fff;
      color: var(--accent-dark);
      border: 1px solid rgba(255,255,255,.6);
      box-shadow: 0 8px 18px rgba(0,0,0,.16);
      border-radius: 8px;
      padding: 8px 10px;
      font-weight: 900;
      font-size: 14px;
      z-index: 1;
    }}
    .source-pill {{
      position: absolute;
      right: 12px;
      bottom: 12px;
      background: rgba(17, 24, 39, .8);
      color: white;
      border-radius: 8px;
      padding: 8px 10px;
      font-weight: 700;
      font-size: 14px;
      z-index: 1;
    }}
    .content {{ padding: 18px 20px; }}
    .card-kicker {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .deal {{
      border-radius: 999px;
      padding: 5px 8px;
      background: var(--soft);
      color: var(--accent-dark);
    }}
    .deal.below {{ background: #e7f6ed; color: var(--good); }}
    .deal.above {{ background: #fff0ed; color: var(--bad); }}
    .price-row {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .price-row strong {{ font-size: 27px; letter-spacing: 0; }}
    .price-meta {{
      display: flex;
      flex-direction: column;
      gap: 5px;
      align-items: flex-end;
    }}
    .estimate, .market {{
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    .market.below {{ color: var(--good); font-weight: 700; }}
    .market.above {{ color: var(--bad); font-weight: 700; }}
    .market.near {{ color: var(--accent); font-weight: 700; }}
    h2 {{
      font-size: 21px;
      line-height: 1.25;
      margin: 0 0 6px;
      letter-spacing: 0;
    }}
    .location {{
      color: var(--muted);
      margin: 0 0 12px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }}
    .metrics div {{
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      min-width: 0;
    }}
    .metrics span {{
      display: block;
      font-weight: 700;
      font-size: 15px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .metrics small {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }}
    .tags {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .tags span {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      font-size: 13px;
      color: #344054;
      background: #fafafa;
    }}
    .summary {{
      margin: 0 0 14px;
      color: #344054;
      line-height: 1.45;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .analysis {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 14px;
    }}
    .analysis h3 {{
      font-size: 14px;
      margin: 0 0 6px;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }}
    .cta {{
      display: inline-block;
      background: var(--accent);
      color: white;
      text-decoration: none;
      border-radius: 8px;
      padding: 11px 14px;
      font-weight: 800;
    }}
    .cta:hover {{ background: var(--accent-dark); }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    .ghost {{
      border: 1px solid var(--line);
      background: #fff;
      color: #344054;
      border-radius: 8px;
      padding: 10px 13px;
      font-weight: 800;
      cursor: pointer;
    }}
    .ghost-link {{
      display: inline-block;
      border: 1px solid var(--line);
      background: #fff;
      color: #344054;
      text-decoration: none;
      border-radius: 8px;
      padding: 10px 13px;
      font-weight: 800;
    }}
    .toast {{
      position: fixed;
      right: 18px;
      bottom: 18px;
      background: #111827;
      color: #fff;
      padding: 11px 13px;
      border-radius: 8px;
      opacity: 0;
      transform: translateY(8px);
      transition: .18s ease;
      z-index: 20;
    }}
    .toast.show {{ opacity: 1; transform: translateY(0); }}
    .empty {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      color: var(--muted);
    }}
    .no-results {{ display: none; }}
    .no-results.visible {{ display: block; }}
    @media (max-width: 1040px) {{
      .hero {{ grid-template-columns: 1fr; }}
      .photo-wall {{ grid-template-columns: repeat(3, 1fr); grid-template-rows: 150px; min-height: 150px; }}
      .photo-wall figure:first-child {{ grid-row: auto; }}
      .control-panel {{ grid-template-columns: 1fr; position: static; margin-top: -26px; }}
      .source-filters {{ justify-content: flex-start; }}
    }}
    @media (max-width: 800px) {{
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .hero {{ padding-top: 22px; }}
      .hero h1 {{ font-size: 34px; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .photo-wall {{ grid-template-columns: 1fr 1fr; grid-template-rows: 150px 120px; }}
      .photo-wall figure:first-child {{ grid-column: span 2; }}
      .listing {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .analysis {{ grid-template-columns: 1fr; }}
      .price-row {{ align-items: flex-start; flex-direction: column; }}
      .price-meta {{ align-items: flex-start; }}
      .section-head {{ align-items: flex-start; flex-direction: column; }}
    }}
    @media (max-width: 520px) {{
      .hero h1 {{ font-size: 30px; }}
      .stats {{ grid-template-columns: 1fr; }}
      .source-filters {{ display: grid; grid-template-columns: 1fr 1fr; }}
      .filter {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand">
        <strong>Dehesa de Campoamor</strong>
        <span>Viviendas seleccionadas por datos, fotos y modelo de precio</span>
      </div>
      <div class="count">{len(rows)} anuncios seleccionados</div>
    </div>
    <section class="hero">
      <div>
        <h1>Oportunidades reales para comprar en Campoamor</h1>
        <p>Anuncios con foto, ranking automatico, estimacion de precio con machine learning y senales claras para detectar viviendas por debajo de mercado.</p>
        <div class="hero-actions">
          <a class="primary" href="#listings">Ver ranking</a>
          <a href="#controls">Filtrar anuncios</a>
        </div>
        <div class="stats">
          <div class="stat"><strong>{len(rows)}</strong><span>viviendas</span></div>
          <div class="stat"><strong>{average_score}</strong><span>score medio</span></div>
          <div class="stat"><strong>{compact_money(average_price)}</strong><span>precio medio</span></div>
          <div class="stat"><strong>{below_model}</strong><span>debajo del ML</span></div>
        </div>
      </div>
      <div class="photo-wall" aria-label="Fotos destacadas">
        {hero_tiles}
      </div>
    </section>
  </header>
  <main>
    <section class="control-panel" id="controls">
      <div class="search">
        <input id="search" type="search" placeholder="Buscar por titulo, zona o fuente">
      </div>
      <div class="sort">
        <select id="sort">
          <option value="score">Mejor score primero</option>
          <option value="deal">Mayor descuento vs ML</option>
          <option value="price-asc">Precio mas bajo</option>
          <option value="price-desc">Precio mas alto</option>
        </select>
      </div>
      <div class="source-filters">{source_buttons}</div>
    </section>
    <div class="filters">
      <span>Zona: Dehesa de Campoamor</span>
      <span>Precio maximo: 350.000 EUR</span>
      <span>Minimo: 2 dormitorios</span>
      <span>Seleccion: filtros + modelo de precio</span>
    </div>
    <div class="section-head" id="listings">
      <div>
        <h2>Ranking de viviendas</h2>
        <p>Ordenado por encaje, precio y comparacion con el modelo.</p>
      </div>
      <div id="visible-count">{len(rows)} visibles</div>
    </div>
    <section class="listings" id="cards">
      {cards if rows else '<div class="empty">Todavia no hay viviendas seleccionadas. Ejecuta primero los scrapers y el modelo de precio.</div>'}
    </section>
    <div class="empty no-results" id="no-results">No hay viviendas con esos filtros.</div>
  </main>
  <div class="toast" id="toast">Enlace copiado</div>
  <script>
    const cards = Array.from(document.querySelectorAll(".listing"));
    const search = document.getElementById("search");
    const sort = document.getElementById("sort");
    const filters = Array.from(document.querySelectorAll(".filter"));
    const cardsContainer = document.getElementById("cards");
    const visibleCount = document.getElementById("visible-count");
    const noResults = document.getElementById("no-results");
    const toast = document.getElementById("toast");
    let activeSource = "all";

    function asNumber(card, key) {{
      return Number(card.dataset[key] || 0);
    }}

    function applyState() {{
      const term = (search.value || "").trim().toLowerCase();
      const selectedSort = sort.value;

      cards.sort((a, b) => {{
        if (selectedSort === "deal") return asNumber(a, "delta") - asNumber(b, "delta");
        if (selectedSort === "price-asc") return asNumber(a, "price") - asNumber(b, "price");
        if (selectedSort === "price-desc") return asNumber(b, "price") - asNumber(a, "price");
        return asNumber(b, "score") - asNumber(a, "score");
      }}).forEach(card => cardsContainer.appendChild(card));

      let visible = 0;
      cards.forEach(card => {{
        const matchesSource = activeSource === "all" || card.dataset.source === activeSource;
        const matchesTerm = !term || (card.dataset.title || "").includes(term);
        const show = matchesSource && matchesTerm;
        card.classList.toggle("hidden", !show);
        if (show) visible += 1;
      }});

      visibleCount.textContent = `${{visible}} visibles`;
      noResults.classList.toggle("visible", visible === 0);
    }}

    filters.forEach(button => {{
      button.addEventListener("click", () => {{
        activeSource = button.dataset.source;
        filters.forEach(item => item.classList.toggle("active", item === button));
        applyState();
      }});
    }});

    search.addEventListener("input", applyState);
    sort.addEventListener("change", applyState);

    document.querySelectorAll("[data-copy]").forEach(button => {{
      button.addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText(button.dataset.copy);
          toast.classList.add("show");
          setTimeout(() => toast.classList.remove("show"), 1400);
        }} catch (error) {{
          window.prompt("Copia el enlace", button.dataset.copy);
        }}
      }});
    }});
  </script>
</body>
</html>
"""


def render_detail_page(row: sqlite3.Row) -> str:
    images = image_list(row)
    if not images:
        images = [""]
    strengths = automatic_strengths(row)
    risks = automatic_risks(row)
    score = property_score(row)
    price_difference = row["price_difference"]
    difference = "Sin comparacion ML"
    difference_class = "near"
    if price_difference is not None:
        if price_difference < 0:
            difference = f"{money(price_difference)} frente al ML"
            difference_class = "below"
        elif price_difference > 0:
            difference = f"+{money(price_difference)} frente al ML"
            difference_class = "above"
        else:
            difference = "En linea con el ML"
    thumbs = "".join(
        f'<button type="button" class="thumb{" active" if index == 0 else ""}" data-index="{index}"><img src="{text(url)}" alt="Foto {index + 1}"></button>'
        for index, url in enumerate(images)
        if url
    )
    gallery_json = json.dumps(images, ensure_ascii=False)
    strength_html = "".join(f"<li>{text(item)}</li>" for item in strengths)
    risk_html = "".join(f"<li>{text(item)}</li>" for item in risks)
    description = text(row["description"], "")
    summary = text(short_summary(row))
    title = text(row["title"], "Vivienda en Dehesa de Campoamor")
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #667085;
      --line: #d7dfdc;
      --accent: #0f766e;
      --accent-dark: #0a4f49;
      --good: #137a3f;
      --bad: #a33b2f;
      --panel: #fff;
      --soft: #eef3f1;
      --warm: #fbf6ec;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: #f4f7f6;
    }}
    a, button {{ font: inherit; }}
    .shell {{ max-width: 1180px; margin: 0 auto; padding: 18px 20px 54px; }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .back, .external {{
      color: #fff;
      background: var(--accent);
      border-radius: 8px;
      padding: 10px 13px;
      text-decoration: none;
      font-weight: 800;
      border: 0;
      cursor: pointer;
    }}
    .back {{ background: #18212d; }}
    .external:hover {{ background: var(--accent-dark); }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) 390px;
      gap: 20px;
      align-items: start;
    }}
    .gallery, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 14px 36px rgba(17, 24, 39, .09);
    }}
    .stage {{
      position: relative;
      background: #dbe4e2;
      min-height: 540px;
      display: grid;
      place-items: center;
    }}
    .stage img {{
      width: 100%;
      height: 540px;
      object-fit: cover;
      display: block;
    }}
    .nav {{
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      width: 44px;
      height: 44px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.55);
      background: rgba(17, 24, 39, .72);
      color: #fff;
      font-size: 26px;
      cursor: pointer;
    }}
    .prev {{ left: 14px; }}
    .next {{ right: 14px; }}
    .counter {{
      position: absolute;
      right: 14px;
      bottom: 14px;
      background: rgba(17,24,39,.78);
      color: #fff;
      border-radius: 8px;
      padding: 8px 10px;
      font-weight: 800;
    }}
    .thumbs {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(92px, 1fr));
      gap: 8px;
      padding: 10px;
      max-height: 230px;
      overflow: auto;
    }}
    .thumb {{
      padding: 0;
      border: 2px solid transparent;
      border-radius: 6px;
      overflow: hidden;
      cursor: pointer;
      background: #fff;
      aspect-ratio: 4 / 3;
    }}
    .thumb.active {{ border-color: var(--accent); }}
    .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .panel {{ padding: 20px; }}
    .score {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--accent-dark);
      background: var(--soft);
      border-radius: 999px;
      padding: 7px 10px;
      font-weight: 900;
      margin-bottom: 12px;
    }}
    h1 {{ font-size: 30px; line-height: 1.12; margin: 0 0 10px; letter-spacing: 0; }}
    .location {{ margin: 0 0 16px; color: var(--muted); }}
    .price {{ font-size: 32px; font-weight: 900; margin-bottom: 12px; }}
    .delta {{ font-weight: 900; margin-bottom: 16px; }}
    .delta.below {{ color: var(--good); }}
    .delta.above {{ color: var(--bad); }}
    .delta.near {{ color: var(--accent); }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin: 16px 0;
    }}
    .metrics div {{
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
    }}
    .metrics strong {{ display: block; }}
    .metrics span {{ color: var(--muted); font-size: 13px; }}
    .summary, .description {{
      color: #344054;
      line-height: 1.55;
      margin: 16px 0;
    }}
    .analysis {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-top: 18px;
    }}
    .analysis section {{
      background: var(--warm);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .analysis h2 {{ font-size: 15px; margin: 0 0 8px; }}
    ul {{ margin: 0; padding-left: 18px; color: var(--muted); line-height: 1.45; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .ghost {{
      border: 1px solid var(--line);
      background: #fff;
      color: #344054;
      border-radius: 8px;
      padding: 10px 13px;
      font-weight: 800;
      cursor: pointer;
    }}
    @media (max-width: 940px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .stage, .stage img {{ height: 430px; min-height: 430px; }}
    }}
    @media (max-width: 560px) {{
      .top {{ align-items: flex-start; flex-direction: column; }}
      h1 {{ font-size: 25px; }}
      .stage, .stage img {{ height: 300px; min-height: 300px; }}
      .analysis {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <div class="top">
      <a class="back" href="../index.html">Volver al ranking</a>
      <a class="external" href="{text(row["url"], "#")}" target="_blank" rel="noreferrer">Ir al sitio web original</a>
    </div>
    <div class="layout">
      <section class="gallery">
        <div class="stage">
          <button class="nav prev" type="button" aria-label="Foto anterior">&#8249;</button>
          <img id="main-photo" src="{text(images[0])}" alt="{title}">
          <button class="nav next" type="button" aria-label="Foto siguiente">&#8250;</button>
          <div class="counter" id="counter">1/{len(images)}</div>
        </div>
        <div class="thumbs">{thumbs}</div>
      </section>
      <aside class="panel">
        <div class="score">{score}/100 encaje</div>
        <h1>{title}</h1>
        <p class="location">{text(row["location"], "Dehesa de Campoamor")}</p>
        <div class="price">{money(row["price"])}</div>
        <div class="delta {difference_class}">{difference}</div>
        <div class="metrics">
          <div><strong>{number(row["bedrooms"])}</strong><span>Habitaciones</span></div>
          <div><strong>{number(row["bathrooms"])}</strong><span>Banos</span></div>
          <div><strong>{number(row["area_m2"], " m2")}</strong><span>Superficie</span></div>
          <div><strong>{number(row["price_per_m2"], " EUR")}</strong><span>Precio por m2</span></div>
        </div>
        <p class="summary">{summary}</p>
        <div class="actions">
          <a class="external" href="{text(row["url"], "#")}" target="_blank" rel="noreferrer">Ir al sitio web original</a>
          <button class="ghost" type="button" id="copy">Copiar enlace</button>
        </div>
      </aside>
    </div>
    <section class="analysis">
      <section>
        <h2>Por que encaja</h2>
        <ul>{strength_html or "<li>Encaja con los filtros principales.</li>"}</ul>
      </section>
      <section>
        <h2>Riesgos</h2>
        <ul>{risk_html or "<li>Sin riesgos destacados en los datos disponibles.</li>"}</ul>
      </section>
    </section>
    {f'<p class="description">{description}</p>' if description else ''}
  </main>
  <script>
    const images = {gallery_json};
    const mainPhoto = document.getElementById("main-photo");
    const counter = document.getElementById("counter");
    const thumbs = Array.from(document.querySelectorAll(".thumb"));
    let current = 0;

    function show(index) {{
      if (!images.length) return;
      current = (index + images.length) % images.length;
      mainPhoto.src = images[current];
      counter.textContent = `${{current + 1}}/${{images.length}}`;
      thumbs.forEach((thumb, itemIndex) => thumb.classList.toggle("active", itemIndex === current));
    }}

    document.querySelector(".prev").addEventListener("click", () => show(current - 1));
    document.querySelector(".next").addEventListener("click", () => show(current + 1));
    thumbs.forEach(thumb => thumb.addEventListener("click", () => show(Number(thumb.dataset.index))));
    document.addEventListener("keydown", event => {{
      if (event.key === "ArrowLeft") show(current - 1);
      if (event.key === "ArrowRight") show(current + 1);
    }});
    document.getElementById("copy").addEventListener("click", async () => {{
      try {{
        await navigator.clipboard.writeText("{text(row["url"], "#")}");
      }} catch (error) {{
        window.prompt("Copia el enlace", "{text(row["url"], "#")}");
      }}
    }});
  </script>
</body>
</html>
"""


def write_detail_pages(rows: list[sqlite3.Row], output_dir: Path) -> None:
    detail_dir = output_dir / "properties"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        (detail_dir / f"{int(row['id'])}.html").write_text(
            render_detail_page(row),
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera el portal inmobiliario estatico.")
    parser.add_argument("--db", type=Path, default=Path(DB_PATH))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()
    rows = fetch_portal_properties(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_detail_pages(rows, args.output.parent)
    args.output.write_text(render_page(rows), encoding="utf-8")
    print(f"Portal generado: {args.output}")
    print(f"Fichas generadas: {len(rows)}")
    print(f"Anuncios incluidos: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
