"""Layout de la pestana Clima Espacial (DONKI)."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


def _stat(value_id: str, title: str) -> dbc.Card:
    return dbc.Card(dbc.CardBody([
        html.H6(title),
        html.H4(id=value_id, children="--"),
    ]), className="stat-card")


def build_donki_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col(_stat("donki-stat-cme", "CME"), width=2),
            dbc.Col(_stat("donki-stat-flr", "Flares"), width=2),
            dbc.Col(_stat("donki-stat-gst", "Tormentas"), width=2),
            dbc.Col(_stat("donki-stat-kp", "Kp máximo"), width=2),
            dbc.Col(_stat("donki-stat-sep", "SEP"), width=2),
            dbc.Col(_stat("donki-stat-hss", "HSS"), width=2),
        ], className="mb-4 g-3"),

        html.Div("Distribución de eventos", className="section-title"),
        dcc.Graph(id="donki-bar-types", style={"height": "320px"}),

        html.Div("Evolución temporal", className="section-title"),
        dcc.Graph(id="donki-time-series", style={"height": "380px"}),

        dbc.Row([
            dbc.Col([
                html.Div("Flares por clase", className="section-title"),
                dcc.Graph(id="donki-flare-classes", style={"height": "320px"}),
            ], width=6),
            dbc.Col([
                html.Div("Eventos recientes", className="section-title"),
                html.Div(id="donki-recent-table"),
            ], width=6),
        ]),
    ])
