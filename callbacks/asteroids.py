"""Callbacks de la pestana Asteroides (NeoWs)."""
from __future__ import annotations

import dash
import dash.dash_table as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html

from app.stats import neo_daily_counts, neo_flatten, neo_summary, neo_closest

_DARK_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e8eaf6", size=12),
    margin=dict(l=40, r=20, t=50, b=40),
)


def register(app: dash.Dash) -> None:

    @app.callback(
        Output("neo-stat-total", "children"),
        Output("neo-stat-hazard", "children"),
        Output("neo-stat-miss", "children"),
        Output("neo-stat-vel", "children"),
        Output("neo-daily-bar", "figure"),
        Output("neo-diameter-hist", "figure"),
        Output("neo-hazard-pie", "figure"),
        Output("neo-closest-table", "children"),
        Input("store-neo", "data"),
    )
    def update_neo(neo_data):
        empty = go.Figure()
        empty.update_layout(title="Sin datos — pulsa Consultar", **_DARK_LAYOUT)
        defaults = ("--", "--", "--", "--", empty, empty, empty,
                    html.Div("Sin datos.", className="text-muted p-3"))
        if not neo_data:
            return defaults

        flat = neo_flatten(neo_data)
        if flat.empty:
            return defaults

        s = neo_summary(flat)
        total = str(s["total"])
        hazard = str(s["hazardous"])
        miss = f"{s['miss_min']:,.0f}" if s["miss_min"] else "--"
        vel = f"{s['vel_med']:,.0f}" if s["vel_med"] else "--"

        # Barras por dia
        daily = neo_daily_counts(neo_data)
        fig_daily = go.Figure()
        if not daily.empty:
            fig_daily.add_trace(go.Bar(
                x=daily["date"], y=daily["count"],
                marker_color="#66bb6a", marker_line_width=0,
            ))
        fig_daily.update_layout(
            title="NEOs por día", **_DARK_LAYOUT,
            xaxis_title="Fecha", yaxis_title="Número",
        )

        # Histograma de diametros
        diam = ((flat["diameter_min_m"] + flat["diameter_max_m"]) / 2).dropna()
        fig_hist = go.Figure()
        if not diam.empty:
            fig_hist.add_trace(go.Histogram(
                x=diam, nbinsx=30, marker_color="#42a5f5",
                marker_line_width=0,
            ))
        fig_hist.update_layout(
            title="Distribución de diámetros (m)", **_DARK_LAYOUT,
            xaxis_title="Diámetro (m)", yaxis_title="Frecuencia",
        )

        # Pie peligrosos vs no
        fig_pie = go.Figure()
        if s["total"] > 0:
            fig_pie.add_trace(go.Pie(
                labels=["Peligrosos", "No peligrosos"],
                values=[s["hazardous"], s["no_hazardous"]],
                marker=dict(colors=["#fc3d21", "#66bb6a"]),
                hole=0.5,
                textfont=dict(color="#e8eaf6"),
            ))
        fig_pie.update_layout(
            title="Peligrosos vs no peligrosos", **_DARK_LAYOUT,
        )

        # Tabla mas cercanos
        closest = neo_closest(flat, limit=10)
        if closest.empty:
            table = html.Div("Sin datos de aproximación.", className="text-muted p-3")
        else:
            disp = closest.copy()
            disp["miss_km"] = disp["miss_km"].map(lambda v: f"{v:,.0f}")
            disp["velocity_kmh"] = disp["velocity_kmh"].map(lambda v: f"{v:,.0f}")
            disp["diameter_max_m"] = disp["diameter_max_m"].map(lambda v: f"{v:.1f}")
            disp["hazardous"] = disp["hazardous"].map(lambda v: "Sí" if v else "No")
            disp.columns = ["Nombre", "Fecha", "Diámetro máx (m)", "Dist. (km)", "Velocidad (km/h)", "Peligroso"]
            table = dt.DataTable(
                data=disp.to_dict("records"),
                columns=[{"name": c, "id": c} for c in disp.columns],
                style_table={"overflowX": "auto"},
                style_cell={
                    "textAlign": "left", "padding": "6px", "fontSize": "12px",
                    "backgroundColor": "#1a2033", "color": "#e8eaf6",
                    "border": "1px solid #2a3149",
                },
                style_header={
                    "fontWeight": "bold", "backgroundColor": "#131826",
                    "color": "#64ffda", "border": "1px solid #2a3149",
                },
            )

        return total, hazard, miss, vel, fig_daily, fig_hist, fig_pie, table
