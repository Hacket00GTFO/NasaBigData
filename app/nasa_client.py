"""Cliente HTTP para los endpoints del portal api.nasa.gov.

Cubre:
- DONKI (Space Weather Database): CME, FLR, GST, SEP, HSS, MPC, RBE
- EONET (Earth Observations): events, categories, sources
- NeoWs (Near Earth Objects): feed, stats, browse
- APOD (Astronomy Picture of the Day)

Incluye:
- API key inyectada en cada request (DEMO_KEY por defecto).
- Cache en memoria con TTL configurable.
- Reintentos con backoff exponencial ante errores transitorios.
- Manejo claro de errores de rate limit (HTTP 429).
"""
from __future__ import annotations

import time
import threading
from typing import Dict, List, Optional, Tuple

import requests

from config import settings


class NasaApiError(Exception):
    """Error devuelto por la API de NASA."""


class NasaApiClient:
    """Cliente para el portal api.nasa.gov con cache y reintentos."""

    def __init__(self, timeout: int = 60, max_retries: int = 3):
        self.base_url = settings.nasa_api_base_url.rstrip("/")
        self.eonet_url = settings.eonet_base_url.rstrip("/")
        self.api_key = settings.nasa_api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._cache: Dict[Tuple, Tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------ #
    # Cache interno con TTL
    # ------------------------------------------------------------------ #
    def _cache_get(self, key: Tuple) -> Optional[object]:
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, value = entry
            if now - ts > settings.cache_timeout:
                self._cache.pop(key, None)
                return None
            return value

    def _cache_set(self, key: Tuple, value: object) -> None:
        with self._lock:
            self._cache[key] = (time.time(), value)

    # ------------------------------------------------------------------ #
    # Request base con reintentos
    # ------------------------------------------------------------------ #
    def _request(self, url: str, params: Dict) -> object:
        # Inyectar api_key si no esta presente
        params = dict(params)
        if "api_key" not in params and "api_key".lower() not in {k.lower() for k in params}:
            # EONET no usa api_key, solo inyectarla si la URL es de api.nasa.gov
            if url.startswith(self.base_url):
                params["api_key"] = self.api_key

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    raise NasaApiError(
                        "Rate limit excedido (HTTP 429). DEMO_KEY esta limitada a "
                        "30 req/hora y 50 req/dia. Solicita tu key en https://api.nasa.gov/"
                    )
                resp.raise_for_status()
                if resp.headers.get("content-type", "").startswith("application/json"):
                    return resp.json()
                return resp.content
            except NasaApiError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                wait = 2 ** attempt
                time.sleep(wait)
        raise NasaApiError(f"Fallo tras {self.max_retries} intentos: {last_exc}")

    # ------------------------------------------------------------------ #
    # DONKI - Space Weather Database
    # ------------------------------------------------------------------ #
    DONKI_TYPES = ["CME", "FLR", "GST", "SEP", "HSS", "MPC", "RBE"]

    def get_donki_events(self, event_type: str, start_date: str, end_date: str) -> List[dict]:
        """event_type: uno de DONKI_TYPES. Fechas en YYYY-MM-DD."""
        if event_type not in self.DONKI_TYPES:
            raise NasaApiError(f"Tipo DONKI invalido: {event_type}")
        key = ("donki", event_type, start_date, end_date)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/DONKI/{event_type}"
        params = {"startDate": start_date, "endDate": end_date}
        data = self._request(url, params)
        if not isinstance(data, list):
            raise NasaApiError(f"Respuesta DONKI inesperada: {type(data)}")
        self._cache_set(key, data)
        return data

    def get_donki_all(self, start_date: str, end_date: str) -> Dict[str, List[dict]]:
        """Descarga todos los tipos DONKI en una sola llamada (cacheado)."""
        key = ("donki", "all", start_date, end_date)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        result: Dict[str, List[dict]] = {}
        for et in self.DONKI_TYPES:
            try:
                result[et] = self.get_donki_events(et, start_date, end_date)
            except NasaApiError:
                result[et] = []
        self._cache_set(key, result)
        return result

    # ------------------------------------------------------------------ #
    # EONET - Earth Observations
    # ------------------------------------------------------------------ #
    def get_eonet_events(self, days: int = 180, status: str = "all",
                         category: Optional[str] = None) -> List[dict]:
        key = ("eonet", "events", days, status, category)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        url = f"{self.eonet_url}/events"
        params: Dict = {"days": days}
        if status and status != "all":
            params["status"] = status
        if category:
            params["category"] = category
        data = self._request(url, params)
        if not isinstance(data, dict) or "events" not in data:
            raise NasaApiError("Respuesta EONET inesperada")
        events = data["events"]
        self._cache_set(key, events)
        return events

    def get_eonet_categories(self) -> List[dict]:
        key = ("eonet", "categories",)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        data = self._request(f"{self.eonet_url}/categories", {})
        if not isinstance(data, dict) or "categories" not in data:
            return []
        cats = data["categories"]
        self._cache_set(key, cats)
        return cats

    # ------------------------------------------------------------------ #
    # NeoWs - Near Earth Objects
    # ------------------------------------------------------------------ #
    def get_neo_feed(self, start_date: str, end_date: str) -> dict:
        """Feed de NEOs. Maximo 7 dias entre start y end (YYYY-MM-DD)."""
        key = ("neo", "feed", start_date, end_date)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        url = f"{self.base_url}/neo/rest/v1/feed"
        params = {"start_date": start_date, "end_date": end_date}
        data = self._request(url, params)
        if not isinstance(data, dict):
            raise NasaApiError("Respuesta NeoWs inesperada")
        self._cache_set(key, data)
        return data

    def get_neo_stats(self) -> dict:
        key = ("neo", "stats",)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        data = self._request(f"{self.base_url}/neo/rest/v1/stats", {})
        if not isinstance(data, dict):
            return {}
        self._cache_set(key, data)
        return data

    # ------------------------------------------------------------------ #
    # APOD - Astronomy Picture of the Day
    # ------------------------------------------------------------------ #
    def get_apod(self, date: Optional[str] = None, count: Optional[int] = None) -> dict:
        """date: YYYY-MM-DD. count: numero aleatorio de imagenes."""
        key = ("apod", date, count)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        url = f"{self.base_url}/planetary/apod"
        params: Dict = {}
        if date:
            params["date"] = date
        if count is not None:
            params["count"] = count
        data = self._request(url, params)
        if not isinstance(data, dict):
            raise NasaApiError("Respuesta APOD inesperada")
        self._cache_set(key, data)
        return data


# Instancia compartida
nasa_client = NasaApiClient()
