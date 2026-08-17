"""Layout de la pestana APOD (Astronomy Picture of the Day)."""
from __future__ import annotations

from datetime import date

import dash_bootstrap_components as dbc
from dash import dcc, html


def build_apod_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Label("Fecha APOD", className="fw-bold"),
                dcc.DatePickerSingle(
                    id="apod-date",
                    min_date_allowed=date(1995, 6, 16),
                    max_date_allowed=date.today(),
                    date=date.today(),
                    display_format="YYYY-MM-DD",
                    className="mb-3 d-block",
                ),
                dbc.Button("Obtener APOD", id="apod-submit", color="primary", className="mb-3"),
            ], width=3),
            dbc.Col([
                html.H5(id="apod-title", children="--"),
                html.P([
                    html.Strong("Fecha: "), html.Span(id="apod-date-text", children="--"),
                    " | ",
                    html.Strong("Autor: "), html.Span(id="apod-copyright", children="--"),
                ], className="text-muted small"),
            ], width=9),
        ], className="mb-3"),
        html.Div(id="apod-media", className="text-center mb-3"),
        dbc.Card(dbc.CardBody([
            html.H6("Explicación", className="fw-bold"),
            html.P(id="apod-explanation", children="--", className="small"),
        ])),
    ])
