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

_DARK_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e8eaf6", size=12),
    margin=dict(l=40, r=20, t=50, b=40),
)

# Paleta para categorias EONET
_CAT_COLORS = px.colors.qualitative.Bold


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
        empty.update_layout(title="Sin datos — pulsa Consultar", **_DARK_LAYOUT)
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
                marker_color=_CAT_COLORS[:len(items)],
                marker_line_width=0,
            ))
        fig_bar.update_layout(
            title="Eventos por categoría", **_DARK_LAYOUT,
            xaxis_title="Categoría", yaxis_title="Eventos",
        )

        # Serie temporal
        ts = eonet_time_series(eonet_events)
        fig_ts = go.Figure()
        if not ts.empty:
            for i, col in enumerate(ts.columns):
                fig_ts.add_trace(go.Scatter(
                    x=ts.index, y=ts[col], name=col, stackgroup="one",
                    line=dict(width=0.5, color=_CAT_COLORS[i % len(_CAT_COLORS)]),
                ))
        fig_ts.update_layout(
            title="Eventos por día y categoría (apilado)", **_DARK_LAYOUT,
            xaxis_title="Fecha", yaxis_title="Eventos",
            hovermode="x unified", legend=dict(orientation="h", y=1.12),
        )

        # Mapa
        map_df = eonet_map_points(eonet_events)
        fig_map = go.Figure()
        if not map_df.empty:
            fig_map = px.scatter_mapbox(
                map_df, lat="lat", lon="lon", color="category",
                hover_name="title", hover_data={"date": True, "lat": False, "lon": False},
                color_discrete_sequence=_CAT_COLORS,
                zoom=1, height=560,
            )
            fig_map.update_layout(
                mapbox_style="carto-darkmatter",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=0, b=0),
                legend=dict(orientation="h", y=1.02, bgcolor="rgba(0,0,0,0)"),
                font=dict(color="#e8eaf6"),
            )
        else:
            fig_map.update_layout(
                title="Sin coordenadas disponibles.", **_DARK_LAYOUT,
            )

        return str(total), str(n_cats), str(n_srcs), top_cat, fig_bar, fig_ts, fig_map
