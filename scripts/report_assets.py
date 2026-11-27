"""Entrena los clasificadores por evento de la Fase 4 y genera las graficas.

Modelos por evento (especificacion de la presentacion de Fase 4):
- severidad del flare: clase M/X = 1 frente a clase C = 0, con variables
  fisicas distintas de la propia intensidad en banda (duracion, posicion,
  region activa, ciclo solar).
- persistencia del incendio: duracion > 7 dias = 1, con geografia y
  estacionalidad del primer dia de deteccion.

Para cada tarea se comparan Regresion Logistica (con StandardScaler) y
Random Forest, division estratificada 80/20 reproducible. No forma parte
del dashboard: produce la evidencia del reporte.

Salidas:
    reporte/graficas/c1..c6*.png     (5 graficas + ROC)
    reporte/metricas_eventos.json    (metricas para el documento Word)
"""
from __future__ import annotations

from datetime import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    auc, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, roc_curve,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app import features, ml
from app.db import store
from config import settings

OUT = Path(__file__).resolve().parent.parent / "reporte"
CHARTS = OUT / "graficas"

# Estilo sobrio para el documento (fondo blanco).
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.grid": True, "grid.alpha": 0.3, "grid.linewidth": 0.5,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
})

_LOC_RE = re.compile(r"^([NS])(\d+)([EW])(\d+)$")


def _parse_location(text: str):
    """'S15W12' -> (lat=-15, lon=-12); None si no se puede parsear."""
    if not text:
        return None
    m = _LOC_RE.match(text.strip().upper())
    if not m:
        return None
    ns, lat_num, ew, lon_num = m.groups()
    lat = int(lat_num) * (1 if ns == "N" else -1)
    lon = int(lon_num) * (1 if ew == "E" else -1)
    return lat, lon


def _to_time(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", ""))
    except (ValueError, TypeError):
        return None


def flare_severity_dataset() -> pd.DataFrame:
    """Event-level: severidad M/X desde caracteristicas fisicas y temporales.

    La duracion es el tiempo real de crecimiento (peakTime - startTime),
    tomado del timestamp completo almacenado en la base.
    """
    conn = store.connect()
    try:
        rows = conn.execute(
            "SELECT event_time, event_day, extra FROM donki_events WHERE event_type = 'FLR'"
        ).fetchall()
    finally:
        conn.close()
    records = []
    for event_time, day, extra_json in rows:
        if not extra_json:
            continue
        try:
            extra = json.loads(extra_json)
        except (ValueError, TypeError):
            continue
        letter = extra.get("top_class")
        if letter not in ("C", "M", "X"):
            continue
        location = _parse_location(extra.get("source_location"))
        if location is None:
            continue
        start = _to_time(event_time)
        peak = _to_time(extra.get("peak_time"))
        duration = (peak - start).total_seconds() / 60.0 if (start and peak) else np.nan
        first = datetime.fromisoformat(day)
        doy = first.timetuple().tm_yday
        months_since = (first.year - 2008) * 12 + (first.month - 12)
        phase = (months_since % 132) / 132.0
        records.append({
            "duracion_min": duration,
            "latitud": location[0],
            "longitud": location[1],
            "region_activa": float(extra.get("active_region") or 0),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
            "ciclo_sin": np.sin(2 * np.pi * phase),
            "ciclo_cos": np.cos(2 * np.pi * phase),
            "severo_mx": int(letter in ("M", "X")),
        })
    df = pd.DataFrame(records)
    return df.dropna()


def fire_persistence_dataset() -> pd.DataFrame:
    """Event-level: foco persistente (zona activa mas de 7 dias).

    EONET v3 registra cada deteccion diaria como un evento independiente
    con una sola geometria, por lo que la persistencia se define por
    zona: se agrupan las detecciones en celdas de 0.5 grados (~55 km) y
    un episodio son dias consecutivos con huecos de <= 3 dias. El foco
    es 'persistente' si su episodio abarca mas de 7 dias. Las variables
    usan solo informacion conocida en el momento de la deteccion.
    """
    conn = store.connect()
    try:
        rows = conn.execute(
            """SELECT first_day, lat, lon FROM eonet_events
               WHERE category = 'Wildfires' AND lat IS NOT NULL AND lon IS NOT NULL"""
        ).fetchall()
    finally:
        conn.close()

    cell_events: dict = {}
    for first_day, lat, lon in rows:
        cell = (round(lat * 2) / 2.0, round(lon * 2) / 2.0)
        cell_events.setdefault(cell, set()).add(first_day)

    # Episodios por celda: dias consecutivos con huecos de <= 3 dias.
    episode_of_day: dict = {}
    for cell, day_set in cell_events.items():
        days = sorted(day_set)
        episodes = []
        previous = None
        for day in days:
            gap = (datetime.fromisoformat(day) - datetime.fromisoformat(previous)).days \
                if previous else 99
            if gap > 3:
                episodes.append([day])
            else:
                episodes[-1].append(day)
            previous = day
        for episode in episodes:
            span = (datetime.fromisoformat(episode[-1])
                    - datetime.fromisoformat(episode[0])).days
            persistent = int(span > 7)
            for day in episode:
                episode_of_day[(cell, day)] = persistent

    # Densidad local el mismo dia (conocida al detectar el foco).
    same_day_density: dict = {}
    for first_day, lat, lon in rows:
        cell = (round(lat * 2) / 2.0, round(lon * 2) / 2.0)
        same_day_density[(cell, first_day)] = same_day_density.get((cell, first_day), 0) + 1

    records = []
    for first_day, lat, lon in rows:
        cell = (round(lat * 2) / 2.0, round(lon * 2) / 2.0)
        target = episode_of_day.get((cell, first_day))
        if target is None:
            continue
        first = datetime.fromisoformat(first_day)
        doy = first.timetuple().tm_yday
        records.append({
            "latitud": float(lat),
            "longitud": float(lon),
            "densidad_dia": float(same_day_density[(cell, first_day)]),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
            "mes_sin": np.sin(2 * np.pi * first.month / 12.0),
            "mes_cos": np.cos(2 * np.pi * first.month / 12.0),
            "anyo_norm": (first.year - 2000) / 26.0,
            "persistente_7d": target,
        })
    return pd.DataFrame(records)


def _evaluate(model, x_test, y_test, threshold: float, prefix=""):
    proba = model.predict_proba(x_test)[:, 1]
    pred = (proba >= threshold).astype(int)
    fpr, tpr, _ = roc_curve(y_test, proba)
    return {
        "auc": round(float(roc_auc_score(y_test, proba)), 3),
        "umbral": round(float(threshold), 4),
        "f1": round(float(f1_score(y_test, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y_test, pred, zero_division=0)), 3),
        "precision": round(float(precision_score(y_test, pred, zero_division=0)), 3),
        "confusion": {"vp": int(confusion_matrix(y_test, pred)[1, 1]),
                      "fp": int(confusion_matrix(y_test, pred)[0, 1]),
                      "fn": int(confusion_matrix(y_test, pred)[1, 0]),
                      "vn": int(confusion_matrix(y_test, pred)[0, 0])},
        "_fpr": fpr.tolist(), "_tpr": tpr.tolist(),
    }


def _calibrated_threshold(factory, x_train, y_train) -> float:
    """Umbral F1-optimo sobre probabilidades fuera de muestra (5 pliegues).

    Mismo protocolo que el clasificador operativo del dashboard: con
    clases muy desbalanceadas el umbral 0.5 nunca dispara.
    """
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof = np.zeros(len(y_train))
    for fit_idx, val_idx in folds.split(x_train, y_train):
        model = factory()
        model.fit(x_train.iloc[fit_idx], y_train[fit_idx])
        oof[val_idx] = model.predict_proba(x_train.iloc[val_idx])[:, 1]
    best_threshold, best_f1 = 0.5, -1.0
    for threshold in np.unique(oof):
        score = f1_score(y_train, (oof >= threshold).astype(int), zero_division=0)
        if score > best_f1:
            best_f1, best_threshold = score, float(threshold)
    return best_threshold


def train_event_model(df: pd.DataFrame, label: str) -> dict:
    """Logistica (escalada) vs Random Forest, 80/20 estratificado reproducible."""
    y = df[label].to_numpy()
    x = df.drop(columns=[label])
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, stratify=y, random_state=42)

    def _logistica():
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=100, C=1.0, class_weight="balanced", random_state=42),
        )

    def _bosque():
        return RandomForestClassifier(
            n_estimators=100, max_depth=8, class_weight="balanced", random_state=42, n_jobs=-1,
        )

    logistica = _logistica().fit(x_train, y_train)
    bosque = _bosque().fit(x_train, y_train)
    threshold_log = _calibrated_threshold(_logistica, x_train, y_train)
    threshold_rf = _calibrated_threshold(_bosque, x_train, y_train)

    return {
        "n_eventos": int(len(df)),
        "positivos": int(y.sum()),
        "tasa_positivos": round(float(y.mean()), 3),
        "n_train": int(len(x_train)), "n_test": int(len(x_test)),
        "logistica": _evaluate(logistica, x_test, y_test, threshold_log),
        "random_forest": _evaluate(bosque, x_test, y_test, threshold_rf),
        "importancias_rf": sorted(
            zip(x.columns, bosque.feature_importances_),
            key=lambda kv: kv[1], reverse=True,
        ),
    }


# ---------------------------------------------------------------------- #
# Graficas del reporte
# ---------------------------------------------------------------------- #
def chart_solar_series():
    flares = features.donki_daily(store, "FLR")
    roll = flares.rolling(28).mean()
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(flares.index, flares.values, color="#9aa4b2", linewidth=0.5, alpha=0.6,
            label="Flares por día")
    ax.plot(roll.index, roll.values, color="#d97706", linewidth=1.8, label="Media móvil 28 días")
    ax.set_title("Actividad solar registrada por DONKI (2010–2026)")
    ax.set_xlabel("Fecha"), ax.set_ylabel("Flares por día")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(CHARTS / "c1_flares_serie.png", dpi=150)
    plt.close(fig)


def chart_fire_series():
    fires = features.eonet_daily(store, "Wildfires")
    roll = fires.rolling(28).mean()
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(fires.index, fires.values, color="#9aa4b2", linewidth=0.6, alpha=0.6,
            label="Eventos por día")
    ax.plot(roll.index, roll.values, color="#dc2626", linewidth=1.8, label="Media móvil 28 días")
    ax.axvline(pd.Timestamp("2024-01-01"), color="#2563eb", linestyle="--", linewidth=1.2)
    ax.annotate("Ingesta automatizada de EONET (2024)", xy=(pd.Timestamp("2024-01-01"), roll.max()),
                xytext=(pd.Timestamp("2015-06-01"), roll.max() * 0.92),
                arrowprops=dict(arrowstyle="->", color="#2563eb"), color="#2563eb")
    ax.set_title("Incendios forestales registrados por EONET (2000–2026)")
    ax.set_xlabel("Fecha"), ax.set_ylabel("Eventos por día")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(CHARTS / "c2_incendios_serie.png", dpi=150)
    plt.close(fig)


def chart_backtest(name: str, title: str, fname: str, color_actual: str, color_pred: str):
    backtests = ml.backtest(store, days=60)
    bt = backtests.get(name)
    if not bt:
        return
    dates = pd.to_datetime(bt["dates"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(dates, bt["actual"], color=color_actual, linewidth=1.7, label="Real")
    ax.plot(dates, bt["predicted"], color=color_pred, linewidth=1.7, linestyle="--",
            label="Predicho (fuera de muestra)")
    ax.set_title(title)
    ax.set_xlabel("Fecha"), ax.set_ylabel("Eventos")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(CHARTS / fname, dpi=150)
    plt.close(fig)


def chart_importance():
    models = {m["name"]: m for m in store.registered_models()}
    model = models.get("flares_x_next_day")
    if not model or not model["metrics"].get("top_features"):
        return
    top = model["metrics"]["top_features"][:10]
    names = [t[0] for t in top][::-1]
    values = [t[1] for t in top][::-1]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.barh(names, values, color="#7c3aed", alpha=0.85)
    ax.set_title("Variables más importantes — clasificador de flare clase X (permutación)")
    ax.set_xlabel("Incremento de MAE al barajar la variable")
    fig.tight_layout()
    fig.savefig(CHARTS / "c5_importancia.png", dpi=150)
    plt.close(fig)


def chart_roc(severity: dict, persistence: dict):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, data, title in (
        (axes[0], severity, "ROC — Severidad de flare (M/X)"),
        (axes[1], persistence, "ROC — Persistencia de incendio (>7 días)"),
    ):
        for key, color, label in (("logistica", "#2563eb", "Regresión logística"),
                                   ("random_forest", "#dc2626", "Random Forest")):
            m = data[key]
            ax.plot(m["_fpr"], m["_tpr"], color=color, linewidth=1.8,
                    label=f"{label} (AUC {m['auc']:.3f})")
        ax.plot([0, 1], [0, 1], color="#9aa4b2", linewidth=0.8, linestyle=":")
        ax.set_xlabel("Tasa de falsos positivos"), ax.set_ylabel("Tasa de verdaderos positivos")
        ax.set_title(title), ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(CHARTS / "c6_roc_eventos.png", dpi=150)
    plt.close(fig)


def main() -> int:
    CHARTS.mkdir(parents=True, exist_ok=True)
    print("Construyendo datasets por evento...")
    flares_df = flare_severity_dataset()
    fires_df = fire_persistence_dataset()
    print(f"  flares: {len(flares_df)} eventos ({int(flares_df['severo_mx'].sum())} M/X)")
    print(f"  incendios: {len(fires_df)} eventos ({int(fires_df['persistente_7d'].sum())} > 7 dias)")

    print("Entrenando Regresion Logistica vs Random Forest (80/20 estratificado)...")
    severity = train_event_model(flares_df, "severo_mx")
    persistence = train_event_model(fires_df, "persistente_7d")
    for label, block in (("severidad", severity), ("persistencia", persistence)):
        print(f"  {label}: logistica AUC={block['logistica']['auc']} F1={block['logistica']['f1']}"
              f" | RF AUC={block['random_forest']['auc']} F1={block['random_forest']['f1']}")

    print("Generando graficas...")
    chart_solar_series()
    chart_fire_series()
    chart_backtest("flares_next_day", "Flares a 24 h: predicho vs real (backtest 60 días)",
                   "c3_backtest_flares.png", "#b91c1c", "#d97706")
    chart_backtest("eonet_wildfires_next_day", "Incendios a 24 h: predicho vs real (backtest 60 días)",
                   "c4_backtest_incendios.png", "#b91c1c", "#0d9488")
    chart_importance()
    chart_roc(severity, persistence)

    # El JSON alimenta al generador del documento Word.
    def _clean(block):
        return {k: v for k, v in block.items() if not k.startswith("_")}

    payload = {
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "flare_severity": {**{k: v for k, v in severity.items()
                              if k not in ("logistica", "random_forest")},
                           "logistica": _clean(severity["logistica"]),
                           "random_forest": _clean(severity["random_forest"]),
                           "importancias_rf": [[c, round(float(v), 4)]
                                               for c, v in severity["importancias_rf"]]},
        "fire_persistence": {**{k: v for k, v in persistence.items()
                                 if k not in ("logistica", "random_forest")},
                             "logistica": _clean(persistence["logistica"]),
                             "random_forest": _clean(persistence["random_forest"]),
                             "importancias_rf": [[c, round(float(v), 4)]
                                                 for c, v in persistence["importancias_rf"]]},
    }
    (OUT / "metricas_eventos.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {CHARTS} y {OUT / 'metricas_eventos.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
