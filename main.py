"""Entrada principal del proyecto.

Permite ejecutar el flujo completo con:

    python main.py

Los argumentos se delegan al orquestador de scrapers, por ejemplo:

    python main.py --max-pages 2 --skip-ml
"""

from scrapers.run_all_scrapers import main


if __name__ == "__main__":
    raise SystemExit(main())
