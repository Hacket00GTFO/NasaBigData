"""Callbacks de la pestana Clima Espacial (DONKI)."""
from __future__ import annotations

import dash
import dash.dash_table as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html

from app.stats import (
    donki_counts_by_type, donki_time_series, donki_flare_classes,
    donki_gst_kp_stats, donki_recent_events,
)


def register(app: dash.Dash) -> None:

    @app.callback(
        Output("donki-stat-cme", "children"),
        Output("donki-stat-flr", "children"),
        Output("donki-stat-gst", "children"),
        Output("donki-stat-kp", "children"),
        Output("donki-stat-sep", "children"),
        Output("donki-stat-hss", "children"),
        Output("donki-bar-types", "figure"),
        Output("donki-time-series", "figure"),
        Output("donki-flare-classes", "figure"),
        Output("donki-recent-table", "children"),
        Input("store-donki", "data"),
    )
    def update_donki(donki_data):
        empty = go.Figure()
        empty.update_layout(template="plotly_white", title="Sin datos")
        defaults = ("--", "--", "--", "--", "--", "--", empty, empty, empty, "Pulsa 'Consultar'.")

        if not donki_data:
            return defaults

        counts = donki_counts_by_type(donki_data)
        cme = str(counts.get("CME", 0))
        flr = str(counts.get("FLR", 0))
        gst = str(counts.get("GST", 0))
        sep = str(counts.get("SEP", 0))
        hss = str(counts.get("HSS", 0))

        kp = donki_gst_kp_stats(donki_data.get("GST", []))
        kp_str = str(kp["max"]) if kp["n"] > 0 else "--"

        # Barras por tipo
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=list(counts.keys()), y=list(counts.values()),
            marker_color=["#e53935", "#fb8c00", "#1e88e5", "#8e24aa",
                          "#43a047", "#6d4c41", "#00897b"][:len(counts)],
        ))
        fig_bar.update_layout(
            title="Conteo de eventos por tipo",
            xaxis_title="Tipo", yaxis_title="Número de eventos",
            template="plotly_white",
        )

        # Serie temporal
        ts = donki_time_series(donki_data)
        fig_ts = go.Figure()
        if not ts.empty:
            for col in ts.columns:
                fig_ts.add_trace(go.Scatter(
                    x=ts.index, y=ts[col], name=col, mode="lines+markers",
                ))
        fig_ts.update_layout(
            title="Eventos por día y tipo",
            xaxis_title="Fecha", yaxis_title="Eventos",
            template="plotly_white", hovermode="x unified",
            legend=dict(orientation="h", y=1.1),
        )

        # Flares por clase
        flare_classes = donki_flare_classes(donki_data.get("FLR", []))
        fig_flr = go.Figure()
        if flare_classes:
            # Ordenar X, M, C, B, A
            order = ["X", "M", "C", "B", "A"]
            ordered = {k: flare_classes.get(k, 0) for k in order if k in flare_classes}
            fig_flr.add_trace(go.Bar(
                x=list(ordered.keys()), y=list(ordered.values()),
                marker_color=["#d32f2f", "#f57c00", "#fbc02d", "#7986cb", "#90caf9"][:len(ordered)],
            ))
        fig_flr.update_layout(
            title="Flares por clase (X>M>C>B>A)",
            xaxis_title="Clase", yaxis_title="Número",
            template="plotly_white",
        )

        # Tabla recientes
        recent = donki_recent_events(donki_data, limit=20)
        if recent.empty:
            table = html.Div("Sin eventos recientes.")
        else:
            table = dt.DataTable(
                data=recent.to_dict("records"),
                columns=[{"name": c, "id": c} for c in recent.columns],
                style_table={"overflowX": "auto", "maxHeight": "320px", "overflowY": "auto"},
                style_cell={"textAlign": "left", "padding": "4px", "fontSize": "12px"},
                style_header={"fontWeight": "bold", "backgroundColor": "#f5f5f5"},
                page_size=15,
            )

        return cme, flr, gst, kp_str, sep, hss, fig_bar, fig_ts, fig_flr, table
