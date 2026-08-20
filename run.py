"""Punto de entrada del dashboard NASA.

Uso:
    python run.py
"""
from __future__ import annotations

import sys

from config import settings


def main() -> int:
    if not settings.is_configured:
        print(
            "ADVERTENCIA: No se detecto un .env con API key real (usando DEMO_KEY).\n"
            "Copia .env.example a .env y edita NASA_API_KEY con tu key de https://api.nasa.gov/\n"
            "DEMO_KEY esta limitada a 30 req/hora y 50 req/dia.\n",
            file=sys.stderr,
        )

    from app import create_app

    app = create_app()
    print(f"Dashboard NASA arrancando en http://127.0.0.1:{settings.flask_port}")
    app.run(
        host="127.0.0.1",
        port=settings.flask_port,
        debug=settings.flask_debug,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
