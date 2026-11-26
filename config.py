"""Configuracion central de la aplicacion.

Carga las variables desde el archivo .env usando python-dotenv y las expone
como atributos tipados de un dataclass Settings. Si falta .env, se usan
valores por defecto seguros (DEMO_KEY) para que la app pueda arrancar.
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Carga el .env del directorio del proyecto (si existe)
load_dotenv(Path(__file__).resolve().parent / ".env")


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() != "" else default


def _get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # NASA API (api.nasa.gov)
    nasa_api_key: str = field(default_factory=lambda: _get_env("NASA_API_KEY", "DEMO_KEY"), repr=False)
    nasa_api_base_url: str = field(default_factory=lambda: _get_env("NASA_API_BASE_URL", "https://api.nasa.gov"))
    donki_base_url: str = field(default_factory=lambda: _get_env("DONKI_BASE_URL", "https://ccmc.gsfc.nasa.gov/DONKI-API/get"))
    apod_fallback_base_url: str = field(default_factory=lambda: _get_env("APOD_FALLBACK_BASE_URL", "https://science.nasa.gov/wp-json/wp/v2/apod-basic"))
    eonet_base_url: str = field(default_factory=lambda: _get_env("EONET_BASE_URL", "https://eonet.gsfc.nasa.gov/api/v3"))

    # Rangos por defecto (dias hacia atras)
    default_donki_days: int = field(default_factory=lambda: _get_env_int("DEFAULT_DONKI_DAYS", 30))
    default_eonet_days: int = field(default_factory=lambda: _get_env_int("DEFAULT_EONET_DAYS", 180))
    default_neo_days: int = field(default_factory=lambda: _get_env_int("DEFAULT_NEO_DAYS", 7))

    # Cache
    cache_timeout: int = field(default_factory=lambda: _get_env_int("CACHE_TIMEOUT", 3600))
    cache_max_entries: int = field(default_factory=lambda: _get_env_int("CACHE_MAX_ENTRIES", 512))

    # Servidor
    flask_port: int = field(default_factory=lambda: _get_env_int("FLASK_PORT", 8050))
    flask_debug: bool = field(default_factory=lambda: _get_env_bool("FLASK_DEBUG", False))

    # Pipeline de datos y predicciones
    db_path: str = field(default_factory=lambda: _get_env("DB_PATH", "state/nasa_big_data.db"))
    models_dir: str = field(default_factory=lambda: _get_env("MODELS_DIR", "state/models"))
    firms_map_key: str = field(default_factory=lambda: _get_env("FIRMS_MAP_KEY", ""), repr=False)
    firms_base_url: str = field(default_factory=lambda: _get_env("FIRMS_BASE_URL", "https://firms.modaps.eosdis.nasa.gov/api"))
    open_meteo_base_url: str = field(default_factory=lambda: _get_env("OPEN_METEO_BASE_URL", "https://archive-api.open-meteo.com/v1/archive"))
    donki_backfill_types: str = field(default_factory=lambda: _get_env("DONKI_BACKFILL_TYPES", "FLR,CME,GST,SEP"))
    donki_backfill_start: str = field(default_factory=lambda: _get_env("DONKI_BACKFILL_START", "2010-01-01"))
    eonet_backfill_start: str = field(default_factory=lambda: _get_env("EONET_BACKFILL_START", "2000-01-01"))
    collect_lookback_days: int = field(default_factory=lambda: _get_env_int("COLLECT_LOOKBACK_DAYS", 3))
    scheduler_enabled: bool = field(default_factory=lambda: _get_env_bool("SCHEDULER_ENABLED", True))
    scheduler_collect_hours: int = field(default_factory=lambda: _get_env_int("SCHEDULER_COLLECT_HOURS", 6))
    scheduler_train_hour: int = field(default_factory=lambda: _get_env_int("SCHEDULER_TRAIN_HOUR", 3))
    ml_test_days: int = field(default_factory=lambda: _get_env_int("ML_TEST_DAYS", 365))
    ml_min_train_rows: int = field(default_factory=lambda: _get_env_int("ML_MIN_TRAIN_ROWS", 400))
    ml_validation_days: int = field(default_factory=lambda: _get_env_int("ML_VALIDATION_DAYS", 90))
    ml_recency_halflife_days: int = field(default_factory=lambda: _get_env_int("ML_RECENCY_HALFLIFE_DAYS", 1095))
    eonet_model_categories: int = field(default_factory=lambda: _get_env_int("EONET_MODEL_CATEGORIES", 3))

    def __post_init__(self):
        self.default_donki_days = max(1, min(self.default_donki_days, 365))
        self.default_eonet_days = max(1, min(self.default_eonet_days, 3660))
        self.default_neo_days = max(1, min(self.default_neo_days, 7))
        self.cache_timeout = max(0, self.cache_timeout)
        self.cache_max_entries = max(1, self.cache_max_entries)
        self.collect_lookback_days = max(1, min(self.collect_lookback_days, 365))
        self.scheduler_collect_hours = max(1, min(self.scheduler_collect_hours, 168))
        self.scheduler_train_hour = max(0, min(self.scheduler_train_hour, 23))
        self.ml_test_days = max(30, min(self.ml_test_days, 3650))
        self.ml_min_train_rows = max(30, self.ml_min_train_rows)
        self.ml_validation_days = max(30, min(self.ml_validation_days, 365))
        self.ml_recency_halflife_days = max(0, min(self.ml_recency_halflife_days, 36500))
        self.eonet_model_categories = max(1, min(self.eonet_model_categories, 8))

    @property
    def user_agent(self) -> str:
        return "NasaBigDataDashboard/1.0"

    @property
    def is_configured(self) -> bool:
        """True si el usuario ha puesto una key real (no DEMO_KEY)."""
        return self.nasa_api_key not in ("DEMO_KEY", "", None)

    @property
    def donki_backfill_types_list(self) -> list[str]:
        """Tipos DONKI que se descargan para el dataset (CSV en .env)."""
        return [t.strip().upper() for t in self.donki_backfill_types.split(",") if t.strip()]

    @property
    def firms_enabled(self) -> bool:
        """True si el usuario configuro una map key de FIRMS."""
        return bool(self.firms_map_key.strip())

    @property
    def db_file(self) -> Path:
        """Ruta absoluta de la base SQLite del dataset."""
        path = Path(self.db_path)
        return path if path.is_absolute() else Path(__file__).resolve().parent / path

    @property
    def models_path(self) -> Path:
        """Ruta absoluta del directorio de modelos entrenados."""
        path = Path(self.models_dir)
        return path if path.is_absolute() else Path(__file__).resolve().parent / path


settings = Settings()
