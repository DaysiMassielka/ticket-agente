"""Herramienta SQL de SOLO LECTURA. La seguridad la impone este código, no el prompt.

Capas de defensa (si una falla, las otras siguen protegiendo):
  1. La conexión se abre en solo lectura (URI de SQLite con mode=ro) y con PRAGMA query_only=ON.
  2. La consulta se valida ANTES de ejecutarla: una sola sentencia, que empiece por SELECT,
     sin comentarios, sin palabras de escritura y solo sobre tablas de la lista permitida.
  3. Se devuelven como máximo MAX_FILAS filas y la ejecución se corta pasado un tiempo máximo.

Nunca lanza excepciones por una consulta rechazada: devuelve {"ok": False, "error": "consulta rechazada: ..."}
para que el agente (y la auditoría) vean el motivo.
"""
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from . import config

# Palabras que no pueden aparecer nunca (como palabra completa), ni siquiera dentro de un SELECT
PALABRAS_PROHIBIDAS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace", "attach", "detach",
    "pragma", "vacuum", "reindex", "load_extension", "truncate", "grant", "revoke",
}
_RE_TABLAS = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_RE_PALABRAS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ConsultaRechazada(Exception):
    """La consulta no cumple las reglas de seguridad."""


def _sin_cadenas(sql: str) -> str:
    """Quita el contenido de los literales entre comillas simples para no confundirlo con palabras de la consulta."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validar(sql: str, tablas_permitidas: Optional[set] = None) -> str:
    """Devuelve la consulta limpia o lanza ConsultaRechazada con el motivo."""
    tablas_permitidas = tablas_permitidas if tablas_permitidas is not None else config.TABLAS_PERMITIDAS
    if not isinstance(sql, str) or not sql.strip():
        raise ConsultaRechazada("la consulta está vacía")
    limpia = sql.strip()
    if limpia.endswith(";"):
        limpia = limpia[:-1].rstrip()  # un único punto y coma final es inofensivo
    sin_literales = _sin_cadenas(limpia)

    if "--" in sin_literales or "/*" in sin_literales or "*/" in sin_literales:
        raise ConsultaRechazada("no se permiten comentarios")
    if ";" in sin_literales:
        raise ConsultaRechazada("solo se permite una sentencia")
    if not re.match(r"select\b", sin_literales, re.IGNORECASE):
        raise ConsultaRechazada("solo se permiten consultas SELECT")
    prohibidas = {p.lower() for p in _RE_PALABRAS.findall(sin_literales)} & PALABRAS_PROHIBIDAS
    if prohibidas:
        raise ConsultaRechazada(f"palabra no permitida: {', '.join(sorted(prohibidas))}")
    tablas = {t.lower() for t in _RE_TABLAS.findall(sin_literales)}
    if not tablas:
        raise ConsultaRechazada("la consulta debe leer de alguna tabla")
    no_permitidas = tablas - {t.lower() for t in tablas_permitidas}
    if no_permitidas:
        raise ConsultaRechazada(f"tabla no permitida: {', '.join(sorted(no_permitidas))}")
    return limpia


def _conectar_solo_lectura(ruta: Path) -> sqlite3.Connection:
    # Ruta en formato URI: SQLite exige barras normales aunque estemos en Windows
    con = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def consultar_sql(sql: str, params: Optional[dict] = None, ruta_db: Optional[Path] = None) -> dict:
    """Ejecuta una consulta de solo lectura.

    Devuelve {"ok": True, "consulta": ..., "filas": [dict...], "n_filas": N, "truncado": bool}
    o       {"ok": False, "consulta": ..., "error": "consulta rechazada: ..."}.
    """
    try:
        limpia = validar(sql)
    except ConsultaRechazada as e:
        return {"ok": False, "consulta": str(sql), "error": f"consulta rechazada: {e}"}

    ruta = Path(ruta_db) if ruta_db is not None else config.RUTA_DB
    try:
        con = _conectar_solo_lectura(ruta)
    except sqlite3.Error as e:
        return {"ok": False, "consulta": limpia, "error": f"no se pudo abrir la base de datos: {e}"}
    try:
        limite = time.monotonic() + config.TIEMPO_MAX_SQL
        # Cada 10.000 instrucciones internas comprueba el reloj; devolver 1 aborta la consulta
        con.set_progress_handler(lambda: 1 if time.monotonic() > limite else 0, 10_000)
        cur = con.execute(limpia, params or {})
        filas = cur.fetchmany(config.MAX_FILAS + 1)
        truncado = len(filas) > config.MAX_FILAS
        filas = [dict(f) for f in filas[: config.MAX_FILAS]]
        return {"ok": True, "consulta": limpia, "filas": filas, "n_filas": len(filas), "truncado": truncado}
    except sqlite3.Error as e:
        return {"ok": False, "consulta": limpia, "error": f"error al ejecutar la consulta: {e}"}
    finally:
        con.close()
