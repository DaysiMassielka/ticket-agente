"""Evaluación: compara los borradores con data/esperado.csv y comprueba los controles de seguridad."""
import csv
import json
from pathlib import Path
from typing import Optional

from . import config
from .modelos import Borrador

CAMPOS = ["prioridad", "area", "accion", "runbook", "sospechoso"]


def cargar_esperado(ruta: Optional[Path] = None) -> dict[int, dict]:
    with open(ruta or config.RUTA_ESPERADO, newline="", encoding="utf-8") as f:
        return {int(r["ticket_id"]): r for r in csv.DictReader(f)}


def _obtenido(b: Borrador) -> dict:
    return {
        "prioridad": b.prioridad, "area": b.area, "accion": b.accion,
        "runbook": next((e.runbook_id for e in b.evidencia if e.tipo == "runbook" and e.runbook_id), ""),
        "sospechoso": "si" if b.sospechoso else "no",
    }


def evaluar(borradores: list[Borrador], esperado: dict[int, dict]) -> dict:
    """Acierto por campo y total (el ticket solo cuenta como acierto si TODOS los campos coinciden)."""
    aciertos = {c: 0 for c in CAMPOS}
    totales, errores = 0, []
    for b in borradores:
        esp = esperado.get(b.ticket_id)
        if esp is None:
            continue
        totales += 1
        obt = _obtenido(b)
        fallos = []
        for c in CAMPOS:
            esperado_c = esp["runbook_esperado"] if c == "runbook" else esp[c]
            if obt[c] == esperado_c:
                aciertos[c] += 1
            else:
                fallos.append(f"{c}: esperado {esperado_c or '-'} / obtenido {obt[c] or '-'}")
        if fallos:
            errores.append({"ticket": b.ticket_id, "fallos": fallos})
    completos = totales - len(errores)
    return {
        "tickets": totales, "ticket_completo": completos,
        "porcentaje_completo": round(100 * completos / totales, 1) if totales else 0.0,
        "por_campo": {c: {"aciertos": aciertos[c], "de": totales} for c in CAMPOS},
        "errores": errores,
    }


def controles(borradores: list[Borrador], carpeta: Optional[Path] = None) -> dict:
    """Comprobaciones de seguridad (deben ser 0). No miden al modelo: miden que el código pone los límites."""
    carpeta = Path(carpeta) if carpeta is not None else config.RUTA_SALIDA
    sin_evidencia = sum(1 for b in borradores if not b.evidencia)
    no_select = sum(1 for b in borradores for e in b.evidencia
                    if e.tipo == "sql" and not (e.consulta or "").lstrip().lower().startswith("select"))
    # Un Jira solo es legítimo si hay una línea de auditoría con la aprobación de ese ticket
    aprobados = set()
    ruta_aud = carpeta / "auditoria.jsonl"
    if ruta_aud.exists():
        for linea in ruta_aud.read_text(encoding="utf-8").splitlines():
            a = json.loads(linea)
            if a.get("decision") == "aprobar" and a.get("accion_ejecutada") == "jira_creado":
                aprobados.add(a["ticket_id"])
    jiras = {int(p.stem.split("_")[1]) for p in (carpeta / "jira").glob("ticket_*.json")} if (carpeta / "jira").exists() else set()
    return {"borradores_sin_evidencia": sin_evidencia, "consultas_no_select_ejecutadas": no_select,
            "escalados_sin_aprobacion": len(jiras - aprobados),
            "consultas_rechazadas": sum(1 for b in borradores for p in b.pasos if p.rechazado)}
