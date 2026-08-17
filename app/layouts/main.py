"""Layout principal con sidebar de filtros y tabs de estadisticas."""
from __future__ import annotations

from datetime import date, timedelta

import dash_bootstrap_components as dbc
from dash import dcc, html

from config import settings


def _kpi_card(value_id: str, title: str, color: str = "primary") -> dbc.Card:
    return dbc.Card(
        dbc.CardBody([
            html.H6(title, className="card-title text-muted text-uppercase mb-1"),
            html.H4(id=value_id, children="--", className="card-text"),
        ]),
        color=color,
        inverse=True,
        className="text-center kpi-card",
    )


def build_sidebar() -> dbc.Col:
    """Barra lateral con filtros globales."""
    today = date.today()
    donki_start = today - timedelta(days=settings.default_donki_days)
    eonet_start = today - timedelta(days=settings.default_eonet_days)
    neo_start = today - timedelta(days=settings.default_neo_days)

    return dbc.Col(
        [
            html.H4("NASA API", className="text-center mb-3"),
            html.Hr(),
            html.Label("Rango DONKI (clima espacial)", className="fw-bold small"),
            dcc.DatePickerRange(
                id="filter-donki-range",
                min_date_allowed=date(2010, 1, 1),
                max_date_allowed=today,
                start_date=donki_start,
                end_date=today,
                display_format="YYYY-MM-DD",
                className="mb-3 d-block",
            ),
            html.Label("Rango EONET (eventos Tierra)", className="fw-bold small"),
            dcc.DatePickerRange(
                id="filter-eonet-range",
                min_date_allowed=date(2010, 1, 1),
                max_date_allowed=today,
                start_date=eonet_start,
                end_date=today,
                display_format="YYYY-MM-DD",
                className="mb-3 d-block",
            ),
            html.Label("Rango Asteroides (máx 7 días)", className="fw-bold small"),
            dcc.DatePickerRange(
                id="filter-neo-range",
                min_date_allowed=date(2010, 1, 1),
                max_date_allowed=today,
                start_date=neo_start,
                end_date=today,
                display_format="YYYY-MM-DD",
                className="mb-3 d-block",
            ),
            dbc.Button("Consultar", id="filter-submit", color="primary", className="w-100 mb-2"),
            html.Div(id="filter-status", className="small text-muted"),
            html.Hr(),
            html.Small(
                f"API Key: {settings.nasa_api_key}",
                className="text-muted d-block text-truncate",
            ),
            html.Small(
                "Solicita tu key en api.nasa.gov" if not settings.is_configured else "Key configurada",
                className="text-warning d-block" if not settings.is_configured else "text-success d-block",
            ),
        ],
        width=3,
        className="bg-light p-3 sidebar",
        style={"minHeight": "100vh"},
    )


def build_main_layout() -> html.Div:
    sidebar = build_sidebar()

    kpi_row = dbc.Row(
        [
            dbc.Col(_kpi_card("kpi-cme", "CMEs", "danger"), width=3),
            dbc.Col(_kpi_card("kpi-flr", "Flares solares", "warning"), width=3),
            dbc.Col(_kpi_card("kpi-gst", "Tormentas geomag.", "info"), width=3),
            dbc.Col(_kpi_card("kpi-neo", "Asteroides", "success"), width=3),
        ],
        className="mb-4 g-3",
    )

    tabs = dbc.Tabs(
        [
            dbc.Tab(label="Clima Espacial (DONKI)", tab_id="tab-donki"),
            dbc.Tab(label="Eventos Tierra (EONET)", tab_id="tab-eonet"),
            dbc.Tab(label="Asteroides (NeoWs)", tab_id="tab-neo"),
            dbc.Tab(label="APOD", tab_id="tab-apod"),
        ],
        id="tabs",
        active_tab="tab-donki",
        className="mb-3",
    )

    tab_content = html.Div(
        [
            dcc.Loading(dbc.Container(id="tab-content", fluid=True), type="circle"),
            # Stores para datos compartidos
            dcc.Store(id="store-donki", storage_type="session"),
            dcc.Store(id="store-eonet", storage_type="session"),
            dcc.Store(id="store-neo", storage_type="session"),
            dcc.Store(id="store-apod", storage_type="session"),
        ]
    )

    return dbc.Container(
        [
            dbc.Row(
                [
                    sidebar,
                    dbc.Col(
                        [
                            html.H2("Dashboard NASA — Estadísticas Multi-fuente", className="mb-3"),
                            kpi_row,
                            tabs,
                            tab_content,
                        ],
                        width=9,
                        className="p-4",
                    ),
                ],
                className="g-0",
            ),
        ],
        fluid=True,
        className="p-0",
    )
