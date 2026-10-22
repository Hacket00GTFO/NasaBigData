"""Cliente NASA compartido: conexiones reutilizadas, caché TTL y concurrencia acotada."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date as Date
from email.utils import parsedate_to_datetime
import threading
import time
from urllib.parse import urlsplit

import requests

from config import settings


class NasaApiError(Exception):
    """Error público que nunca incluye la URL autenticada ni la API key."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


class NasaApiClient:
    DONKI_TYPES = ["CME", "FLR", "GST", "SEP", "HSS", "MPC", "RBE"]

    def __init__(self, timeout=20, max_retries=2):
        self.base_url = settings.nasa_api_base_url.rstrip("/")
        self.donki_url = settings.donki_base_url.rstrip("/")
        self.eonet_url = settings.eonet_base_url.rstrip("/")
        self.api_key = settings.nasa_api_key
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._cache = OrderedDict()
        self._inflight = {}
        self._cooldowns = {}
        self._lock = threading.Lock()
        self._local = threading.local()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="donki")

    @property
    def _session(self):
        # Cada trabajador conserva su propia Session y sus conexiones.
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
            self._local.session.headers.update({
                "User-Agent": settings.user_agent, "Accept": "application/json",
            })
        return self._local.session

    def _cached(self, key, loader):
        """Comparte solicitudes en curso para evitar descargas duplicadas."""
        with self._lock:
            now = time.monotonic()
            for expired in [k for k, (expires, _) in self._cache.items() if expires <= now]:
                del self._cache[expired]
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key][1]
            pending = self._inflight.get(key)
            owner = pending is None
            if owner:
                pending = self._inflight[key] = Future()
        if not owner:
            return pending.result()
        try:
            value = loader()
            with self._lock:
                if settings.cache_timeout:
                    self._cache[key] = (time.monotonic() + settings.cache_timeout, value)
                    while len(self._cache) > settings.cache_max_entries:
                        self._cache.popitem(last=False)
            pending.set_result(value)
            return value
        except Exception as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def _request(self, url, params):
        params = dict(params)
        is_nasa = url.startswith(self.base_url + "/")
        service = urlsplit(url).netloc
        if is_nasa:
            params["api_key"] = self.api_key
        for attempt in range(self.max_retries):
            with self._lock:
                remaining = self._cooldowns.get(service, 0) - time.monotonic()
            if remaining > 0:
                raise NasaApiError(f"Límite de consultas alcanzado. Reintenta en {int(remaining) + 1} segundos.", 429)
            try:
                with self._session.get(url, params=params, timeout=(5, self.timeout)) as resp:
                    if resp.status_code == 429:
                        raw = resp.headers.get("Retry-After", "60")
                        try:
                            delay = float(raw)
                        except ValueError:
                            try:
                                delay = parsedate_to_datetime(raw).timestamp() - time.time()
                            except (ValueError, TypeError, OverflowError):
                                delay = 60
                        delay = max(1, min(delay, 3600))
                        with self._lock:
                            self._cooldowns[service] = time.monotonic() + delay
                        raise NasaApiError(f"Límite de consultas alcanzado. Reintenta en {int(delay)} segundos.", 429)
                    if resp.status_code in (408, 500, 502, 503, 504):
                        if attempt + 1 < self.max_retries:
                            time.sleep(2 ** attempt)
                            continue
                    if resp.status_code >= 400:
                        if is_nasa and resp.status_code in (401, 403):
                            message = "NASA rechazó la API key. Revisa NASA_API_KEY en el servidor."
                        else:
                            message = f"El servicio respondió HTTP {resp.status_code}."
                        raise NasaApiError(message)
                    try:
                        return resp.json()
                    except ValueError:
                        raise NasaApiError("El servicio devolvió una respuesta JSON inválida.") from None
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == self.max_retries:
                    raise NasaApiError("No se pudo conectar con el servicio NASA en el tiempo disponible.") from None
                time.sleep(2 ** attempt)
            except requests.RequestException:
                raise NasaApiError("Error de comunicación con el servicio NASA.") from None

    def _get_json(self, key, url, params, expected, field=None, allow_null=False):
        def load():
            data = self._request(url, params)
            if allow_null and data is None:
                data = []
            if not isinstance(data, expected):
                raise NasaApiError("El servicio devolvió una estructura inesperada.")
            if field:
                if not isinstance(data.get(field), list if field in ("events", "categories") else dict):
                    raise NasaApiError("El servicio devolvió una estructura incompleta.")
                if field in ("events", "categories"):
                    return data[field]
            return data
        return self._cached(key, load)

    def get_donki_events(self, event_type, start_date, end_date):
        if event_type not in self.DONKI_TYPES:
            raise NasaApiError("Tipo DONKI inválido.")
        return self._get_json(("donki", event_type, start_date, end_date),
                              f"{self.donki_url}/{event_type}",
                              {"startDate": start_date, "endDate": end_date}, list, allow_null=True)

    def get_donki_all(self, start_date, end_date):
        """Devuelve datos disponibles y errores sin cachear fallos como ceros."""
        futures = {et: self._executor.submit(self.get_donki_events, et, start_date, end_date)
                   for et in self.DONKI_TYPES}
        data, errors = {}, {}
        for event_type, future in futures.items():
            try:
                data[event_type] = future.result()
            except NasaApiError as exc:
                errors[event_type] = str(exc)
        return data, errors

    def get_eonet_events(self, days=180, status="all", category=None, *, start_date=None, end_date=None):
        params = {"status": status}
        if start_date and end_date:
            params.update(start=start_date, end=end_date)
        else:
            params["days"] = days
        if category:
            params["category"] = category
        return self._get_json(("eonet", tuple(sorted(params.items()))), f"{self.eonet_url}/events",
                              params, dict, field="events")

    def get_eonet_categories(self):
        return self._get_json(("eonet", "categories"), f"{self.eonet_url}/categories", {}, dict, field="categories")

    def get_neo_feed(self, start_date, end_date):
        return self._get_json(("neo", start_date, end_date), f"{self.base_url}/neo/rest/v1/feed",
                              {"start_date": start_date, "end_date": end_date}, dict, field="near_earth_objects")

    def get_neo_stats(self):
        return self._get_json(("neo", "stats"), f"{self.base_url}/neo/rest/v1/stats", {}, dict)

    def get_apod(self, date=None, count=None):
        if date and count is not None:
            raise NasaApiError("APOD acepta fecha o cantidad, no ambos parámetros.")
        effective_date = date or (Date.today().isoformat() if count is None else None)
        params = {"date": effective_date} if effective_date else {"count": count}
        return self._get_json(("apod", effective_date, count), f"{self.base_url}/planetary/apod",
                              params, list if count is not None else dict)


nasa_client = NasaApiClient()
