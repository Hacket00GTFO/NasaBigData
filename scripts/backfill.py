"""Backfill del historial hacia la base SQLite del proyecto.

Construye el dataset para entrenar los modelos de prediccion. Es
idempotente: puede ejecutarse varias veces sin duplicar filas, por lo
que tambien sirve para rellenar huecos tras una interrupcion.

Ejemplos (desde la raiz del proyecto, con el venv activado):

    python scripts/backfill.py --source all
    python scripts/backfill.py --source donki --types FLR,CME,GST,SEP
    python scripts/backfill.py --source eonet --start 2005-01-01
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

# Permite ejecutar el script directamente: python scripts/backfill.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collector import backfill_donki, backfill_eonet, backfill_open_meteo  # noqa: E402
from app.db import store  # noqa: E402
from config import settings  # noqa: E402


def _parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("Usa fechas con formato YYYY-MM-DD.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill del dataset NASA para predicciones.")
    parser.add_argument("--source", choices=["all", "donki", "eonet", "openmeteo"], default="all",
                        help="Fuentes a descargar (por defecto: all).")
    parser.add_argument("--start", type=_parse_day, default=None,
                        help="Fecha inicial (por defecto 2010-01-01 para DONKI y 2000-01-01 para EONET/Open-Meteo).")
    parser.add_argument("--types", default=None,
                        help="Tipos DONKI separados por coma (por defecto FLR,CME,GST,SEP).")
    parser.add_argument("--end", type=_parse_day, default=None,
                        help="Fecha final (por defecto: hoy).")
    args = parser.parse_args()

    store.init()
    end = args.end or date.today()
    donki_start = args.start or date.fromisoformat(settings.donki_backfill_start)
    eonet_start = args.start or date.fromisoformat(settings.eonet_backfill_start)
    types = [t.strip().upper() for t in args.types.split(",") if t.strip()] if args.types else None

    print("Backfill hacia:", store.path)
    started = time.monotonic()
    if args.source in ("all", "donki"):
        print(f"\n[1/3] DONKI {donki_start} -> {end} (tipos: {','.join(types or settings.donki_backfill_types_list)})")
        result = backfill_donki(store, donki_start, end, types=types, progress=print)
        for event_type, info in result.items():
            print(f"  {event_type}: {info['rows']} eventos"
                  + (f" | errores: {len(info['errors'])}" if info["errors"] else ""))
    if args.source in ("all", "eonet"):
        print(f"\n[2/3] EONET {eonet_start} -> {end}")
        result = backfill_eonet(store, eonet_start, end, progress=print)
        print(f"  eventos: {result['rows']}"
              + (f" | errores: {len(result['errors'])}" if result["errors"] else ""))
    if args.source in ("all", "openmeteo"):
        print(f"\n[3/3] Open-Meteo {eonet_start} -> {end} (regiones propensas a incendios)")
        result = backfill_open_meteo(store, eonet_start, end, progress=print)
        print(f"  filas: {result['rows']}"
              + (f" | errores: {len(result['errors'])}" if result["errors"] else ""))

    summary = store.dataset_summary()
    minutes = (time.monotonic() - started) / 60
    print(f"\nResumen del dataset ({minutes:.1f} min):")
    for table in summary["tables"]:
        print(f"  {table['table']}: {table['rows']} filas ({table['from']} a {table['to']})")
    print(f"  Tamano: {summary['size_mb']} MB")
    print("\nSiguiente paso: python scripts/train_models.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
