"""Endpoints REST para el dashboard NASA.

Devuelven JSON procesado a partir de los datos crudos de api.nasa.gov,
listo para ser consumido por el frontend HTML/CSS/JS.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import re

from flask import Blueprint, jsonify, request

from app import ml
from app.collector import update_recent
from app.db import store
from app.nasa_client import nasa_client, NasaApiError
from app.stats import (
    donki_counts_by_type, donki_time_series, donki_flare_classes,
    donki_gst_kp_stats, donki_recent_events, donki_latest_events,
    eonet_counts_by_category, eonet_time_series, eonet_map_points,
    eonet_sources_count,
    neo_daily_counts, neo_flatten, neo_summary, neo_closest,
    apod_summary,
)
from config import settings

api_bp = Blueprint("api", __name__, url_prefix="/api")
_fetch_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="nasa-source")


def _parse_date(value):
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Usa fechas con formato YYYY-MM-DD.")
    return date.fromisoformat(value)


def _validate_range(start, end, label, max_days):
    first, last = _parse_date(start), _parse_date(end)
    if first > last:
        raise ValueError(f"{label}: la fecha inicial debe ser anterior o igual a la final.")
    if (last - first).days + 1 > max_days:
        raise ValueError(f"{label}: selecciona como máximo {max_days} días, incluidos inicio y fin.")


# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #
@api_bp.route("/config")
def get_config():
    """Devuelve la configuración pública del dashboard."""
    return jsonify({
        "is_configured": settings.is_configured,
        "limits": {"donki_days": 61, "eonet_days": 3660, "neo_days": 7},
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

    try:
        _validate_range(donki_s, donki_e, "DONKI", 61)
        _validate_range(eonet_s, eonet_e, "EONET", 3660)
        _validate_range(neo_s, neo_e, "NeoWs", 7)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    client = nasa_client
    donki_future = _fetch_executor.submit(client.get_donki_all, donki_s, donki_e)
    eonet_future = _fetch_executor.submit(client.get_eonet_events, start_date=eonet_s, end_date=eonet_e)
    neo_future = _fetch_executor.submit(client.get_neo_feed, neo_s, neo_e)
    status_parts: list[str] = []
    result: dict = {"status": "", "kpis": {}, "donki": {}, "eonet": {}, "neo": {}, "errors": {}}

    # ---- DONKI ----
    try:
        donki_data, donki_errors = donki_future.result()
        if donki_errors:
            result["errors"]["donki"] = donki_errors
            status_parts.append("DONKI: datos incompletos (" + "; ".join(
                f"{kind}: {message}" for kind, message in donki_errors.items()) + ")")
        total_donki = sum(len(v) for v in donki_data.values())
        if not donki_errors:
            status_parts.append(f"DONKI: {total_donki} eventos")

        counts = donki_counts_by_type(donki_data)
        ts = donki_time_series(donki_data, donki_s, donki_e)
        flare_classes = donki_flare_classes(donki_data.get("FLR", []))
        kp = donki_gst_kp_stats(donki_data.get("GST", []))
        recent = donki_recent_events(donki_data, limit=20)

        result["donki"] = {
            "counts": counts,
            "errors": donki_errors,
            "time_series": {
                "dates": [d.strftime("%Y-%m-%d") for d in ts.index] if not ts.empty else [],
                "series": {col: [int(v) for v in ts[col]] for col in ts.columns} if not ts.empty else {},
            },
            "flare_classes": flare_classes,
            "kp_stats": kp,
            "recent_events": recent.to_dict("records") if not recent.empty else [],
            "latest_events": donki_latest_events(donki_data),
        }
    except NasaApiError as exc:
        result["errors"]["donki"] = str(exc)
        status_parts.append(f"DONKI: error ({exc})")

    # ---- EONET ----
    try:
        eonet_raw = eonet_future.result()
        # EONET puede devolver geometrías fuera del intervalo dentro de un evento.
        # Copiar evita modificar la respuesta cruda compartida en caché.
        eonet_events = []
        for event in eonet_raw:
            geometry = [g for g in event.get("geometry", []) or []
                        if eonet_s <= (g.get("date") or "")[:10] <= eonet_e]
            if geometry:
                eonet_events.append({**event, "geometry": sorted(geometry, key=lambda g: g["date"])})
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
        result["errors"]["eonet"] = str(exc)
        status_parts.append(f"EONET: error ({exc})")

    # ---- NeoWs ----
    try:
        neo_data = neo_future.result()
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
                    "velocity_kmh": f"{float(row['velocity_kmh']):,.0f}" if row['velocity_kmh'] == row['velocity_kmh'] else "--",
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
        result["errors"]["neo"] = str(exc)
        status_parts.append(f"NEO: error ({exc})")

    # ---- KPIs globales ----
    donki = result.get("donki", {})
    neo = result.get("neo", {})
    result["kpis"] = {
        "cme": donki.get("counts", {}).get("CME"),
        "flr": donki.get("counts", {}).get("FLR"),
        "gst": donki.get("counts", {}).get("GST"),
        "neo": neo.get("summary", {}).get("total"),
    }

    result["status"] = " | ".join(status_parts)
    result["partial"] = bool(result["errors"])
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

    try:
        parsed = _parse_date(apod_date)
        if parsed < date(1995, 6, 16) or parsed > date.today():
            raise ValueError("APOD: elige una fecha desde 1995-06-16 hasta hoy.")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    client = nasa_client
    try:
        data = client.get_apod(date=apod_date)
    except NasaApiError as exc:
        response = jsonify({"error": f"Error NASA: {exc}"})
        if exc.status_code == 429:
            response.headers["Retry-After"] = "60"
        return response, exc.status_code

    return jsonify(apod_summary(data))


# ------------------------------------------------------------------ #
# Predicciones: dataset, modelos, pronostico y backtest
# ------------------------------------------------------------------ #
@api_bp.route("/predictions")
def get_predictions():
    """Estado del pipeline: volumen del dataset, metricas de cada modelo,
    pronostico con los datos vigentes y backtest de los ultimos dias."""
    dataset = store.dataset_summary()
    models = store.registered_models()
    if not models:
        return jsonify({
            "ready": False,
            "dataset": dataset,
            "models": [],
            "forecasts": {},
            "backtests": {},
            "message": "Aun no hay modelos entrenados. Ejecuta scripts/backfill.py "
                       "y scripts/train_models.py, o usa los botones de la pestana "
                       "Predicciones.",
        })
    forecasts = ml.predict(store)
    backtests = ml.backtest(store, days=60)
    return jsonify({
        "ready": True,
        "dataset": dataset,
        "models": models,
        "forecasts": forecasts,
        "backtests": backtests,
    })


@api_bp.route("/collect", methods=["POST"])
def run_collect():
    """Refresca los ultimos dias de todas las fuentes (idempotente)."""
    try:
        summary = update_recent(store)
    except Exception as exc:  # el dashboard sigue usable ante cualquier fallo
        return jsonify({"ok": False, "error": f"Recoleccion fallida: {exc}"}), 502
    return jsonify({"ok": True, "summary": summary, "dataset": store.dataset_summary()})


@api_bp.route("/train", methods=["POST"])
def run_train():
    """Entrena todos los modelos con el dataset vigente."""
    counts = store.counts()
    if counts.get("donki_events", 0) < 50 and counts.get("eonet_events", 0) < 50:
        return jsonify({
            "ok": False,
            "error": "El dataset esta casi vacio. Ejecuta primero el backfill: "
                     "python scripts/backfill.py --source all",
        }), 400
    try:
        results = ml.train_all(store)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Entrenamiento fallido: {exc}"}), 500
    trained = sum(1 for r in results.values() if isinstance(r, dict) and r.get("status") == "ok")
    return jsonify({"ok": True, "trained": trained, "total": len(results), "results": results})
