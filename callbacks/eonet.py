"""Callbacks de la pestana Eventos Terrestres (EONET)."""
from __future__ import annotations

import dash
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output

from app.stats import (
    eonet_counts_by_category, eonet_time_series, eonet_map_points,
    eonet_sources_count,
)


def register(app: dash.Dash) -> None:

    @app.callback(
        Output("eonet-stat-total", "children"),
        Output("eonet-stat-cats", "children"),
        Output("eonet-stat-sources", "children"),
        Output("eonet-stat-top", "children"),
        Output("eonet-bar-categories", "figure"),
        Output("eonet-time-series", "figure"),
        Output("eonet-map", "figure"),
        Input("store-eonet", "data"),
    )
    def update_eonet(eonet_events):
        empty = go.Figure()
        empty.update_layout(template="plotly_white", title="Sin datos. Pulsa 'Consultar'.")
        defaults = ("--", "--", "--", "--", empty, empty, empty)
        if not eonet_events:
            return defaults

        total = len(eonet_events)
        cat_counts = eonet_counts_by_category(eonet_events)
        src_counts = eonet_sources_count(eonet_events)
        n_cats = len(cat_counts)
        n_srcs = len(src_counts)
        top_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "--"

        # Barras por categoria
        fig_bar = go.Figure()
        if cat_counts:
            items = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
            fig_bar.add_trace(go.Bar(
                x=[k for k, _ in items], y=[v for _, v in items],
                marker_color="#26a69a",
            ))
        fig_bar.update_layout(
            title="Eventos por categoría",
            xaxis_title="Categoría", yaxis_title="Eventos",
            template="plotly_white",
        )

        # Serie temporal
        ts = eonet_time_series(eonet_events)
        fig_ts = go.Figure()
        if not ts.empty:
            for col in ts.columns:
                fig_ts.add_trace(go.Scatter(
                    x=ts.index, y=ts[col], name=col, stackgroup="one",
                ))
        fig_ts.update_layout(
            title="Eventos por día y categoría (apilado)",
            xaxis_title="Fecha", yaxis_title="Eventos",
            template="plotly_white", hovermode="x unified",
            legend=dict(orientation="h", y=1.1),
        )

        # Mapa
        map_df = eonet_map_points(eonet_events)
        fig_map = go.Figure()
        if not map_df.empty:
            fig_map = px.scatter_mapbox(
                map_df, lat="lat", lon="lon", color="category",
                hover_name="title", hover_data={"date": True, "lat": False, "lon": False},
                zoom=1, height=560,
            )
            fig_map.update_layout(
                mapbox_style="open-street-map",
                margin=dict(l=0, r=0, t=0, b=0),
                legend=dict(orientation="h", y=1.02),
            )
        else:
            fig_map.update_layout(
                template="plotly_white", title="Sin coordenadas disponibles.",
            )

        return str(total), str(n_cats), str(n_srcs), top_cat, fig_bar, fig_ts, fig_map
