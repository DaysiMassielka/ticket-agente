"""Configuración común: rutas, límites de seguridad y modelo."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")  # no pisa las variables que ya estén en el entorno

RUTA_DB = RAIZ / "data" / "reservas.db"
RUTA_TICKETS = RAIZ / "data" / "tickets"
RUTA_RUNBOOKS = RAIZ / "data" / "runbooks"
RUTA_ESPERADO = RAIZ / "data" / "esperado.csv"
RUTA_SALIDA = RAIZ / "output"
RUTA_CACHE = RAIZ / ".cache"

# Herramienta SQL: lo que el agente NUNCA puede saltarse (lo impone el código, no el prompt)
TABLAS_PERMITIDAS = {"usuarios", "reservas", "pagos", "logs_api"}
MAX_FILAS = 50
TIEMPO_MAX_SQL = 2.0  # segundos

# Agente
MAX_PASOS = 6  # llamadas a herramientas por ticket
# Un runbook solo se cita si su mejor fragmento llega a esta similitud (calibrado con los 10 tickets: el ticket 9 saca 0.169 y el peor acierto 0.213, margen estrecho)
UMBRAL_SIMILITUD = 0.19


def nombre_modelo() -> str:
    return os.environ.get("MODEL_NAME") or "claude-haiku-5-5"
