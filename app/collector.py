"""Descarga y persistencia del dataset historico para predicciones.

Dos modos de uso:

- backfill: descarga por tramos el historial completo (DONKI en bloques
  de hasta 60 dias porque el endpoint CCMC rechaza rangos mayores con
  HTTP 400; EONET y Open-Meteo por anos) desde una fecha inicial hasta
  hoy. Es idempotente: puede interrumpirse y reanudarse sin duplicar
  filas.
- update_recent: refresco incremental de los ultimos dias, usado por el
  scheduler y por el boton del dashboard.

Usa sesiones propias sin la cache del dashboard: las respuestas del
historial son grandes y no deben desplazar las consultas vivas del
usuario en memoria.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Callable, Dict, Iterator, List, Optional, Tuple
import csv
import io
import json
import logging
import math
import threading
import time

import requests

from app.db import Store, store as default_store
from config import settings

log = logging.getLogger(__name__)

Progress = Optional[Callable[[str], None]]

# Regiones representativas propensas a incendios: clima (Open-Meteo) y
# conteo de focos (FIRMS). Centroides aproximados de grandes zonas.
FIRE_REGIONS: List[Tuple[str, float, float]] = [
    ("California", 36.7, -119.4),
    ("Amazonia", -10.5, -55.0),
    ("Australia SE", -33.0, 149.0),
    ("Siberia Sur", 56.0, 92.0),
    ("Africa Central", -2.0, 22.0),
    ("Canada Oeste", 54.0, -121.0),
]

_local = threading.local()


class CollectorError(Exception):
    """Fallo de descarga; el mensaje nunca incluye la FIRMS map key."""


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        session = requests.Session()
        session.headers.update({"User-Agent": settings.user_agent, "Accept": "application/json"})
        _local.session = session
    return _local.session


def _is_day(text: str) -> bool:
    if len(text) != 10:
        return False
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


def _retry_after(raw: Optional[str]) -> float:
    if not raw:
        return 60.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        try:
            return max(1.0, parsedate_to_datetime(raw).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 60.0


def fetch_json(url: str, params: Optional[dict] = None, timeout: float = 120.0, max_retries: int = 3):
    """GET JSON con reintentos, backoff y respeto de Retry-After (HTTP 429)."""
    last_error = "sin respuesta"
    for attempt in range(max_retries):
        try:
            with _session().get(url, params=params or {}, timeout=(10, timeout)) as resp:
                if resp.status_code == 429:
                    delay = _retry_after(resp.headers.get("Retry-After"))
                    time.sleep(min(delay, 180.0))
                    last_error = "limite de consultas (HTTP 429)"
                    continue
                if resp.status_code in (408, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}"
                    if attempt + 1 < max_retries:
                        time.sleep(2 ** attempt)
                    continue
                if resp.status_code >= 400:
                    raise CollectorError(f"El servicio respondio HTTP {resp.status_code}.")
                try:
                    return resp.json()
                except ValueError:
                    raise CollectorError("El servicio devolvio una respuesta JSON invalida.") from None
        except requests.Timeout:
            last_error = "tiempo de espera agotado"
        except requests.ConnectionError:
            last_error = "fallo de conexion"
        except requests.RequestException:
            raise CollectorError("Error de comunicacion con el servicio.") from None
        if attempt + 1 < max_retries:
            time.sleep(2 ** attempt)
    raise CollectorError(f"No se pudo completar la descarga ({last_error}).")


def fetch_text(url: str, params: Optional[dict] = None, timeout: float = 120.0, max_retries: int = 3) -> str:
    """GET de texto (CSV de FIRMS) con la misma politica de reintentos."""
    last_error = "sin respuesta"
    for attempt in range(max_retries):
        try:
            with _session().get(url, params=params or {}, timeout=(10, timeout)) as resp:
                if resp.status_code == 429:
                    time.sleep(min(_retry_after(resp.headers.get("Retry-After")), 180.0))
                    last_error = "limite de consultas (HTTP 429)"
                    continue
                if resp.status_code in (408, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}"
                    if attempt + 1 < max_retries:
                        time.sleep(2 ** attempt)
                    continue
                if resp.status_code >= 400:
                    raise CollectorError(f"El servicio respondio HTTP {resp.status_code}.")
                return resp.text
        except requests.Timeout:
            last_error = "tiempo de espera agotado"
        except requests.ConnectionError:
            last_error = "fallo de conexion"
        except requests.RequestException:
            raise CollectorError("Error de comunicacion con el servicio.") from None
        if attempt + 1 < max_retries:
            time.sleep(2 ** attempt)
    raise CollectorError(f"No se pudo completar la descarga ({last_error}).")


def _chunks(start: date, end: date, days: int) -> Iterator[Tuple[date, date]]:
    """Divide [start, end] en tramos inclusivos de hasta 'days' dias."""
    current = start
    while current <= end:
        stop = min(current + timedelta(days=days - 1), end)
        yield current, stop
        current = stop + timedelta(days=1)


def _parse_day(text: str) -> Optional[str]:
    day = str(text or "")[:10]
    return day if _is_day(day) else None


# ---------------------------------------------------------------------- #
# DONKI: flares, CME, tormentas geomagneticas y particulas
# ---------------------------------------------------------------------- #
def parse_donki_events(event_type: str, raw: List[dict]) -> List[Tuple[str, str, str, str, Optional[str]]]:
    """Convierte la respuesta DONKI en filas listas para la base.

    Cada fila: (event_type, event_id, event_day, event_time, extra_json).
    'extra' guarda los campos especificos de cada tipo (clase del flare,
    velocidad del CME, Kp maximo de la tormenta, ...).
    """
    rows: List[Tuple[str, str, str, str, Optional[str]]] = []
    for ev in raw or []:
        if not isinstance(ev, dict):
            continue
        event_id = ev.get("activityID") or ev.get(f"{event_type.lower()}ID")
        event_time = ev.get("startTime") or ev.get("eventTime") or ev.get("beginTime")
        if not event_id or not event_time:
            continue
        day = _parse_day(event_time)
        if not day:
            continue
        extra: Dict = {}
        if event_type == "FLR":
            class_type = ev.get("classType")
            if class_type:
                extra["class"] = class_type
                extra["top_class"] = class_type[0].upper() if class_type[:1].isalpha() else "?"
            if ev.get("sourceLocation"):
                extra["source_location"] = ev["sourceLocation"]
            if ev.get("activeRegionNum") is not None:
                extra["active_region"] = ev["activeRegionNum"]
            if ev.get("peakTime"):
                extra["peak_time"] = ev["peakTime"]
        elif event_type == "CME":
            for key in ("speed", "halfAngle", "latitude", "longitude", "type"):
                if ev.get(key) is not None:
                    extra[key] = ev[key]
        elif event_type == "GST":
            kps = [float(k.get("kpIndex")) for k in ev.get("allKpIndex") or []
                   if isinstance(k, dict) and k.get("kpIndex") is not None]
            if kps:
                extra["max_kp"] = max(kps)
                extra["kp_entries"] = len(kps)
        rows.append((event_type, event_id, day, str(event_time), json.dumps(extra) if extra else None))
    return rows


def backfill_donki(store: Store, start: date, end: date, types: Optional[List[str]] = None,
                   kind: str = "backfill", progress: Progress = None) -> dict:
    """Descarga DONKI por tramos de hasta 60 dias y lo guarda por tipo.

    El endpoint CCMC acepta rangos de 61 dias como maximo (probado
    empiricamente: 61 OK, HTTP 400 desde 62); se usa 60 de margen.
    """
    event_types = types or settings.donki_backfill_types_list
    base = settings.donki_base_url.rstrip("/")
    results = {et: {"rows": 0, "errors": []} for et in event_types}
    chunks = list(_chunks(start, end, 60))
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="donki-backfill") as pool:
        futures = {}
        for et in event_types:
            for chunk_start, chunk_end in chunks:
                future = pool.submit(
                    fetch_json, f"{base}/{et}",
                    {"startDate": chunk_start.isoformat(), "endDate": chunk_end.isoformat()},
                )
                futures[future] = (et, chunk_start, chunk_end)
        for future in as_completed(futures):
            et, chunk_start, chunk_end = futures[future]
            try:
                raw = future.result()
                rows = parse_donki_events(et, raw if isinstance(raw, list) else [])
                store.upsert_donki(rows)
                results[et]["rows"] += len(rows)
                if progress:
                    progress(f"DONKI {et}: {chunk_start} -> {chunk_end} ({len(rows)} eventos)")
            except CollectorError as exc:
                results[et]["errors"].append(f"{chunk_start}->{chunk_end}: {exc}")
    ok = not any(r["errors"] for r in results.values())
    total_rows = sum(r["rows"] for r in results.values())
    errors_msg = "; ".join(f"{et}: {len(r['errors'])} tramos con error" for et, r in results.items() if r["errors"])
    store.record_run("donki", kind, ok, total_rows, errors_msg)
    return results


# ---------------------------------------------------------------------- #
# EONET: eventos naturales terrestres
# ---------------------------------------------------------------------- #
def parse_eonet_events(raw: List[dict]) -> List[Tuple[str, str, str, str, str, Optional[float], Optional[float]]]:
    """Filas: (event_id, title, category, first_day, last_day, lat, lon).

    La fecha de cada evento es el primer dia de geometria, la misma
    convencion que usa la serie temporal del dashboard.
    """
    rows: List[Tuple[str, str, str, str, str, Optional[float], Optional[float]]] = []
    for ev in raw or []:
        if not isinstance(ev, dict):
            continue
        event_id = ev.get("id")
        geoms = ev.get("geometry") or []
        days = sorted({d for d in (_parse_day(g.get("date")) for g in geoms if isinstance(g, dict)) if d})
        if not event_id or not days:
            continue
        lat = lon = None
        # Coordenadas de la geometria mas antigua (la que define first_day).
        first_geom = next((g for g in geoms if isinstance(g, dict) and _parse_day(g.get("date")) == days[0]), None)
        coords = (first_geom or {}).get("coordinates") or []
        while coords and isinstance(coords[0], list):
            coords = coords[0]
        if (len(coords) >= 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in coords[:2])
                and -180 <= coords[0] <= 180 and -90 <= coords[1] <= 90):
            lon, lat = float(coords[0]), float(coords[1])
        categories = [c.get("title") for c in ev.get("categories") or []
                      if isinstance(c, dict) and c.get("title")]
        rows.append((
            str(event_id), str(ev.get("title") or "")[:300],
            categories[0] if categories else "Desconocido",
            days[0], days[-1], lat, lon,
        ))
    return rows


def backfill_eonet(store: Store, start: date, end: date, kind: str = "backfill",
                   progress: Progress = None) -> dict:
    """Descarga EONET en tramos anuales (status=all) y lo guarda."""
    url = f"{settings.eonet_base_url.rstrip('/')}/events"
    result = {"rows": 0, "errors": []}
    for chunk_start, chunk_end in _chunks(start, end, 365):
        try:
            raw = fetch_json(url, {
                "start": chunk_start.isoformat(),
                "end": chunk_end.isoformat(),
                "status": "all",
            })
            # EONET v3 envuelve la lista: {"title": ..., "events": [...]}.
            if isinstance(raw, dict):
                raw = raw.get("events") or []
            rows = parse_eonet_events(raw if isinstance(raw, list) else [])
            store.upsert_eonet(rows)
            result["rows"] += len(rows)
            if progress:
                progress(f"EONET: {chunk_start} -> {chunk_end} ({len(rows)} eventos)")
        except CollectorError as exc:
            result["errors"].append(f"{chunk_start}->{chunk_end}: {exc}")
    store.record_run("eonet", kind, not result["errors"], result["rows"],
                     "; ".join(result["errors"][:3]))
    return result


# ---------------------------------------------------------------------- #
# Open-Meteo: clima historico de regiones propensas a incendios
# ---------------------------------------------------------------------- #
def parse_open_meteo(payload, region_names: List[str]) -> List[Tuple[str, str, Optional[float], Optional[float], Optional[float], Optional[float]]]:
    """Filas: (location, day, t_max, t_min, precip, wind_max)."""
    locations = payload if isinstance(payload, list) else [payload]
    rows: List[Tuple[str, str, Optional[float], Optional[float], Optional[float], Optional[float]]] = []
    for i, loc in enumerate(locations):
        if not isinstance(loc, dict):
            continue
        name = region_names[i] if i < len(region_names) else f"region_{i}"
        daily = loc.get("daily") or {}
        times = daily.get("time") or []

        def _value(key: str, j: int) -> Optional[float]:
            values = daily.get(key) or []
            if j >= len(values):
                return None
            v = values[j]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        for j, day in enumerate(times):
            day_text = _parse_day(day)
            if not day_text:
                continue
            rows.append((
                name, day_text,
                _value("temperature_2m_max", j), _value("temperature_2m_min", j),
                _value("precipitation_sum", j), _value("wind_speed_10m_max", j),
            ))
    return rows


def backfill_open_meteo(store: Store, start: date, end: date, kind: str = "backfill",
                        progress: Progress = None) -> dict:
    """Descarga el archivo historico de Open-Meteo para las regiones."""
    names = [name for name, _, _ in FIRE_REGIONS]
    params = {
        "latitude": ",".join(str(lat) for _, lat, _ in FIRE_REGIONS),
        "longitude": ",".join(str(lon) for _, _, lon in FIRE_REGIONS),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "timezone": "UTC",
    }
    result = {"rows": 0, "errors": []}
    for chunk_start, chunk_end in _chunks(start, end, 366):
        try:
            payload = fetch_json(settings.open_meteo_base_url, {
                **params,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
            })
            rows = parse_open_meteo(payload, names)
            store.upsert_open_meteo(rows)
            result["rows"] += len(rows)
            if progress:
                progress(f"Open-Meteo: {chunk_start} -> {chunk_end} ({len(rows)} filas)")
        except CollectorError as exc:
            result["errors"].append(f"{chunk_start}->{chunk_end}: {exc}")
    store.record_run("open_meteo", kind, not result["errors"], result["rows"],
                     "; ".join(result["errors"][:3]))
    return result


# ---------------------------------------------------------------------- #
# FIRMS: focos de incendio satelitales (requiere FIRMS_MAP_KEY)
# ---------------------------------------------------------------------- #
def update_firms(store: Store, days: int = 10, progress: Progress = None) -> dict:
    """Descarga los focos VIIRS de los ultimos dias por region.

    FIRMS limita cada consulta a 10 dias, por lo que esta fuente solo se
    alimenta de forma incremental; sin FIRMS_MAP_KEY se omite sin error.
    """
    if not settings.firms_enabled:
        return {"skipped": "FIRMS_MAP_KEY no configurada; fuente omitida."}
    day_range = max(1, min(days, 10))
    result: Dict[str, object] = {"days": day_range}
    total = 0
    errors: List[str] = []
    for name, lat, lon in FIRE_REGIONS:
        box = f"{lon - 10:.1f},{lat - 10:.1f},{lon + 10:.1f},{lat + 10:.1f}"
        url = (f"{settings.firms_base_url.rstrip('/')}/area/csv/"
               f"{settings.firms_map_key}/VIIRS_SNPP_CROP/{box}/{day_range}")
        try:
            text = fetch_text(url)
            counts = Counter(row.get("acq_date") for row in csv.DictReader(io.StringIO(text))
                             if row.get("acq_date"))
            store.upsert_firms([(name, day, int(total_day)) for day, total_day in counts.items()])
            result[name] = sum(counts.values())
            total += sum(counts.values())
            if progress:
                progress(f"FIRMS {name}: {sum(counts.values())} focos en {day_range} dias")
        except CollectorError as exc:
            result[name] = f"error: {exc}"
            errors.append(name)
    store.record_run("firms", "incremental", not errors, total, "; ".join(errors))
    return result


# ---------------------------------------------------------------------- #
# Refresco incremental (scheduler y dashboard)
# ---------------------------------------------------------------------- #
def update_recent(store: Optional[Store] = None, lookback_days: Optional[int] = None,
                   progress: Progress = None) -> dict:
    """Refresca los ultimos dias de todas las fuentes de forma idempotente.

    La ventana corta permite capturar eventos que llegan con retraso o
    que se actualizan (tormentas que ganan entradas Kp, etc.).
    """
    target = store or default_store
    lookback = max(1, lookback_days or settings.collect_lookback_days)
    today = date.today()
    window_start = today - timedelta(days=lookback - 1)

    donki = backfill_donki(target, window_start, today, kind="incremental", progress=progress)
    eonet = backfill_eonet(target, window_start, today, kind="incremental", progress=progress)
    climate_start = today - timedelta(days=lookback + 9)
    open_meteo = backfill_open_meteo(target, climate_start, today, kind="incremental", progress=progress)
    firms = update_firms(target, days=min(10, lookback + 7), progress=progress)

    return {
        "window": {"from": window_start.isoformat(), "to": today.isoformat()},
        "donki": donki,
        "eonet": eonet,
        "open_meteo": open_meteo,
        "firms": firms,
    }
