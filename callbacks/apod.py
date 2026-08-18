"""Callbacks de la pestana APOD (Astronomy Picture of the Day)."""
from __future__ import annotations

import dash
from dash import Input, Output, State, html

from app.nasa_client import NasaApiClient, NasaApiError
from app.stats import apod_summary


def register(app: dash.Dash) -> None:

    @app.callback(
        Output("apod-title", "children"),
        Output("apod-date-text", "children"),
        Output("apod-copyright", "children"),
        Output("apod-explanation", "children"),
        Output("apod-media", "children"),
        Input("apod-submit", "n_clicks"),
        State("apod-date", "date"),
        prevent_initial_call=False,
    )
    def update_apod(n_clicks, apod_date):
        defaults = ("--", "--", "--", "Pulsa 'Obtener APOD'.", html.Div())
        if not apod_date:
            return defaults

        client = NasaApiClient()
        try:
            data = client.get_apod(date=apod_date)
        except NasaApiError as exc:
            return ("Error", apod_date, "--", f"Error NASA: {exc}", html.Div())

        info = apod_summary(data)
        media = html.Div()
        if info["media_type"] == "image":
            media = html.Img(
                src=info["hdurl"] or info["url"],
                className="apod-img img-fluid",
            )
        elif info["media_type"] == "video":
            media = html.Iframe(
                src=info["url"], className="w-100",
                style={"height": "500px", "border": "none", "borderRadius": "12px"},
            )

        return (
            info["title"],
            info["date"],
            info["copyright"],
            info["explanation"],
            media,
        )
