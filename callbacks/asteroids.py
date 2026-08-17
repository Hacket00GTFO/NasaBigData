"""Callbacks de la pestana Asteroides (NeoWs)."""
from __future__ import annotations

import dash
import dash.dash_table as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html

from app.stats import neo_daily_counts, neo_flatten, neo_summary, neo_closest


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
        empty.update_layout(template="plotly_white", title="Sin datos. Pulsa 'Consultar'.")
        defaults = ("--", "--", "--", "--", empty, empty, empty, "Sin datos.")
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
                x=daily["date"], y=daily["count"], marker_color="#43a047",
            ))
        fig_daily.update_layout(
            title="NEOs por día",
            xaxis_title="Fecha", yaxis_title="Número",
            template="plotly_white",
        )

        # Histograma de diametros (media min-max)
        diam = ((flat["diameter_min_m"] + flat["diameter_max_m"]) / 2).dropna()
        fig_hist = go.Figure()
        if not diam.empty:
            fig_hist.add_trace(go.Histogram(
                x=diam, nbinsx=30, marker_color="#1e88e5",
            ))
        fig_hist.update_layout(
            title="Distribución de diámetros (m)",
            xaxis_title="Diámetro (m)", yaxis_title="Frecuencia",
            template="plotly_white",
        )

        # Pie peligrosos vs no
        fig_pie = go.Figure()
        if s["total"] > 0:
            fig_pie.add_trace(go.Pie(
                labels=["Peligrosos", "No peligrosos"],
                values=[s["hazardous"], s["no_hazardous"]],
                marker=dict(colors=["#e53935", "#43a047"]),
                hole=0.4,
            ))
        fig_pie.update_layout(
            title="Peligrosos vs no peligrosos",
            template="plotly_white",
        )

        # Tabla mas cercanos
        closest = neo_closest(flat, limit=10)
        if closest.empty:
            table = html.Div("Sin datos de aproximación.")
        else:
            # Formatear columnas
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
                style_cell={"textAlign": "left", "padding": "6px", "fontSize": "12px"},
                style_header={"fontWeight": "bold", "backgroundColor": "#f5f5f5"},
            )

        return total, hazard, miss, vel, fig_daily, fig_hist, fig_pie, table
