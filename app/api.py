"""Endpoints REST para el dashboard NASA.

Devuelven JSON procesado a partir de los datos crudos de api.nasa.gov,
listo para ser consumido por el frontend HTML/CSS/JS.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from app.nasa_client import NasaApiClient, NasaApiError
from app.stats import (
    donki_counts_by_type, donki_time_series, donki_flare_classes,
    donki_gst_kp_stats, donki_recent_events,
    eonet_counts_by_category, eonet_time_series, eonet_map_points,
    eonet_sources_count,
    neo_daily_counts, neo_flatten, neo_summary, neo_closest,
    apod_summary,
)
from config import settings

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #
@api_bp.route("/config")
def get_config():
    """Devuelve la configuración pública del dashboard."""
    return jsonify({
        "is_configured": settings.is_configured,
        "defaults": {
            "donki_days": settings.default_donki_days,
            "eonet_days": settings.default_eonet_days,
            "neo_days": settings.default_neo_days,
        },
    })


# ------------------------------------------------------------------ #
# Fetch principal: DONKI + EONET + NeoWs
# ------------------------------------------------------------------ #
@api_bp.route("/fetch")
def fetch_data():
    """Descarga y procesa DONKI, EONET y NeoWs según los rangos de fechas.

    Query params: donki_start, donki_end, eonet_start, eonet_end,
                  neo_start, neo_end  (todas en YYYY-MM-DD)
    """
    p = request.args
    donki_s = p.get("donki_start")
    donki_e = p.get("donki_end")
    eonet_s = p.get("eonet_start")
    eonet_e = p.get("eonet_end")
    neo_s = p.get("neo_start")
    neo_e = p.get("neo_end")

    if not all([donki_s, donki_e, eonet_s, eonet_e, neo_s, neo_e]):
        return jsonify({"error": "Faltan parámetros de fecha."}), 400

    # Validar rango NeoWs (max 7 dias)
    try:
        ns = datetime.fromisoformat(neo_s)
        ne = datetime.fromisoformat(neo_e)
    except ValueError:
        return jsonify({"error": "Fechas de asteroides inválidas."}), 400
    if (ne - ns).days > 7:
        neo_e = (ns + timedelta(days=7)).date().isoformat()
    if ne <= ns:
        return jsonify({"error": "Rango de asteroides inválido."}), 400

    client = NasaApiClient()
    status_parts: list[str] = []
    result: dict = {"status": "", "kpis": {}, "donki": {}, "eonet": {}, "neo": {}}

    # ---- DONKI ----
    try:
        donki_data = client.get_donki_all(donki_s, donki_e)
        total_donki = sum(len(v) for v in donki_data.values())
        status_parts.append(f"DONKI: {total_donki} eventos")

        counts = donki_counts_by_type(donki_data)
        ts = donki_time_series(donki_data)
        flare_classes = donki_flare_classes(donki_data.get("FLR", []))
        kp = donki_gst_kp_stats(donki_data.get("GST", []))
        recent = donki_recent_events(donki_data, limit=20)

        result["donki"] = {
            "counts": counts,
            "time_series": {
                "dates": [d.strftime("%Y-%m-%d") for d in ts.index] if not ts.empty else [],
                "series": {col: [int(v) for v in ts[col]] for col in ts.columns} if not ts.empty else {},
            },
            "flare_classes": flare_classes,
            "kp_stats": kp,
            "recent_events": recent.to_dict("records") if not recent.empty else [],
        }
    except NasaApiError as exc:
        status_parts.append(f"DONKI: error ({exc})")

    # ---- EONET ----
    try:
        es = datetime.fromisoformat(eonet_s)
        ee = datetime.fromisoformat(eonet_e)
        eonet_days = max(1, (ee - es).days)
        eonet_events = client.get_eonet_events(days=eonet_days)
        status_parts.append(f"EONET: {len(eonet_events)} eventos")

        cat_counts = eonet_counts_by_category(eonet_events)
        src_counts = eonet_sources_count(eonet_events)
        top_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "--"
        ts = eonet_time_series(eonet_events)
        map_df = eonet_map_points(eonet_events)

        result["eonet"] = {
            "total": len(eonet_events),
            "n_cats": len(cat_counts),
            "n_sources": len(src_counts),
            "top_cat": top_cat,
            "bar_categories": {
                "labels": list(cat_counts.keys()),
                "values": list(cat_counts.values()),
            },
            "time_series": {
                "dates": [d.strftime("%Y-%m-%d") for d in ts.index] if not ts.empty else [],
                "series": {col: [int(v) for v in ts[col]] for col in ts.columns} if not ts.empty else {},
            },
            "map_points": map_df.to_dict("records") if not map_df.empty else [],
        }
    except NasaApiError as exc:
        status_parts.append(f"EONET: error ({exc})")

    # ---- NeoWs ----
    try:
        neo_data = client.get_neo_feed(neo_s, neo_e)
        neo_count = sum(len(v) for v in neo_data.get("near_earth_objects", {}).values())
        status_parts.append(f"NEO: {neo_count} asteroides")

        flat = neo_flatten(neo_data)
        s = neo_summary(flat)
        daily = neo_daily_counts(neo_data)
        diam = ((flat["diameter_min_m"] + flat["diameter_max_m"]) / 2).dropna().tolist() if not flat.empty else []
        closest = neo_closest(flat, limit=10)

        # Formatear closest para la tabla
        closest_records = []
        if not closest.empty:
            for _, row in closest.iterrows():
                closest_records.append({
                    "name": row["name"],
                    "date": row["date"],
                    "diameter_max_m": round(float(row["diameter_max_m"]), 1),
                    "miss_km": f"{float(row['miss_km']):,.0f}",
                    "velocity_kmh": f"{float(row['velocity_kmh']):,.0f}",
                    "hazardous": "Sí" if row["hazardous"] else "No",
                })

        result["neo"] = {
            "summary": s,
            "daily_counts": {
                "dates": [d.strftime("%Y-%m-%d") for d in daily["date"]] if not daily.empty else [],
                "counts": [int(v) for v in daily["count"]] if not daily.empty else [],
            },
            "diameters": [float(d) for d in diam],
            "hazard_counts": {
                "hazardous": s["hazardous"],
                "no_hazardous": s["no_hazardous"],
            },
            "closest": closest_records,
        }
    except NasaApiError as exc:
        status_parts.append(f"NEO: error ({exc})")

    # ---- KPIs globales ----
    donki = result.get("donki", {})
    neo = result.get("neo", {})
    result["kpis"] = {
        "cme": donki.get("counts", {}).get("CME", 0),
        "flr": donki.get("counts", {}).get("FLR", 0),
        "gst": donki.get("counts", {}).get("GST", 0),
        "neo": neo.get("summary", {}).get("total", 0),
    }

    result["status"] = " | ".join(status_parts)
    return jsonify(result)


# ------------------------------------------------------------------ #
# APOD
# ------------------------------------------------------------------ #
@api_bp.route("/apod")
def get_apod():
    """Devuelve la imagen astronómica del día para una fecha dada."""
    apod_date = request.args.get("date")
    if not apod_date:
        return jsonify({"error": "Falta el parámetro 'date'."}), 400

    client = NasaApiClient()
    try:
        data = client.get_apod(date=apod_date)
    except NasaApiError as exc:
        return jsonify({"error": f"Error NASA: {exc}"}), 502

    return jsonify(apod_summary(data))
