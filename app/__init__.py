"""Factory de la aplicacion Flask + Dash.

Crea el servidor Flask y monta la instancia de Dash sobre el.
Registra los layouts y los callbacks de cada pestaña.
Usa el tema DARKLY de Bootstrap combinado con custom.css para
el aspecto espacial oscuro.
"""
from __future__ import annotations

import os

import dash
from flask import Flask

from config import settings

# Ruta absoluta a la carpeta assets (relativa a este archivo)
_ASSETS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def create_app() -> dash.Dash:
    """Crea y configura la aplicacion Dash."""
    server = Flask(__name__)

    import dash_bootstrap_components as dbc

    app = dash.Dash(
        __name__,
        server=server,
        external_stylesheets=[dbc.themes.DARKLY],
        suppress_callback_exceptions=True,
        title="Dashboard NASA",
        update_title="Consultando NASA...",
        assets_folder=_ASSETS_PATH,
    )

    from app.layouts.main import build_main_layout
    from callbacks import register_all_callbacks

    app.layout = build_main_layout()
    register_all_callbacks(app)

    return app
