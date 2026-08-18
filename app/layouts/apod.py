"""Layout de la pestana APOD (Astronomy Picture of the Day)."""
from __future__ import annotations

from datetime import date

import dash_bootstrap_components as dbc
from dash import dcc, html


def build_apod_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Card(dbc.CardBody([
                    html.Div("Fecha APOD", className="section-title mb-3"),
                    dcc.DatePickerSingle(
                        id="apod-date",
                        min_date_allowed=date(1995, 6, 16),
                        max_date_allowed=date.today(),
                        date=date.today(),
                        display_format="YYYY-MM-DD",
                        className="mb-3 d-block",
                    ),
                    dbc.Button(
                        [html.Span("\u25b6", className="me-2"), "Obtener APOD"],
                        id="apod-submit", color="primary", className="w-100",
                    ),
                ]), className="apod-card"),
            ], width=3),
            dbc.Col([
                html.H5(id="apod-title", children="--",
                        style={"color": "#e8eaf6", "fontWeight": "700"}),
                html.P([
                    html.Strong("Fecha: ", style={"color": "#64ffda"}),
                    html.Span(id="apod-date-text", children="--"),
                    "  \u2022  ",
                    html.Strong("Autor: ", style={"color": "#64ffda"}),
                    html.Span(id="apod-copyright", children="--"),
                ], className="text-muted small mt-2"),
            ], width=9),
        ], className="mb-3"),

        html.Div(id="apod-media", className="text-center mb-4"),

        dbc.Card(dbc.CardBody([
            html.Div("Explicación", className="section-title"),
            html.P(id="apod-explanation", children="--",
                   className="small", style={"color": "#b0bec5", "lineHeight": "1.7"}),
        ]), className="apod-card"),
    ])
