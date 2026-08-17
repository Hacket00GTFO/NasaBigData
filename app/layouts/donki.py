"""Layout de la pestana Clima Espacial (DONKI)."""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


def build_donki_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("CME", className="text-muted"),
                html.H4(id="donki-stat-cme", children="--"),
            ]), className="text-center"), width=2),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Flares (FLR)", className="text-muted"),
                html.H4(id="donki-stat-flr", children="--"),
            ]), className="text-center"), width=2),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Tormentas geomag. (GST)", className="text-muted"),
                html.H4(id="donki-stat-gst", children="--"),
            ]), className="text-center"), width=2),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("Kp máximo", className="text-muted"),
                html.H4(id="donki-stat-kp", children="--"),
            ]), className="text-center"), width=2),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("SEP", className="text-muted"),
                html.H4(id="donki-stat-sep", children="--"),
            ]), className="text-center"), width=2),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H6("HSS", className="text-muted"),
                html.H4(id="donki-stat-hss", children="--"),
            ]), className="text-center"), width=2),
        ], className="mb-4 g-3"),

        html.H5("Eventos por tipo"),
        dcc.Graph(id="donki-bar-types", style={"height": "320px"}),
        html.Hr(),
        html.H5("Serie temporal de eventos"),
        dcc.Graph(id="donki-time-series", style={"height": "380px"}),
        html.Hr(),
        dbc.Row([
            dbc.Col([
                html.H5("Distribución de flares por clase"),
                dcc.Graph(id="donki-flare-classes", style={"height": "320px"}),
            ], width=6),
            dbc.Col([
                html.H5("Eventos recientes"),
                html.Div(id="donki-recent-table"),
            ], width=6),
        ]),
    ])
