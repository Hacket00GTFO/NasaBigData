"""Paquete de callbacks del dashboard."""
from __future__ import annotations

import dash


def register_all_callbacks(app: dash.Dash) -> None:
    """Registra todos los callbacks de la aplicacion."""
    from callbacks import filters, donki, eonet, asteroids, apod

    filters.register(app)
    donki.register(app)
    eonet.register(app)
    asteroids.register(app)
    apod.register(app)
