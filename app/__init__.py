"""Factory de la aplicacion Flask + Dash.

Crea el servidor Flask y monta la instancia de Dash sobre el.
Registra los layouts y los callbacks de cada pestaña.
"""
from __future__ import annotations

import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
from flask import Flask

from config import settings


def create_app() -> dash.Dash:
    """Crea y configura la aplicacion Dash."""
    server = Flask(__name__)

    # Tema Bootstrap: MATERIA es limpio y moderno
    app = dash.Dash(
        __name__,
        server=server,
        external_stylesheets=[dbc.themes.MATERIA],
        suppress_callback_exceptions=True,
        title="Dashboard NASA POWER",
        update_title="Consultando NASA...",
    )

    # Import diferido para evitar ciclos
    from app.layouts.main import build_main_layout
    from callbacks import register_all_callbacks

    app.layout = build_main_layout()
    register_all_callbacks(app)

    return app
