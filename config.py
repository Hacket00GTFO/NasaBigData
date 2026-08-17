"""Configuracion central de la aplicacion.

Carga las variables desde el archivo .env usando python-dotenv y las expone
como atributos tipados de un dataclass Settings. Si falta .env, se usan
valores por defecto seguros (DEMO_KEY) para que la app pueda arrancar.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Carga el .env del directorio del proyecto (si existe)
load_dotenv()


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None and value.strip() != "" else default


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
    nasa_api_key: str = field(default_factory=lambda: _get_env("NASA_API_KEY", "DEMO_KEY"))
    nasa_api_base_url: str = field(default_factory=lambda: _get_env("NASA_API_BASE_URL", "https://api.nasa.gov"))
    eonet_base_url: str = field(default_factory=lambda: _get_env("EONET_BASE_URL", "https://eonet.gsfc.nasa.gov/api/v3"))

    # Rangos por defecto (dias hacia atras)
    default_donki_days: int = field(default_factory=lambda: _get_env_int("DEFAULT_DONKI_DAYS", 30))
    default_eonet_days: int = field(default_factory=lambda: _get_env_int("DEFAULT_EONET_DAYS", 180))
    default_neo_days: int = field(default_factory=lambda: _get_env_int("DEFAULT_NEO_DAYS", 7))

    # Cache
    cache_timeout: int = field(default_factory=lambda: _get_env_int("CACHE_TIMEOUT", 3600))

    # Servidor
    flask_port: int = field(default_factory=lambda: _get_env_int("FLASK_PORT", 8050))
    flask_debug: bool = field(default_factory=lambda: _get_env_bool("FLASK_DEBUG", True))

    @property
    def user_agent(self) -> str:
        return "NasaBigDataDashboard/1.0"

    @property
    def is_configured(self) -> bool:
        """True si el usuario ha puesto una key real (no DEMO_KEY)."""
        return self.nasa_api_key not in ("DEMO_KEY", "", None)


settings = Settings()
