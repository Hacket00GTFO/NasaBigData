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

# Plantilla oscura comun para todos los graficos
_DARK_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e8eaf6", size=12),
    margin=dict(l=40, r=20, t=50, b=40),
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
        empty.update_layout(title="Sin datos — pulsa Consultar", **_DARK_LAYOUT)
        defaults = ("--", "--", "--", "--", "--", "--", empty, empty, empty,
                    html.Div("Pulsa 'Consultar'.", className="text-muted p-3"))

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
        colors = ["#fc3d21", "#ffb74d", "#42a5f5", "#ab47bc",
                  "#66bb6a", "#8d6e63", "#26a69a"]
        fig_bar.add_trace(go.Bar(
            x=list(counts.keys()), y=list(counts.values()),
            marker_color=colors[:len(counts)],
            marker_line_width=0,
        ))
        fig_bar.update_layout(
            title="Conteo de eventos por tipo", **_DARK_LAYOUT,
            xaxis_title="Tipo", yaxis_title="Eventos",
        )

        # Serie temporal
        ts = donki_time_series(donki_data)
        fig_ts = go.Figure()
        if not ts.empty:
            line_colors = ["#fc3d21", "#ffb74d", "#42a5f5", "#ab47bc",
                           "#66bb6a", "#8d6e63", "#26a69a"]
            for i, col in enumerate(ts.columns):
                fig_ts.add_trace(go.Scatter(
                    x=ts.index, y=ts[col], name=col, mode="lines+markers",
                    line=dict(color=line_colors[i % len(line_colors)], width=2),
                    marker=dict(size=5),
                ))
        fig_ts.update_layout(
            title="Eventos por día y tipo", **_DARK_LAYOUT,
            xaxis_title="Fecha", yaxis_title="Eventos",
            hovermode="x unified", legend=dict(orientation="h", y=1.12),
        )

        # Flares por clase
        flare_classes = donki_flare_classes(donki_data.get("FLR", []))
        fig_flr = go.Figure()
        if flare_classes:
            order = ["X", "M", "C", "B", "A"]
            ordered = {k: flare_classes.get(k, 0) for k in order if k in flare_classes}
            fig_flr.add_trace(go.Bar(
                x=list(ordered.keys()), y=list(ordered.values()),
                marker_color=["#ff5252", "#ff9800", "#ffd54f", "#7986cb", "#90caf9"][:len(ordered)],
                marker_line_width=0,
            ))
        fig_flr.update_layout(
            title="Flares por clase (X>M>C>B>A)", **_DARK_LAYOUT,
            xaxis_title="Clase", yaxis_title="Número",
        )

        # Tabla recientes
        recent = donki_recent_events(donki_data, limit=20)
        if recent.empty:
            table = html.Div("Sin eventos recientes.", className="text-muted p-3")
        else:
            table = dt.DataTable(
                data=recent.to_dict("records"),
                columns=[{"name": c, "id": c} for c in recent.columns],
                style_table={"overflowX": "auto", "maxHeight": "320px", "overflowY": "auto"},
                style_cell={
                    "textAlign": "left", "padding": "6px", "fontSize": "12px",
                    "backgroundColor": "#1a2033", "color": "#e8eaf6",
                    "border": "1px solid #2a3149",
                },
                style_header={
                    "fontWeight": "bold", "backgroundColor": "#131826",
                    "color": "#64ffda", "border": "1px solid #2a3149",
                },
                page_size=15,
            )

        return cme, flr, gst, kp_str, sep, hss, fig_bar, fig_ts, fig_flr, table
