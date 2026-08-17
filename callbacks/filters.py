"""Callbacks de filtros globales y carga de datos compartidos.

- Al pulsar 'Consultar' descarga DONKI, EONET y NeoWs segun los rangos.
- Actualiza las KPI cards superiores.
- Renderiza el contenido de la pestaña activa.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Tuple

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html, no_update

from app.nasa_client import NasaApiClient, NasaApiError
from app.layouts.donki import build_donki_layout
from app.layouts.eonet import build_eonet_layout
from app.layouts.asteroids import build_asteroids_layout
from app.layouts.apod import build_apod_layout


def register(app: dash.Dash) -> None:

    @app.callback(
        Output("store-donki", "data"),
        Output("store-eonet", "data"),
        Output("store-neo", "data"),
        Output("filter-status", "children"),
        Input("filter-submit", "n_clicks"),
        State("filter-donki-range", "start_date"),
        State("filter-donki-range", "end_date"),
        State("filter-eonet-range", "start_date"),
        State("filter-eonet-range", "end_date"),
        State("filter-neo-range", "start_date"),
        State("filter-neo-range", "end_date"),
        prevent_initial_call=False,
    )
    def fetch_data(n_clicks, donki_s, donki_e, eonet_s, eonet_e, neo_s, neo_e):
        """Descarga datos al pulsar 'Consultar' (y al cargar la app)."""
        if not all([donki_s, donki_e, eonet_s, eonet_e, neo_s, neo_e]):
            return None, None, None, "Completa todos los rangos de fechas."

        # Validar rango NeoWs (max 7 dias)
        try:
            ns = datetime.fromisoformat(neo_s)
            ne = datetime.fromisoformat(neo_e)
        except ValueError:
            return None, None, None, "Fechas de asteroides inválidas."
        if (ne - ns).days > 7:
            # Recortar a 7 dias desde el inicio
            neo_e = (ns + timedelta(days=7)).date().isoformat()
        if ne <= ns:
            return None, None, None, "Rango de asteroides inválido."

        client = NasaApiClient()
        status_parts = []
        donki_data, eonet_data, neo_data = None, None, None

        # DONKI
        try:
            donki_data = client.get_donki_all(donki_s, donki_e)
            total_donki = sum(len(v) for v in donki_data.values())
            status_parts.append(f"DONKI: {total_donki} eventos")
        except NasaApiError as exc:
            status_parts.append(f"DONKI: error ({exc})")

        # EONET - calcular dias
        try:
            es = datetime.fromisoformat(eonet_s)
            ee = datetime.fromisoformat(eonet_e)
            eonet_days = max(1, (ee - es).days)
            eonet_events = client.get_eonet_events(days=eonet_days)
            eonet_data = eonet_events
            status_parts.append(f"EONET: {len(eonet_events)} eventos")
        except NasaApiError as exc:
            status_parts.append(f"EONET: error ({exc})")

        # NeoWs
        try:
            neo_data = client.get_neo_feed(neo_s, neo_e)
            neo_count = sum(len(v) for v in neo_data.get("near_earth_objects", {}).values())
            status_parts.append(f"NEO: {neo_count} asteroides")
        except NasaApiError as exc:
            status_parts.append(f"NEO: error ({exc})")

        return donki_data, eonet_data, neo_data, " | ".join(status_parts)

    @app.callback(
        Output("kpi-cme", "children"),
        Output("kpi-flr", "children"),
        Output("kpi-gst", "children"),
        Output("kpi-neo", "children"),
        Input("store-donki", "data"),
        Input("store-neo", "data"),
    )
    def update_kpis(donki_data, neo_data):
        cme = flr = gst = neo = "--"
        if donki_data:
            cme = str(len(donki_data.get("CME", [])))
            flr = str(len(donki_data.get("FLR", [])))
            gst = str(len(donki_data.get("GST", [])))
        if neo_data:
            neo = str(sum(len(v) for v in neo_data.get("near_earth_objects", {}).values()))
        return cme, flr, gst, neo

    @app.callback(
        Output("tab-content", "children"),
        Input("tabs", "active_tab"),
    )
    def render_tab(active_tab):
        if active_tab == "tab-donki":
            return build_donki_layout()
        if active_tab == "tab-eonet":
            return build_eonet_layout()
        if active_tab == "tab-neo":
            return build_asteroids_layout()
        if active_tab == "tab-apod":
            return build_apod_layout()
        return html.Div("Pestaña desconocida")
