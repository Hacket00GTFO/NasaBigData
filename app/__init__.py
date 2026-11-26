"""Factory de la aplicacion Flask (sin Dash).

Sirve el frontend estatico (HTML/CSS/JS) desde static/ y expone
los endpoints REST en /api/* definidos en app.api.
"""
from __future__ import annotations

import os

from flask import Flask, send_from_directory

from config import settings

_STATIC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def create_app() -> Flask:
    """Crea y configura la aplicacion Flask."""
    app = Flask(__name__, static_folder=_STATIC_PATH, static_url_path="/static")

    # Registrar blueprint de la API
    from app.api import api_bp
    app.register_blueprint(api_bp)

    # Dataset local del pipeline de predicciones y tareas programadas
    from app.db import store
    store.init()
    from app.scheduler import start_scheduler
    start_scheduler()

    # Ruta raiz: servir index.html
    @app.route("/")
    def index():
        return send_from_directory(_STATIC_PATH, "index.html")

    return app
