"""Layout principal con sidebar de filtros y tabs de estadisticas.

Diseno: tema espacial oscuro con navbar NASA, KPI cards con iconos,
sidebar estilizado y tabs con borde inferior cyan.
"""
from __future__ import annotations

from datetime import date, timedelta

import dash_bootstrap_components as dbc
from dash import dcc, html

from config import settings


# Iconos Unicode para KPIs (sin dependencias externas)
_KPI_ICONS = {
    "cme": "\u2604",      # cometa
    "flr": "\u2600",      # sol
    "gst": "\u26a1",      # rayo
    "neo": "\u26f2",      # montaña/cuerpo
}


def _kpi_card(value_id: str, title: str, icon: str, color: str = "primary") -> dbc.Card:
    return dbc.Card(
        dbc.CardBody([
            html.Span(icon, className="kpi-icon"),
            html.Div(title, className="kpi-label"),
            html.H4(id=value_id, children="--", className="kpi-value"),
        ]),
        className=f"kpi-card kpi-{color}",
    )


def _navbar() -> dbc.Navbar:
    return dbc.Navbar(
        dbc.Container([
            dbc.Row(
                [
                    dbc.Col(
                        html.Div([
                            html.Span("NASA", className="nasa-logo-badge"),
                            html.Span("Dashboard", className="ms-2"),
                        ], className="nasa-logo"),
                        className="align-items-center",
                    ),
                    dbc.Col(
                        html.Div([
                            html.Span(
                                "Key configurada" if settings.is_configured else "DEMO_KEY",
                                className=f"status-badge {'status-ok' if settings.is_configured else 'status-warn'}",
                            ),
                        ], className="text-end"),
                        width="auto",
                        className="ms-auto",
                    ),
                ],
                align="center",
                className="w-100",
            ),
        ], fluid=True),
        dark=True,
        color="dark",
        className="nasa-navbar",
    )


def _filter_section(title: str, date_picker_id: str, hint: str,
                    start: date, end: date, today: date) -> list:
    """Seccion de filtro con titulo, hint y DatePickerRange."""
    return [
        html.Div([
            html.Label(title, className="form-label"),
            html.Small(hint, className="d-block text-muted mb-1"),
        ]),
        dcc.DatePickerRange(
            id=date_picker_id,
            min_date_allowed=date(2010, 1, 1),
            max_date_allowed=today,
            start_date=start,
            end_date=end,
            display_format="YYYY-MM-DD",
            className="mb-3 d-block",
        ),
    ]


def build_sidebar() -> dbc.Col:
    """Barra lateral con filtros globales."""
    today = date.today()
    donki_start = today - timedelta(days=settings.default_donki_days)
    eonet_start = today - timedelta(days=settings.default_eonet_days)
    neo_start = today - timedelta(days=settings.default_neo_days)

    children = [
        html.Div([
            html.Span("\u25c8", style={"fontSize": "1.5rem", "color": "var(--accent-cyan)"}),
            html.H5("Panel de control", className="d-inline ms-2 mb-0"),
        ], className="mb-3"),
        html.Hr(),
    ]

    children += _filter_section(
        "Clima espacial (DONKI)", "filter-donki-range",
        "Eyecciones de masa coronal, flares, tormentas",
        donki_start, today, today,
    )
    children += _filter_section(
        "Eventos Tierra (EONET)", "filter-eonet-range",
        "Incendios, tormentas, volcanes, hielo",
        eonet_start, today, today,
    )
    children += _filter_section(
        "Asteroides (NeoWs)", "filter-neo-range",
        "Máximo 7 días (limitación de la API)",
        neo_start, today, today,
    )

    children += [
        dbc.Button(
            [html.Span("\u25b6", className="me-2"), "Consultar"],
            id="filter-submit", color="primary", className="w-100 mb-2",
        ),
        html.Div(id="filter-status", className="small mt-2"),
        html.Hr(),
        html.Div([
            html.Small("Powered by", className="text-muted d-block"),
            html.Small("api.nasa.gov", className="fw-bold"),
        ], className="text-center mt-3"),
    ]

    return dbc.Col(
        children,
        width=3,
        className="sidebar",
    )


def build_main_layout() -> html.Div:
    navbar = _navbar()
    sidebar = build_sidebar()

    kpi_row = dbc.Row(
        [
            dbc.Col(_kpi_card("kpi-cme", "CMEs", _KPI_ICONS["cme"], "danger"), width=3),
            dbc.Col(_kpi_card("kpi-flr", "Flares solares", _KPI_ICONS["flr"], "warning"), width=3),
            dbc.Col(_kpi_card("kpi-gst", "Tormentas geomag.", _KPI_ICONS["gst"], "info"), width=3),
            dbc.Col(_kpi_card("kpi-neo", "Asteroides", _KPI_ICONS["neo"], "success"), width=3),
        ],
        className="mb-4 g-3",
    )

    tabs = dbc.Tabs(
        [
            dbc.Tab(label="\u2604 Clima Espacial", tab_id="tab-donki"),
            dbc.Tab(label="\u25c8 Eventos Tierra", tab_id="tab-eonet"),
            dbc.Tab(label="\u26f2 Asteroides", tab_id="tab-neo"),
            dbc.Tab(label="\u25c6 APOD", tab_id="tab-apod"),
        ],
        id="tabs",
        active_tab="tab-donki",
        className="mb-3",
    )

    tab_content = html.Div(
        [
            dcc.Loading(
                dbc.Container(id="tab-content", fluid=True, className="p-0"),
                type="dot",
                color="var(--accent-cyan)",
            ),
            dcc.Store(id="store-donki", storage_type="session"),
            dcc.Store(id="store-eonet", storage_type="session"),
            dcc.Store(id="store-neo", storage_type="session"),
            dcc.Store(id="store-apod", storage_type="session"),
        ]
    )

    footer = html.Div(
        "Dashboard NASA — Estadísticas multi-fuente | DONKI · EONET · NeoWs · APOD",
        className="app-footer",
    )

    return html.Div([
        navbar,
        dbc.Container(
            dbc.Row(
                [
                    sidebar,
                    dbc.Col(
                        [
                            html.Div(
                                "Estadísticas Multi-fuente",
                                className="h3 mt-4 mb-1",
                                style={"color": "var(--text-bright)", "fontWeight": "700"},
                            ),
                            html.Div(
                                "Datos en tiempo real de la API de la NASA",
                                className="text-muted mb-4",
                            ),
                            kpi_row,
                            tabs,
                            tab_content,
                            footer,
                        ],
                        width=9,
                        className="p-4",
                    ),
                ],
                className="g-0",
            ),
            fluid=True,
            className="p-0",
        ),
    ])
