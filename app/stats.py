"""Funciones estadisticas sobre los datos de los endpoints de api.nasa.gov.

Operan sobre las estructuras devueltas por NasaApiClient y devuelven
diccionarios/listas listas para la API REST del frontend.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Dict, List, Optional

import pandas as pd


# ---------------------------------------------------------------------- #
# DONKI - Space Weather
# ---------------------------------------------------------------------- #
def donki_latest_events(donki_all: Dict[str, List[dict]]) -> Dict[str, str]:
    """Última fecha por tipo, independiente del límite de la tabla reciente."""
    return {kind: max((ev.get("startTime") or ev.get("eventTime") or ev.get("beginTime") or ""
                      for ev in events), default="") for kind, events in donki_all.items()}


def donki_counts_by_type(donki_all: Dict[str, List[dict]]) -> Dict[str, int]:
    """Cuenta eventos por tipo (CME, FLR, GST, ...)."""
    return {et: len(events) for et, events in donki_all.items()}


def donki_time_series(donki_all: Dict[str, List[dict]], start_date=None, end_date=None) -> pd.DataFrame:
    """Serie temporal diaria de eventos por tipo.

    Devuelve DataFrame con indice fecha y columnas por tipo.
    """
    rows: List[dict] = []
    for et, events in donki_all.items():
        for ev in events:
            ts = ev.get("startTime") or ev.get("eventTime") or ev.get("beginTime")
            if not ts:
                continue
            try:
                day = datetime.fromisoformat(ts.replace("Z", "")).strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                continue
            rows.append({"date": day, "type": et})
    if rows:
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        pivot = pd.crosstab(df["date"], df["type"])
    else:
        pivot = pd.DataFrame()
    if start_date and end_date:
        pivot = pivot.reindex(index=pd.date_range(start_date, end_date),
                              columns=list(donki_all), fill_value=0)
    return pivot.sort_index()


def donki_flare_classes(flr_events: List[dict]) -> Dict[str, int]:
    """Distribucion de flares por clase (X, M, C, B, A)."""
    counts = Counter()
    for ev in flr_events:
        cls = ev.get("classType", "")
        if cls:
            # classType ej: "X1.2", "M5.3", "C4.1"
            top = cls[0].upper() if cls[0].isalpha() else "?"
            counts[top] += 1
        else:
            counts["?"] += 1
    return dict(counts)


def donki_gst_kp_stats(gst_events: List[dict]) -> Dict[str, float]:
    """Estadisticas del Kp index de tormentas geomagneticas."""
    kps: List[float] = []
    for ev in gst_events:
        # GST tiene allKpIndex con kp values
        for kp_entry in ev.get("allKpIndex", []) or []:
            kp = kp_entry.get("kpIndex")
            if kp is not None:
                kps.append(float(kp))
    if not kps:
        return {"max": 0.0, "media": 0.0, "n": 0}
    return {
        "max": round(max(kps), 1),
        "media": round(sum(kps) / len(kps), 2),
        "n": len(kps),
    }


def donki_recent_events(donki_all: Dict[str, List[dict]], limit: int = 20) -> pd.DataFrame:
    """Tabla de los eventos mas recientes."""
    rows = []
    for et, events in donki_all.items():
        for ev in events:
            ts = ev.get("startTime") or ev.get("eventTime") or ev.get("beginTime") or ""
            rows.append({
                "Tipo": et,
                "Fecha/Hora": ts,
                "ID": ev.get("activityID") or ev.get(f"{et.lower()}ID") or "",
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values("Fecha/Hora", ascending=False).head(limit)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------- #
# EONET - Earth Events
# ---------------------------------------------------------------------- #
def eonet_counts_by_category(events: List[dict]) -> Dict[str, int]:
    counts = Counter()
    for ev in events:
        for cat in ev.get("categories", []):
            title = cat.get("title", "Desconocido")
            counts[title] += 1
    return dict(counts)


def eonet_time_series(events: List[dict]) -> pd.DataFrame:
    """Eventos por fecha (geometries[0].date)."""
    rows = []
    for ev in events:
        geoms = ev.get("geometry", []) or []
        if not geoms:
            continue
        date_str = geoms[0].get("date", "")
        if not date_str:
            continue
        try:
            day = datetime.fromisoformat(date_str.replace("Z", "")).strftime("%Y-%m-%d")
        except ValueError:
            continue
        cats = [c.get("title", "?") for c in ev.get("categories", [])]
        for cat in cats:
            rows.append({"date": day, "category": cat})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    pivot = pd.crosstab(df["date"], df["category"])
    return pivot.sort_index()


def eonet_map_points(events: List[dict]) -> pd.DataFrame:
    """Extrae lat/lon/categoria/titulo para el mapa."""
    rows = []
    for ev in events:
        geoms = ev.get("geometry", []) or []
        if not geoms:
            continue
        geom = geoms[0]
        coords = geom.get("coordinates", []) or []
        cats = [c.get("title", "?") for c in ev.get("categories", [])]
        cat = cats[0] if cats else "?"
        title = ev.get("title", "")
        date_str = geom.get("date", "")
        # Polygon usa anillos [[[lon, lat], ...]]; un vértice representa su ubicación.
        while coords and isinstance(coords[0], list):
            coords = coords[0]
        if (len(coords) >= 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in coords[:2])
                and -180 <= coords[0] <= 180 and -90 <= coords[1] <= 90):
            rows.append({"lat": coords[1], "lon": coords[0], "category": cat,
                         "title": title, "date": date_str})
    if not rows:
        return pd.DataFrame(columns=["lat", "lon", "category", "title", "date"])
    return pd.DataFrame(rows)


def eonet_sources_count(events: List[dict]) -> Dict[str, int]:
    counts = Counter()
    for ev in events:
        for src in ev.get("sources", []) or []:
            sid = src.get("id", "?")
            counts[sid] += 1
    return dict(counts)


# ---------------------------------------------------------------------- #
# NeoWs - Asteroids
# ---------------------------------------------------------------------- #
def neo_daily_counts(feed: dict) -> pd.DataFrame:
    """NEOs por dia."""
    neos = feed.get("near_earth_objects", {})
    rows = [{"date": d, "count": len(items)} for d, items in neos.items()]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def neo_flatten(feed: dict) -> pd.DataFrame:
    """Aplana todos los NEOs del feed a un DataFrame."""
    neos = feed.get("near_earth_objects", {})
    rows = []
    for day, items in neos.items():
        for n in items:
            approaches = n.get("close_approach_data") or []
            cad = next((a for a in approaches if a.get("close_approach_date") == day), {})
            if not cad and len(approaches) == 1:
                cad = approaches[0]
            miss = cad.get("miss_distance", {}).get("kilometers")
            vel = cad.get("relative_velocity", {}).get("kilometers_per_hour")
            rows.append({
                "date": day,
                "id": n.get("id"),
                "name": n.get("name", "").strip(),
                "diameter_min_m": float((n.get("estimated_diameter", {}).get("meters", {})
                                         .get("estimated_diameter_min", 0)) or 0),
                "diameter_max_m": float((n.get("estimated_diameter", {}).get("meters", {})
                                         .get("estimated_diameter_max", 0)) or 0),
                "hazardous": bool(n.get("is_potentially_hazardous_asteroid", False)),
                "miss_km": float(miss) if miss is not None else None,
                "velocity_kmh": float(vel) if vel is not None else None,
                "abs_mag": n.get("absolute_magnitude_h"),
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def neo_summary(flat: pd.DataFrame) -> Dict[str, float]:
    if flat.empty:
        return {"total": 0, "hazardous": 0, "no_hazardous": 0,
                "diam_med": 0.0, "miss_min": 0.0, "vel_med": 0.0}
    diam_med = ((flat["diameter_min_m"] + flat["diameter_max_m"]) / 2).mean()
    return {
        "total": int(len(flat)),
        "hazardous": int(flat["hazardous"].sum()),
        "no_hazardous": int((~flat["hazardous"]).sum()),
        "diam_med": round(float(diam_med), 2),
        "miss_min": round(float(flat["miss_km"].min()), 0) if flat["miss_km"].notna().any() else 0.0,
        "vel_med": round(float(flat["velocity_kmh"].mean()), 2) if flat["velocity_kmh"].notna().any() else 0.0,
    }


def neo_closest(flat: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if flat.empty:
        return flat
    sub = flat.dropna(subset=["miss_km"]).sort_values("miss_km").head(limit)
    return sub[["name", "date", "diameter_max_m", "miss_km", "velocity_kmh", "hazardous"]].reset_index(drop=True)


# ---------------------------------------------------------------------- #
# APOD
# ---------------------------------------------------------------------- #
def apod_summary(apod: dict) -> Dict[str, str]:
    return {
        "title": apod.get("title", ""),
        "date": apod.get("date", ""),
        "explanation": apod.get("explanation", ""),
        "url": apod.get("url", ""),
        "hdurl": apod.get("hdurl", "") or apod.get("url", ""),
        "media_type": apod.get("media_type", "image"),
        "copyright": apod.get("copyright", "NASA"),
    }
