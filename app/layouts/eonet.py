"""Layout de la pestana Eventos Terrestres (EONET)."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


def _stat(value_id: str, title: str) -> dbc.Card:
    return dbc.Card(dbc.CardBody([
        html.H6(title),
        html.H4(id=value_id, children="--"),
    ]), className="stat-card")


def build_eonet_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col(_stat("eonet-stat-total", "Total eventos"), width=3),
            dbc.Col(_stat("eonet-stat-cats", "Categorías"), width=3),
            dbc.Col(_stat("eonet-stat-sources", "Fuentes"), width=3),
            dbc.Col(_stat("eonet-stat-top", "Categoría top"), width=3),
        ], className="mb-4 g-3"),

        html.Div("Distribución por categoría", className="section-title"),
        dcc.Graph(id="eonet-bar-categories", style={"height": "340px"}),

        html.Div("Evolución temporal", className="section-title"),
        dcc.Graph(id="eonet-time-series", style={"height": "380px"}),

        html.Div("Mapa de eventos", className="section-title"),
        dcc.Graph(id="eonet-map", style={"height": "560px"}),
    ])
