"""Layout de la pestana Asteroides (NeoWs)."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


def build_asteroids_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Total NEOs", className="text-muted"),
                html.H4(id="neo-stat-total", children="--"),
            ]), className="text-center"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Peligrosos", className="text-muted"),
                html.H4(id="neo-stat-hazard", children="--"),
            ]), className="text-center"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Dist. mín (km)", className="text-muted"),
                html.H4(id="neo-stat-miss", children="--", className="fs-6"),
            ]), className="text-center"), width=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Vel. media (km/h)", className="text-muted"),
                html.H4(id="neo-stat-vel", children="--", className="fs-6"),
            ]), className="text-center"), width=3),
        ], className="mb-4 g-3"),

        html.H5("NEOs por día"),
        dcc.Graph(id="neo-daily-bar", style={"height": "300px"}),
        html.Hr(),
        dbc.Row([
            dbc.Col([
                html.H5("Distribución de diámetros (m)"),
                dcc.Graph(id="neo-diameter-hist", style={"height": "340px"}),
            ], width=6),
            dbc.Col([
                html.H5("Peligrosos vs no peligrosos"),
                dcc.Graph(id="neo-hazard-pie", style={"height": "340px"}),
            ], width=6),
        ]),
        html.Hr(),
        html.H5("Asteroides más cercanos"),
        html.Div(id="neo-closest-table"),
    ])
