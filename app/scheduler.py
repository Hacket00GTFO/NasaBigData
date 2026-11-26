"""Tareas programadas del pipeline dentro del servidor Flask (APScheduler).

- collect: cada SCHEDULER_COLLECT_HOURS refresca los ultimos dias de
  todas las fuentes (idempotente) y amplifica el dataset.
- train: una vez al dia (SCHEDULER_TRAIN_HOUR, UTC) reentrena los
  modelos con el dataset vigente.

Ademas del intervalo, se programa una recoleccion unica 2 minutos
despues de arrancar para estrenar el dataset sin esperar el ciclo.
No se inicia bajo unittest ni en el proceso padre del reloader.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
import sys

from apscheduler.schedulers.background import BackgroundScheduler

from app import ml
from app.collector import update_recent
from config import settings

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _run_collect() -> None:
    try:
        summary = update_recent()
        log.info("Recoleccion incremental completada: %s",
                 json.dumps(summary, default=str)[:400])
    except Exception:
        log.exception("Fallo la recoleccion incremental")


def _run_train() -> None:
    try:
        results = ml.train_all()
        status = {name: (result.get("status", "?") if isinstance(result, dict) else "?")
                  for name, result in results.items()}
        log.info("Reentrenamiento completado: %s", status)
    except Exception:
        log.exception("Fallo el reentrenamiento de modelos")


def start_scheduler() -> None:
    """Arranca el scheduler una sola vez por proceso."""
    global _scheduler
    if not settings.scheduler_enabled:
        return
    if "unittest" in sys.modules:
        return
    if settings.flask_debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return  # proceso padre del reloader de depuracion
    if _scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_collect, "interval", hours=settings.scheduler_collect_hours,
        id="nasa_collect", replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _run_train, "cron", hour=settings.scheduler_train_hour,
        id="nasa_train", replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _run_collect, "date",
        run_date=datetime.now() + timedelta(minutes=2),
        id="nasa_collect_boot",
    )
    scheduler.start()
    _scheduler = scheduler
    log.info(
        "Scheduler iniciado: recoleccion cada %d h y reentrenamiento a las %02d:00 UTC.",
        settings.scheduler_collect_hours, settings.scheduler_train_hour,
    )
