"""Almacenamiento SQLite del dataset acumulado del proyecto.

Persiste los eventos descargados (DONKI, EONET, Open-Meteo y FIRMS) en
una base de datos local que alimenta los modelos de prediccion. Las
escrituras son idempotentes (upserts): repetir una descarga no
duplica filas, por lo que el backfill puede interrumpirse y reanudarse.

Cada metodo abre su propia conexion en modo WAL, asi que es seguro
llamarlas desde los hilos de Flask y del scheduler a la vez.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from config import settings

_TABLES = ("donki_events", "eonet_events", "open_meteo_daily", "firms_daily")
_RANGE_COL = {
    "donki_events": "event_day",
    "eonet_events": "first_day",
    "open_meteo_daily": "day",
    "firms_daily": "day",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS donki_events (
    event_type TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    event_day  TEXT NOT NULL,
    event_time TEXT,
    extra      TEXT,
    PRIMARY KEY (event_type, event_id)
);
CREATE INDEX IF NOT EXISTS idx_donki_day ON donki_events (event_type, event_day);

CREATE TABLE IF NOT EXISTS eonet_events (
    event_id  TEXT PRIMARY KEY,
    title     TEXT,
    category  TEXT,
    first_day TEXT NOT NULL,
    last_day  TEXT,
    lat REAL,
    lon REAL
);
CREATE INDEX IF NOT EXISTS idx_eonet_category ON eonet_events (category, first_day);

CREATE TABLE IF NOT EXISTS open_meteo_daily (
    location TEXT NOT NULL,
    day      TEXT NOT NULL,
    t_max    REAL,
    t_min    REAL,
    precip   REAL,
    wind_max REAL,
    PRIMARY KEY (location, day)
);
CREATE INDEX IF NOT EXISTS idx_open_meteo_day ON open_meteo_daily (day);

CREATE TABLE IF NOT EXISTS firms_daily (
    region TEXT NOT NULL,
    day    TEXT NOT NULL,
    total  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (region, day)
);

CREATE TABLE IF NOT EXISTS collect_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    ok           INTEGER NOT NULL,
    rows_written INTEGER NOT NULL DEFAULT 0,
    message      TEXT,
    ran_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    name          TEXT PRIMARY KEY,
    frame         TEXT NOT NULL,
    target        TEXT NOT NULL,
    horizon_days  INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    feature_cols  TEXT NOT NULL,
    metrics       TEXT NOT NULL,
    model_path    TEXT,
    trained_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class Store:
    """Capa de acceso a SQLite para el dataset del pipeline."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else settings.db_file
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Conexion y esquema
    # ------------------------------------------------------------------ #
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init(self) -> None:
        """Crea el esquema si no existe (idempotente)."""
        conn = self.connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Escrituras (upserts idempotentes)
    # ------------------------------------------------------------------ #
    def upsert_donki(self, rows: Iterable[Tuple[str, str, str, Optional[str], Optional[str]]]) -> int:
        """Filas: (event_type, event_id, event_day, event_time, extra_json)."""
        rows = list(rows)
        if not rows:
            return 0
        conn = self.connect()
        try:
            conn.executemany(
                """INSERT INTO donki_events (event_type, event_id, event_day, event_time, extra)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (event_type, event_id) DO UPDATE SET
                       event_day = excluded.event_day,
                       event_time = excluded.event_time,
                       extra = excluded.extra""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return len(rows)

    def upsert_eonet(self, rows: Iterable[Tuple[str, str, str, str, str, Optional[float], Optional[float]]]) -> int:
        """Filas: (event_id, title, category, first_day, last_day, lat, lon)."""
        rows = list(rows)
        if not rows:
            return 0
        conn = self.connect()
        try:
            conn.executemany(
                """INSERT INTO eonet_events (event_id, title, category, first_day, last_day, lat, lon)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (event_id) DO UPDATE SET
                       title = excluded.title,
                       category = excluded.category,
                       first_day = excluded.first_day,
                       last_day = excluded.last_day,
                       lat = excluded.lat,
                       lon = excluded.lon""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return len(rows)

    def upsert_open_meteo(self, rows: Iterable[Tuple[str, str, Optional[float], Optional[float], Optional[float], Optional[float]]]) -> int:
        """Filas: (location, day, t_max, t_min, precip, wind_max)."""
        rows = list(rows)
        if not rows:
            return 0
        conn = self.connect()
        try:
            conn.executemany(
                """INSERT INTO open_meteo_daily (location, day, t_max, t_min, precip, wind_max)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (location, day) DO UPDATE SET
                       t_max = excluded.t_max,
                       t_min = excluded.t_min,
                       precip = excluded.precip,
                       wind_max = excluded.wind_max""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return len(rows)

    def upsert_firms(self, rows: Iterable[Tuple[str, str, int]]) -> int:
        """Filas: (region, day, total)."""
        rows = list(rows)
        if not rows:
            return 0
        conn = self.connect()
        try:
            conn.executemany(
                """INSERT INTO firms_daily (region, day, total)
                   VALUES (?, ?, ?)
                   ON CONFLICT (region, day) DO UPDATE SET total = excluded.total""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return len(rows)

    def record_run(self, source: str, kind: str, ok: bool, rows_written: int = 0, message: str = "") -> None:
        conn = self.connect()
        try:
            conn.execute(
                "INSERT INTO collect_runs (source, kind, ok, rows_written, message, ran_at) VALUES (?, ?, ?, ?, ?, ?)",
                (source, kind, int(bool(ok)), int(rows_written), message[:500], _now()),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Lecturas para features y reportes
    # ------------------------------------------------------------------ #
    def donki_rows(self, event_type: str) -> List[Tuple[str, Optional[str]]]:
        """(event_day, extra) por evento de un tipo DONKI."""
        conn = self.connect()
        try:
            return conn.execute(
                "SELECT event_day, extra FROM donki_events WHERE event_type = ? ORDER BY event_day",
                (event_type,),
            ).fetchall()
        finally:
            conn.close()

    def donki_type_totals(self) -> Dict[str, int]:
        conn = self.connect()
        try:
            return {t: int(n) for t, n in conn.execute(
                "SELECT event_type, COUNT(*) FROM donki_events GROUP BY event_type").fetchall()}
        finally:
            conn.close()

    def eonet_daily_counts(self, category: Optional[str] = None) -> List[Tuple[str, int]]:
        """Eventos por primer dia de geometria, opcionalmente por categoria."""
        conn = self.connect()
        try:
            if category:
                rows = conn.execute(
                    "SELECT first_day, COUNT(*) FROM eonet_events WHERE category = ? GROUP BY first_day ORDER BY first_day",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT first_day, COUNT(*) FROM eonet_events GROUP BY first_day ORDER BY first_day"
                ).fetchall()
            return [(d, int(n)) for d, n in rows]
        finally:
            conn.close()

    def eonet_category_totals(self, limit: Optional[int] = None) -> List[Tuple[str, int]]:
        conn = self.connect()
        try:
            sql = "SELECT category, COUNT(*) AS c FROM eonet_events GROUP BY category ORDER BY c DESC"
            if limit:
                sql += f" LIMIT {int(limit)}"
            return [(cat, int(n)) for cat, n in conn.execute(sql).fetchall()]
        finally:
            conn.close()

    def climate_rows(self) -> List[Tuple[str, float, float, float, float]]:
        """Promedios entre regiones por dia: (day, t_max, t_min, precip, wind)."""
        conn = self.connect()
        try:
            return conn.execute(
                """SELECT day, AVG(t_max), AVG(t_min), AVG(precip), AVG(wind_max)
                   FROM open_meteo_daily GROUP BY day ORDER BY day"""
            ).fetchall()
        finally:
            conn.close()

    def firms_daily_counts(self) -> List[Tuple[str, int]]:
        conn = self.connect()
        try:
            return [(d, int(n)) for d, n in conn.execute(
                "SELECT day, SUM(total) FROM firms_daily GROUP BY day ORDER BY day").fetchall()]
        finally:
            conn.close()

    def counts(self) -> Dict[str, int]:
        conn = self.connect()
        try:
            return {t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in _TABLES}
        finally:
            conn.close()

    def latest_runs(self, limit: int = 8) -> List[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """SELECT source, kind, ok, rows_written, message, ran_at
                   FROM collect_runs ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()
        return [
            {"source": s, "kind": k, "ok": bool(ok), "rows": int(n), "message": msg or "", "ran_at": ran}
            for s, k, ok, n, msg, ran in rows
        ]

    def dataset_summary(self) -> dict:
        """Volumen, rangos temporales y ultimas ejecuciones del dataset."""
        conn = self.connect()
        try:
            tables = []
            for name in _TABLES:
                rows = int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                lo, hi = conn.execute(
                    f"SELECT MIN({_RANGE_COL[name]}), MAX({_RANGE_COL[name]}) FROM {name}"
                ).fetchone()
                tables.append({"table": name, "rows": rows, "from": lo, "to": hi})
            donki_types = {t: int(n) for t, n in conn.execute(
                "SELECT event_type, COUNT(*) FROM donki_events GROUP BY event_type").fetchall()}
            top_cats = {cat: int(n) for cat, n in conn.execute(
                "SELECT category, COUNT(*) AS c FROM eonet_events GROUP BY category ORDER BY c DESC LIMIT 8"
            ).fetchall()}
        finally:
            conn.close()
        return {
            "tables": tables,
            "donki_by_type": donki_types,
            "eonet_top_categories": top_cats,
            "last_runs": self.latest_runs(8),
            "size_mb": round(self.path.stat().st_size / 1_000_000, 2) if self.path.exists() else 0.0,
        }

    # ------------------------------------------------------------------ #
    # Registro de modelos
    # ------------------------------------------------------------------ #
    def register_model(self, entry: dict) -> None:
        """Guarda o reemplaza la ficha de un modelo entrenado."""
        conn = self.connect()
        try:
            conn.execute(
                """INSERT INTO models (name, frame, target, horizon_days, kind,
                                       feature_cols, metrics, model_path, trained_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (name) DO UPDATE SET
                       frame = excluded.frame,
                       target = excluded.target,
                       horizon_days = excluded.horizon_days,
                       kind = excluded.kind,
                       feature_cols = excluded.feature_cols,
                       metrics = excluded.metrics,
                       model_path = excluded.model_path,
                       trained_at = excluded.trained_at""",
                (
                    entry["name"], entry["frame"], entry["target"], int(entry["horizon_days"]),
                    entry["kind"], json.dumps(entry["feature_cols"]), json.dumps(entry["metrics"]),
                    entry.get("model_path"), entry["trained_at"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def registered_models(self) -> List[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """SELECT name, frame, target, horizon_days, kind, feature_cols, metrics,
                          model_path, trained_at
                   FROM models ORDER BY name"""
            ).fetchall()
        finally:
            conn.close()
        models = []
        for name, frame, target, horizon, kind, cols, metrics, path, trained_at in rows:
            try:
                parsed_metrics = json.loads(metrics)
            except (ValueError, TypeError):
                parsed_metrics = {}
            try:
                parsed_cols = json.loads(cols)
            except (ValueError, TypeError):
                parsed_cols = []
            models.append({
                "name": name, "frame": frame, "target": target, "horizon_days": int(horizon),
                "kind": kind, "feature_cols": parsed_cols, "metrics": parsed_metrics,
                "model_path": path, "trained_at": trained_at,
            })
        return models


# Instancia compartida por la API y el scheduler (tests usan la suya).
store = Store()
