"""Entrenamiento, evaluacion y pronostico con scikit-learn.

Modelos generados por train_all():

- flares_next_day: regresion del numero de flares de manana.
- flares_week_total: regresion del total de flares de los proximos 7 dias.
- flares_x_next_day: clasificacion de si habra al menos un flare clase X manana.
- eonet_<categoria>_next_day: regresion de eventos por categoria a 24 h.

Cada regresion elige por validacion temporal entre tres variantes:

- persistencia: "manana sera igual que hoy" (el baseline, sin modelo).
- delta: el modelo aprende la correccion sobre la persistencia
  (y_manana - y_hoy) y el pronostico es hoy + correccion. Aporta la
  base de nivel por lo que resiste los cambios de regimen del registro
  (por ejemplo, el salto de eventos EONET desde 2024).
- directa: el modelo aprende y_manana tal cual.

La seleccion usa una ventana de validacion (ML_VALIDATION_DAYS) dentro
del entrenamiento; el ultimo tramo (ML_TEST_DAYS) queda reservado como
prueba final que ningun modelo ni la seleccion ha visto. Los
hiperparametros de cada variante se ajustan con TimeSeriesSplit y el
entrenamiento pondera las filas por recencia (semivida
ML_RECENCY_HALFLIFE_DAYS) porque el proceso generador de eventos cambia
con el tiempo. Con esto, el skill frente a la persistencia nunca deberia
ser muy negativo: en el peor caso la propia persistencia gana la
seleccion y se registra como modelo.

El clasificador calibra su umbral maximizando F1 sobre probabilidades
fuera de muestra (5 pliegues estratificados), imprescindible con clases
muy desbalanceadas (~3% de dias con flare X).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    f1_score, mean_absolute_error, mean_squared_error,
    precision_score, r2_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, TimeSeriesSplit

from app import features
from app.db import Store, store as default_store
from app.features import TARGET_COLS
from config import settings

log = logging.getLogger(__name__)

# Configuraciones candidatas para el ajuste de hiperparametros.
_PARAM_GRID: Tuple[dict, ...] = (
    {"learning_rate": 0.05, "max_iter": 400, "max_leaf_nodes": 31, "min_samples_leaf": 20, "l2_regularization": 0.0},
    {"learning_rate": 0.03, "max_iter": 500, "max_leaf_nodes": 15, "min_samples_leaf": 20, "l2_regularization": 1.0},
    {"learning_rate": 0.08, "max_iter": 300, "max_leaf_nodes": 31, "min_samples_leaf": 40, "l2_regularization": 0.0},
    {"learning_rate": 0.05, "max_iter": 400, "max_leaf_nodes": 8, "min_samples_leaf": 30, "l2_regularization": 1.0},
    {"learning_rate": 0.10, "max_iter": 200, "max_leaf_nodes": 31, "min_samples_leaf": 20, "l2_regularization": 0.0},
    {"learning_rate": 0.03, "max_iter": 600, "max_leaf_nodes": 31, "min_samples_leaf": 10, "l2_regularization": 0.0},
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _model_path(name: str):
    path = settings.models_path
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{name}.joblib"


def _feature_cols(frame: pd.DataFrame, exclude: set) -> List[str]:
    return [c for c in frame.columns if c not in exclude]


def _recency_weights(index: pd.DatetimeIndex, halflife_days: int) -> np.ndarray:
    """Pondera cada fila por 0.5**(edad/semivida), con piso de 0.05.

    Semivida 0 desactiva la ponderacion (todo peso 1). Los dias recientes
    representan mejor el presente porque el proceso generador cambia
    (ciclo solar, automatizacion del registro de eventos).
    """
    if halflife_days <= 0:
        return np.ones(len(index))
    ages = np.asarray((index.max() - index).days, dtype=float)
    weights = np.power(0.5, ages / float(halflife_days))
    return np.maximum(weights, 0.05)


def _new_regressor(params: dict) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        early_stopping=False, random_state=42, **params,
    )


def _new_classifier() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=400, min_samples_leaf=2,
        class_weight="balanced_subsample", random_state=42, n_jobs=-1,
    )


def _temporal_split(frame: pd.DataFrame, cols: List[str]) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """Separa entrenamiento/prueba por fecha (sin mezclar el futuro)."""
    df = frame.dropna(subset=cols)
    if len(df) < settings.ml_test_days + settings.ml_min_train_rows:
        return None
    test = df.iloc[-settings.ml_test_days:]
    train = df.iloc[:-settings.ml_test_days]
    return train, test


def _search_params(x: pd.DataFrame, y: pd.Series, weights: np.ndarray) -> Tuple[dict, float]:
    """Ajuste de hiperparametros con validacion temporal (3 pliegues).

    Devuelve la configuracion con menor MAE promedio fuera de muestra.
    """
    folds = TimeSeriesSplit(n_splits=3)
    best_params, best_mae = dict(_PARAM_GRID[0]), float("inf")
    for params in _PARAM_GRID:
        errors = []
        for fit_idx, val_idx in folds.split(x):
            model = _new_regressor(params)
            model.fit(x.iloc[fit_idx], y.iloc[fit_idx],
                      sample_weight=weights[fit_idx])
            predicted = model.predict(x.iloc[val_idx])
            errors.append(mean_absolute_error(y.iloc[val_idx], predicted))
        mae = float(np.mean(errors))
        if mae < best_mae:
            best_mae, best_params = mae, dict(params)
    return best_params, best_mae


def _top_features(model, x: pd.DataFrame, y: pd.Series, cols: List[str]) -> List[list]:
    """Importancia por permutacion (MAE), sobre datos no usados para ajustar."""
    result = permutation_importance(
        model, x, y, scoring="neg_mean_absolute_error",
        n_repeats=5, random_state=42,
    )
    pairs = sorted(zip(cols, result.importances_mean), key=lambda kv: kv[1], reverse=True)[:10]
    return [[str(c), round(float(v), 4)] for c, v in pairs]


def _register(store: Store, name: str, frame_kind: str, target: str, horizon: int,
              kind: str, cols: List[str], metrics: dict, model_path) -> None:
    store.register_model({
        "name": name, "frame": frame_kind, "target": target, "horizon_days": horizon,
        "kind": kind, "feature_cols": cols, "metrics": metrics,
        "model_path": str(model_path) if model_path else None, "trained_at": _now(),
    })


# ---------------------------------------------------------------------- #
# Regresion: seleccion de variante (persistencia / delta / directa)
# ---------------------------------------------------------------------- #
def _fit_variant(train: pd.DataFrame, cols: List[str], target: str, level_col: str,
                 variant: str, params: dict, weights: np.ndarray) -> HistGradientBoostingRegressor:
    """Entrena una variante con hiperparametros ya ajustados.

    delta: aprende (y - nivel_hoy) y el pronostico es nivel_hoy + correccion.
    directa: aprende y tal cual.
    """
    model = _new_regressor(params)
    if variant == "delta":
        model.fit(train[cols], train[target] - train[level_col], sample_weight=weights)
    else:
        model.fit(train[cols], train[target], sample_weight=weights)
    return model


def _variant_predict(model: HistGradientBoostingRegressor, sub: pd.DataFrame,
                     cols: List[str], level: pd.Series, variant: str) -> np.ndarray:
    raw = model.predict(sub[cols])
    if variant == "delta":
        raw = np.asarray(level, dtype=float) + raw
    return np.clip(raw, 0.0, None)


def _train_regression(store: Store, name: str, frame_kind: str, frame: pd.DataFrame,
                      target: str, level_col: str, horizon: int) -> dict:
    """Selecciona por validacion walk-forward la mejor variante y la
    evalua una sola vez en la prueba.

    Protocolo: prueba = ultimo ML_TEST_DAYS (intocable). La seleccion usa
    tres bloques consecutivos al final del entrenamiento, cada uno
    predicho solo con los datos previos (MAE agrupado): una ventana
    unica puede caer en un periodo atipico y elegir mal. La ganadora se
    reajusta con todo el entrenamiento para medirse en la prueba.
    """
    cols = _feature_cols(frame, set(TARGET_COLS))
    split = _temporal_split(frame, cols + [target])
    if split is None:
        return {"status": "datos_insuficientes", "rows": int(len(frame))}
    train, test = split

    # Bloques de validacion walk-forward al final del entrenamiento.
    block_days = min(settings.ml_validation_days, max(30, len(train) // 6))
    blocks: List[Tuple[int, int]] = []
    end = len(train)
    while len(blocks) < 3 and end - block_days > max(60, settings.ml_min_train_rows // 2):
        blocks.append((end - block_days, end))
        end -= block_days
    if not blocks:
        blocks = [(max(0, len(train) - block_days), len(train))]

    # Hiperparametros de cada variante, ajustados con TimeSeriesSplit.
    weights_train = _recency_weights(train.index, settings.ml_recency_halflife_days)
    params: Dict[str, dict] = {}
    for variant in ("delta", "directa"):
        y = train[target] - train[level_col] if variant == "delta" else train[target]
        params[variant], _ = _search_params(train[cols], y, weights_train)

    def _pooled_score(variant: Optional[str]) -> float:
        y_true: List[np.ndarray] = []
        y_pred: List[np.ndarray] = []
        for start, stop in blocks:
            fit_part, val_part = train.iloc[:start], train.iloc[start:stop]
            if variant is None:  # persistencia: manana = hoy
                pred = np.clip(val_part[level_col].to_numpy(), 0.0, None)
            else:
                weights = _recency_weights(fit_part.index, settings.ml_recency_halflife_days)
                model = _fit_variant(fit_part, cols, target, level_col, variant,
                                     params[variant], weights)
                pred = _variant_predict(model, val_part, cols, val_part[level_col], variant)
            y_true.append(val_part[target].to_numpy())
            y_pred.append(pred)
        return round(float(mean_absolute_error(
            np.concatenate(y_true), np.concatenate(y_pred))), 3)

    val_scores: Dict[str, float] = {"persistencia": _pooled_score(None)}
    for variant in ("delta", "directa"):
        val_scores[variant] = _pooled_score(variant)

    winner = min(val_scores, key=val_scores.get)

    # Ajuste final de la variante ganadora con TODO el entrenamiento.
    if winner == "persistencia":
        kind, winner_params, top_features = "persistence", {}, []
        predicted_test = np.clip(test[level_col].to_numpy(), 0.0, None)
        model_path = None
        feature_cols = [level_col]
    else:
        model = _fit_variant(train, cols, target, level_col, winner,
                             params[winner], weights_train)
        winner_params = params[winner]
        predicted_test = _variant_predict(model, test, cols, test[level_col], winner)
        # Importancia por permutacion en el ultimo bloque de validacion
        # (no en la prueba): mide cuanto empeora el MAE al barajar la
        # variable.
        val_for_importance = train.iloc[blocks[-1][0]:]
        y_importance = (val_for_importance[target] - val_for_importance[level_col]
                        if winner == "delta" else val_for_importance[target])
        top_features = _top_features(model, val_for_importance[cols], y_importance, cols)
        kind, feature_cols = "regression", cols
        model_path = _model_path(name)
        joblib.dump(model, model_path)

    actual = test[target].to_numpy()
    metrics = {
        "status": "ok", "kind": kind,
        "variant": winner,
        "params": winner_params,
        "n_train": int(len(train)), "n_test": int(len(test)),
        "val_scores": val_scores,
        "level_col": level_col,
        "mae": round(float(mean_absolute_error(actual, predicted_test)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, predicted_test))), 3),
        "r2": round(float(r2_score(actual, predicted_test)), 3),
        "baseline_mae": round(float(mean_absolute_error(
            actual, np.clip(test[level_col].to_numpy(), 0.0, None))), 3),
        "test_from": test.index[0].strftime("%Y-%m-%d"),
        "test_to": test.index[-1].strftime("%Y-%m-%d"),
        "top_features": top_features,
    }
    metrics["skill"] = (round(1 - metrics["mae"] / metrics["baseline_mae"], 3)
                       if metrics["baseline_mae"] > 0 else None)
    _register(store, name, frame_kind, target, horizon, kind, feature_cols, metrics, model_path)
    return metrics


# ---------------------------------------------------------------------- #
# Clasificacion (flare clase X manana)
# ---------------------------------------------------------------------- #
def _calibrate_threshold(x: pd.DataFrame, y: pd.Series, weights: np.ndarray) -> Tuple[float, np.ndarray]:
    """Umbral que maximiza F1 sobre probabilidades fuera de muestra.

    Devuelve (umbral, probabilidades OOF). Con clases muy desbalanceadas
    (~3% de dias con flare X) el umbral 0.5 nunca dispara.
    """
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof = np.zeros(len(y))
    for fit_idx, val_idx in folds.split(x, y):
        model = _new_classifier()
        model.fit(x.iloc[fit_idx], y.iloc[fit_idx], sample_weight=weights[fit_idx])
        oof[val_idx] = model.predict_proba(x.iloc[val_idx])[:, 1]
    best_threshold, best_f1 = 0.5, -1.0
    for threshold in np.unique(oof):
        score = f1_score(y, (oof >= threshold).astype(int), zero_division=0)
        if score > best_f1:
            best_f1, best_threshold = score, float(threshold)
    return best_threshold, oof


def _train_classification(store: Store, name: str, frame_kind: str, frame: pd.DataFrame,
                          target: str) -> dict:
    cols = _feature_cols(frame, set(TARGET_COLS))
    split = _temporal_split(frame, cols + [target])
    if split is None:
        return {"status": "datos_insuficientes", "rows": int(len(frame))}
    train, test = split
    if train[target].nunique() < 2:
        return {"status": "clase_unica", "rows": int(len(train))}

    weights = _recency_weights(train.index, settings.ml_recency_halflife_days)
    model = _new_classifier()
    model.fit(train[cols], train[target], sample_weight=weights)
    threshold, _ = _calibrate_threshold(train[cols], train[target].astype(int), weights)
    proba = model.predict_proba(test[cols])[:, 1]
    predicted = (proba >= threshold).astype(int)
    actual = test[target].astype(int).to_numpy()

    try:
        auc = round(float(roc_auc_score(actual, proba)), 3)
    except ValueError:
        auc = None  # el periodo de prueba no contiene la clase positiva
    confusion = {
        "tp": int(((predicted == 1) & (actual == 1)).sum()),
        "fp": int(((predicted == 1) & (actual == 0)).sum()),
        "fn": int(((predicted == 0) & (actual == 1)).sum()),
        "tn": int(((predicted == 0) & (actual == 0)).sum()),
    }
    metrics = {
        "status": "ok", "kind": "classification",
        "n_train": int(len(train)), "n_test": int(len(test)),
        "auc": auc,
        "threshold": round(float(threshold), 4),
        "f1": round(float(f1_score(actual, predicted, zero_division=0)), 3),
        "precision": round(float(precision_score(actual, predicted, zero_division=0)), 3),
        "recall": round(float(recall_score(actual, predicted, zero_division=0)), 3),
        "positive_rate": round(float(actual.mean()), 3),
        "confusion": confusion,
        "test_from": test.index[0].strftime("%Y-%m-%d"),
        "test_to": test.index[-1].strftime("%Y-%m-%d"),
    }
    importance = sorted(zip(cols, model.feature_importances_), key=lambda kv: kv[1], reverse=True)[:10]
    metrics["top_features"] = [[str(c), round(float(v), 4)] for c, v in importance]

    path = _model_path(name)
    joblib.dump(model, path)
    _register(store, name, frame_kind, target, 1, "classification", cols, metrics, path)
    return metrics


# ---------------------------------------------------------------------- #
# Orquestacion
# ---------------------------------------------------------------------- #
def train_all(store: Optional[Store] = None, progress=None) -> Dict[str, dict]:
    """Entrena (o reentrena) todos los modelos sobre el dataset vigente."""
    target = store or default_store
    results: Dict[str, dict] = {}
    frame = features.flare_frame(target)
    if frame.empty:
        results["flares_next_day"] = {"status": "sin_datos"}
    else:
        if progress:
            progress(f"Frame flares: {len(frame)} dias ({frame.index[0].date()} a {frame.index[-1].date()})")
        results["flares_next_day"] = _train_regression(
            target, "flares_next_day", "flare", frame, "flares_next", "flares", 1)
        if progress:
            progress("flares_next_day: " + results["flares_next_day"].get("status", "?")
                     + f" (variante {results['flares_next_day'].get('variant', '?')})")
        results["flares_week_total"] = _train_regression(
            target, "flares_week_total", "flare", frame, "flares_week", "flares_week_past", 7)
        if progress:
            progress("flares_week_total: " + results["flares_week_total"].get("status", "?")
                     + f" (variante {results['flares_week_total'].get('variant', '?')})")
        results["flares_x_next_day"] = _train_classification(
            target, "flares_x_next_day", "flare", frame, "flares_x_next")
        if progress:
            progress("flares_x_next_day: " + results["flares_x_next_day"].get("status", "?"))

    categories = target.eonet_category_totals(limit=settings.eonet_model_categories)
    for category, total in categories:
        if total < 200:
            results[f"eonet_{_slug(category)}_next_day"] = {"status": "pocos_eventos", "total": int(total)}
            continue
        eonet = features.eonet_frame(target, category)
        if eonet.empty:
            results[f"eonet_{_slug(category)}_next_day"] = {"status": "sin_datos"}
            continue
        if progress:
            progress(f"Frame {category}: {len(eonet)} dias")
        results[f"eonet_{_slug(category)}_next_day"] = _train_regression(
            target, f"eonet_{_slug(category)}_next_day", f"eonet:{category}",
            eonet, "events_next", "events", 1)
        if progress:
            progress(f"eonet_{_slug(category)}_next_day: "
                     + results[f"eonet_{_slug(category)}_next_day"].get("status", "?")
                     + f" (variante {results[f'eonet_{_slug(category)}_next_day'].get('variant', '?')})")
    return results


# ---------------------------------------------------------------------- #
# Pronostico y backtest en produccion
# ---------------------------------------------------------------------- #
def _frame_for(store: Store, cache: dict, frame_kind: str) -> Optional[pd.DataFrame]:
    """Construye (una vez por peticion) el frame segun el tipo de modelo."""
    if frame_kind == "flare":
        return cache.setdefault("flare", features.flare_frame(store))
    if frame_kind.startswith("eonet:"):
        return cache.setdefault(frame_kind, features.eonet_frame(store, frame_kind[len("eonet:"):]))
    return None


def predict(store: Optional[Store] = None) -> dict:
    """Pronostico de cada modelo registrado con los datos vigentes."""
    target = store or default_store
    models = target.registered_models()
    if not models:
        return {}
    frames: dict = {}
    forecasts: dict = {}
    for model in models:
        name = model["name"]
        frame = _frame_for(target, frames, model["frame"])
        if frame is None or frame.empty:
            forecasts[name] = {"status": "sin_datos"}
            continue
        cols = model["feature_cols"]
        metrics = model.get("metrics") or {}
        level_col = metrics.get("level_col")
        is_delta = (model["kind"] == "regression"
                    and metrics.get("variant") == "delta" and level_col)
        # 'level_col' suele ser ademas una feature: se deduplica.
        if model["kind"] == "persistence":
            needed = [level_col]
        elif is_delta:
            needed = list(dict.fromkeys(list(cols) + [level_col]))
        else:
            needed = list(cols)
        if any(c not in frame.columns for c in needed if c):
            forecasts[name] = {"status": "features_incompletas"}
            continue
        row = frame[needed].tail(1)
        if row.isna().any().any():
            forecasts[name] = {"status": "features_incompletas"}
            continue
        last_day = frame.index[-1]
        predicted_date = last_day + pd.Timedelta(days=int(model["horizon_days"]))
        common = {
            "date": predicted_date.strftime("%Y-%m-%d"),
            "last_day": last_day.strftime("%Y-%m-%d"),
        }
        if model["kind"] == "persistence":
            forecasts[name] = {
                "status": "ok", "kind": "persistence", **common,
                "value": round(max(0.0, float(row[level_col].iloc[0])), 2),
            }
        elif model["kind"] == "regression":
            try:
                estimator = joblib.load(model["model_path"])
            except (OSError, ValueError):
                forecasts[name] = {"status": "modelo_no_disponible"}
                continue
            raw = float(estimator.predict(frame[cols].tail(1))[0])
            if is_delta:
                raw += float(frame[level_col].iloc[-1])
            forecasts[name] = {
                "status": "ok", "kind": "regression", **common,
                "value": round(max(0.0, raw), 2),
            }
        else:
            try:
                estimator = joblib.load(model["model_path"])
            except (OSError, ValueError):
                forecasts[name] = {"status": "modelo_no_disponible"}
                continue
            probability = float(estimator.predict_proba(frame[cols].tail(1))[0][1])
            threshold = float(metrics.get("threshold") or 0.5)
            forecasts[name] = {
                "status": "ok", "kind": "classification", **common,
                "probability": round(probability, 4),
                "threshold": round(threshold, 4),
                "alert": bool(probability >= threshold),
            }
    return forecasts


def backtest(store: Optional[Store] = None, days: int = 60) -> dict:
    """Predicho vs real de los ultimos 'days' dias por modelo (evaluacion).

    Con la division temporal por defecto, esa ventana cae dentro del
    conjunto de prueba: los valores son fuera de muestra.
    """
    target = store or default_store
    models = target.registered_models()
    frames: dict = {}
    out: dict = {}
    for model in models:
        frame = _frame_for(target, frames, model["frame"])
        if frame is None or frame.empty:
            continue
        cols = model["feature_cols"]
        metrics = model.get("metrics") or {}
        level_col = metrics.get("level_col")
        is_delta = (model["kind"] == "regression"
                    and metrics.get("variant") == "delta" and level_col)
        sub_cols = ([level_col] if model["kind"] == "persistence" else
                    list(dict.fromkeys(list(cols) + [level_col])) if is_delta else list(cols))
        if any(c not in frame.columns for c in sub_cols + [model["target"]] if c):
            continue
        sub = frame.dropna(subset=sub_cols + [model["target"]]).tail(days)
        if sub.empty or level_col is None:
            continue
        if model["kind"] == "persistence":
            predicted = [round(max(0.0, float(v)), 2) for v in sub[level_col]]
        else:
            try:
                estimator = joblib.load(model["model_path"])
            except (OSError, ValueError):
                continue
            if model["kind"] == "regression":
                if is_delta:
                    raw = np.asarray(sub[level_col], dtype=float) + estimator.predict(sub[cols])
                else:
                    raw = estimator.predict(sub[cols])
                predicted = [round(max(0.0, float(v)), 2) for v in np.clip(raw, 0.0, None)]
            else:
                predicted = [round(float(v), 4) for v in estimator.predict_proba(sub[cols])[:, 1]]
        out[model["name"]] = {
            "kind": "persistence" if model["kind"] == "persistence" else model["kind"],
            "dates": [d.strftime("%Y-%m-%d") for d in sub.index],
            "actual": [round(float(v), 2) for v in sub[model["target"]]],
            "predicted": predicted,
        }
    return out
