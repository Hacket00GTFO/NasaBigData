"""Entrena los modelos de prediccion y muestra el informe de evaluacion.

Imprime por modelo: estado, metricas frente al baseline de
persistencia y las variables mas importantes. Sirve como evidencia
para las fases de modelado y evaluacion de CRISP-DM.

Ejemplos:

    python scripts/train_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ml  # noqa: E402
from app.db import store  # noqa: E402


def _print_metrics(name: str, metrics: dict) -> None:
    status = metrics.get("status", "?")
    print(f"\n=== {name} [{status}] ===")
    if status != "ok":
        if "rows" in metrics:
            print(f"  filas disponibles: {metrics['rows']}")
        return
    if metrics.get("kind") == "regression":
        print(f"  prueba: {metrics['test_from']} -> {metrics['test_to']}"
              f" ({metrics['n_test']} dias, entrenamiento {metrics['n_train']})")
        print(f"  variante ganadora: {metrics.get('variant')}"
              f" | validacion: {metrics.get('val_scores')}")
        if metrics.get("params"):
            print(f"  hiperparametros: {metrics['params']}")
        print(f"  MAE {metrics['mae']} | RMSE {metrics['rmse']} | R2 {metrics['r2']}")
        print(f"  baseline persistencia: MAE {metrics['baseline_mae']}"
              f" | skill {metrics.get('skill')}")
    elif metrics.get("kind") == "persistence":
        print(f"  la persistencia gano la seleccion: {metrics.get('val_scores')}")
        print(f"  MAE {metrics['mae']} | skill {metrics.get('skill')}"
              f" (el sistema queda igualado al baseline)")
    else:
        print(f"  prueba: {metrics['test_from']} -> {metrics['test_to']}"
              f" ({metrics['n_test']} dias, entrenamiento {metrics['n_train']})")
        print(f"  AUC {metrics.get('auc')} | F1 {metrics['f1']}"
              f" | umbral calibrado {metrics.get('threshold')}"
              f" | precision {metrics['precision']} | recall {metrics['recall']}")
        print(f"  tasa de dias con flare X: {metrics['positive_rate']}"
              f" | confusion {metrics['confusion']}")
    top = metrics.get("top_features") or []
    if top:
        print("  variables mas importantes:")
        for feature, importance in top[:6]:
            print(f"    {feature}: {importance}")


def main() -> int:
    store.init()
    counts = store.counts()
    if counts.get("donki_events", 0) == 0 and counts.get("eonet_events", 0) == 0:
        print("El dataset esta vacio. Ejecuta primero el backfill:")
        print("    python scripts/backfill.py --source all")
        return 1

    print("Dataset:")
    for table in store.dataset_summary()["tables"]:
        print(f"  {table['table']}: {table['rows']} filas ({table['from']} a {table['to']})")
    print("\nEntrenando modelos (division temporal de prueba:",
          "ultimos dias segun ML_TEST_DAYS)...")
    results = ml.train_all(store, progress=print)

    print("\n" + "=" * 60)
    print("INFORME DE EVALUACION")
    print("=" * 60)
    trained = 0
    for name, metrics in results.items():
        _print_metrics(name, metrics)
        if isinstance(metrics, dict) and metrics.get("status") == "ok":
            trained += 1
    print(f"\nModelos entrenados: {trained} de {len(results)}"
          + (" (guardados en " + str(store.path.parent / "models") + ")" if trained else ""))
    print("\nEl dashboard muestra las predicciones en la pestana 'Predicciones':")
    print("    python run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
