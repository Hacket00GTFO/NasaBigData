"""Ingenieria de caracteristicas para los modelos de prediccion.

Construye series diarias desde el dataset SQLite y deriva retardos
(lags), medias moviles y componentes estacionales: ciclo solar de ~11
anos y dia del ano. Las filas quedan indexadas por dia continuo, con
los valores objetivo desplazados hacia el futuro (shift negativo).

Politica de nulos: el clima y FIRMS se rellenan hacia adelante (ffill)
porque operativamente se usa el ultimo valor conocido; los primeros
dias sin cobertura quedan con NaN y el entrenamiento los descarta.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional, Tuple
import json
import math

import numpy as np
import pandas as pd

from app.db import Store

LAGS = (1, 2, 3, 7, 14, 28)
ROLLS = (7, 28)

# Escala del flujo pico de flares en W/m2 por clase (log10 del prefijo).
_FLARE_BASE = {"A": -8.0, "B": -7.0, "C": -6.0, "M": -5.0, "X": -4.0}

# Columnas objetivo que nunca entran como features.
TARGET_COLS = ("flares_next", "flares_week", "flares_x_next", "events_next")


# ---------------------------------------------------------------------- #
# Series diarias desde la base
# ---------------------------------------------------------------------- #
def donki_daily(store: Store, event_type: str) -> pd.Series:
    """Eventos DONKI de un tipo por dia."""
    rows = store.donki_rows(event_type)
    if not rows:
        return pd.Series(dtype="float64")
    counts = Counter(day for day, _ in rows)
    series = pd.Series(counts, dtype="float64")
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def flare_class_daily(store: Store) -> pd.DataFrame:
    """Flares por dia y clase (columnas C, M, X, ...)."""
    rows = store.donki_rows("FLR")
    records = []
    for day, extra_json in rows:
        letter = "?"
        if extra_json:
            try:
                letter = json.loads(extra_json).get("top_class") or "?"
            except (ValueError, TypeError):
                pass
        records.append((day, letter))
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records, columns=["day", "letter"])
    df["day"] = pd.to_datetime(df["day"])
    return pd.crosstab(df["day"], df["letter"]).sort_index()


def flare_flux_daily(store: Store) -> pd.DataFrame:
    """Intensidad de los flares por dia, en log10 del flujo pico (W/m2).

    Un flare M5.3 tiene flujo ~5.3e-5 W/m2 (log10 = -4.3): captura que
    un M9.9 es casi un X1.0, algo que el conteo simple no ve.
    Devuelve flux_max y flux_sum por dia.
    """
    rows = store.donki_rows("FLR")
    records = []
    for day, extra_json in rows:
        if not extra_json:
            continue
        try:
            class_type = json.loads(extra_json).get("class") or ""
        except (ValueError, TypeError):
            continue
        letter, magnitude = class_type[:1].upper(), class_type[1:]
        base = _FLARE_BASE.get(letter)
        if base is None:
            continue
        try:
            number = float(magnitude) if magnitude else 1.0
        except ValueError:
            continue
        records.append((day, base + math.log10(max(number, 0.1))))
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records, columns=["day", "logflux"])
    df["day"] = pd.to_datetime(df["day"])
    grouped = df.groupby("day")["logflux"]
    return pd.DataFrame({"flux_max": grouped.max(), "flux_sum": grouped.sum()}).sort_index()


def days_since_last(days_with_event: pd.Series, cap: float = 180.0) -> pd.Series:
    """Dias transcurridos desde el ultimo dia con evento (tope 'cap').

    'days_with_event' es una serie diaria booleana/0-1 alineada al indice.
    """
    had = days_with_event.astype(bool).astype(int)
    groups = had.cumsum()
    since = days_with_event.index.to_series().groupby(groups).cumcount().astype(float)
    since = since.where(groups > 0, cap)  # antes del primer evento historico
    return since.clip(upper=cap)


def eonet_daily(store: Store, category: Optional[str] = None) -> pd.Series:
    """Eventos EONET por primer dia de geometria, opcionalmente por categoria."""
    rows = store.eonet_daily_counts(category)
    if not rows:
        return pd.Series(dtype="float64")
    series = pd.Series({day: float(n) for day, n in rows}, dtype="float64")
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def climate_daily(store: Store) -> pd.DataFrame:
    """Clima promedio entre regiones propensas a incendios, por dia."""
    rows = store.climate_rows()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["day", "t_max", "t_min", "precip", "wind_max"])
    df["day"] = pd.to_datetime(df["day"])
    return df.set_index("day").sort_index()


def firms_daily(store: Store) -> pd.Series:
    """Focos de incendio FIRMS (suma entre regiones) por dia."""
    rows = store.firms_daily_counts()
    if not rows:
        return pd.Series(dtype="float64")
    series = pd.Series({day: float(n) for day, n in rows}, dtype="float64")
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


# ---------------------------------------------------------------------- #
# Bloques reutilizables
# ---------------------------------------------------------------------- #
def _calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Componentes estacionales: dia del ano, mes y ciclo solar (~11 anos)."""
    doy = np.asarray(index.dayofyear, dtype=float)
    month = np.asarray(index.month, dtype=float)
    # Minimo del ciclo 24 en dic-2008; periodo medio ~132 meses.
    months_since = (index.year - 2008) * 12 + (index.month - 12)
    phase = (months_since % 132) / 132.0
    frame = pd.DataFrame(index=index)
    frame["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    frame["month_sin"] = np.sin(2 * np.pi * month / 12.0)
    frame["month_cos"] = np.cos(2 * np.pi * month / 12.0)
    frame["cycle_sin"] = np.sin(2 * np.pi * np.asarray(phase, dtype=float))
    frame["cycle_cos"] = np.cos(2 * np.pi * np.asarray(phase, dtype=float))
    return frame


def _lag_block(series: pd.Series, prefix: str, lags: Tuple[int, ...], rolls: Tuple[int, ...]) -> pd.DataFrame:
    """Retardos y medias moviles de una serie diaria.

    Las medias moviles incluyen el dia actual: al predecir manana ya se
    conoce el valor de hoy.
    """
    out = pd.DataFrame(index=series.index)
    for lag in lags:
        out[f"{prefix}_lag{lag}"] = series.shift(lag)
    for roll in rolls:
        out[f"{prefix}_roll{roll}"] = series.rolling(roll).mean()
    return out


# ---------------------------------------------------------------------- #
# Frames de entrenamiento
# ---------------------------------------------------------------------- #
def flare_frame(store: Store) -> pd.DataFrame:
    """Frame diario con features solares y tres objetivos:
    flares del dia siguiente, total de los proximos 7 dias y clase X
    del dia siguiente (clasificacion binaria).
    """
    flares = donki_daily(store, "FLR")
    if flares.empty:
        return pd.DataFrame()
    index = pd.date_range(flares.index.min(), flares.index.max(), freq="D")
    data = pd.DataFrame(index=index)
    data["flares"] = flares.reindex(index, fill_value=0.0)
    for event_type, column in (("CME", "cme"), ("GST", "gst"), ("SEP", "sep")):
        series = donki_daily(store, event_type)
        if not series.empty:
            data[column] = series.reindex(index, fill_value=0.0)
    classes = flare_class_daily(store)
    for letter, column in (("C", "flares_c"), ("M", "flares_m"), ("X", "flares_x")):
        if letter in classes.columns:
            data[column] = classes[letter].reindex(index, fill_value=0.0)
        else:
            data[column] = 0.0

    # Intensidad real de los flares (log10 del flujo pico en W/m2).
    flux = flare_flux_daily(store)
    if not flux.empty:
        flux = flux.reindex(index).fillna(0.0)
        data["flux_max"] = flux["flux_max"]
        data["flux_sum"] = flux["flux_sum"]
    # Memoria del ultimo flare clase X: los dias sin X se acumulan.
    data["days_since_x"] = days_since_last(data["flares_x"])

    blocks = [data, _calendar(index),
              _lag_block(data["flares"], "flares", LAGS, ROLLS),
              _lag_block(data["flares_x"], "flares_x", (1, 7), ()),
              _lag_block(data["flares_m"], "flares_m", (1, 7), ())]
    if "flux_max" in data.columns:
        blocks.append(_lag_block(data["flux_max"], "flux_max", (1, 7), (7,)))
        blocks.append(_lag_block(data["flux_sum"], "flux_sum", (1,), (7,)))
    if "cme" in data.columns:
        blocks.append(_lag_block(data["cme"], "cme", (1, 2, 7), (7,)))
    if "gst" in data.columns:
        blocks.append(_lag_block(data["gst"], "gst", (1,), ()))
    if "sep" in data.columns:
        blocks.append(_lag_block(data["sep"], "sep", (1, 7), ()))

    frame = pd.concat(blocks, axis=1)

    # Objetivos (futuro) y baseline del modelo semanal (pasado).
    frame["flares_next"] = data["flares"].shift(-1)
    frame["flares_week"] = sum(data["flares"].shift(-k) for k in range(1, 8))
    frame["flares_week_past"] = data["flares"].rolling(7).sum()
    frame["flares_x_next"] = (data["flares_x"].shift(-1) > 0).astype(float)
    return frame


def eonet_frame(store: Store, category: str) -> pd.DataFrame:
    """Frame diario de una categoria EONET con clima de regiones propensas.

    Objetivo: numero de eventos de la categoria al dia siguiente.
    """
    events = eonet_daily(store, category)
    if events.empty:
        return pd.DataFrame()
    index = pd.date_range(events.index.min(), events.index.max(), freq="D")
    data = pd.DataFrame(index=index)
    data["events"] = events.reindex(index, fill_value=0.0)

    all_events = eonet_daily(store, None)
    if not all_events.empty:
        data["all_events"] = all_events.reindex(index, fill_value=0.0)

    climate = climate_daily(store)
    if not climate.empty:
        clim = climate.reindex(index).ffill()
        data["t_max"] = clim["t_max"]
        data["t_min"] = clim["t_min"]
        data["precip"] = clim["precip"]
        data["wind_max"] = clim["wind_max"]
        data["t_max_lag1"] = data["t_max"].shift(1)
        data["precip_lag1"] = data["precip"].shift(1)
        data["precip_roll7"] = data["precip"].rolling(7).mean()
        data["wind_lag1"] = data["wind_max"].shift(1)

    firms = firms_daily(store)
    if len(firms) >= max(60, int(len(index) * 0.8)):
        # Solo entra si hay cobertura historica suficiente; si no, seria
        # una columna casi vacia que descartaria todo el entrenamiento.
        data["firms"] = firms.reindex(index).ffill().fillna(0.0)

    blocks = [data, _calendar(index),
              _lag_block(data["events"], "events", LAGS, ROLLS)]
    if "all_events" in data.columns:
        blocks.append(_lag_block(data["all_events"], "all_events", (1, 7), ()))

    frame = pd.concat(blocks, axis=1)
    frame["events_next"] = data["events"].shift(-1)
    return frame
