"""Layout de la pestana Eventos Terrestres (EONET)."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


def build_eonet_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Total eventos", className="text-muted"),
                html.H4(id="eonet-stat-total", children="--"),
            ]), className="text-center"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Categorías", className="text-muted"),
                html.H4(id="eonet-stat-cats", children="--"),
            ]), className="text-center"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Fuentes", className="text-muted"),
                html.H4(id="eonet-stat-sources", children="--"),
            ]), className="text-center"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Categoría top", className="text-muted"),
                html.H4(id="eonet-stat-top", children="--", className="fs-6"),
            ]), className="text-center"), width=3),
        ], className="mb-4 g-3"),

        html.H5("Eventos por categoría"),
        dcc.Graph(id="eonet-bar-categories", style={"height": "340px"}),
        html.Hr(),
        html.H5("Serie temporal por categoría"),
        dcc.Graph(id="eonet-time-series", style={"height": "380px"}),
        html.Hr(),
        html.H5("Mapa de eventos"),
        dcc.Graph(id="eonet-map", style={"height": "560px"}),
    ])
