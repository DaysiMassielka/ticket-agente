"""Puerta de aprobación humana, Jira simulado y registro de auditoría.

Regla central: este es el ÚNICO sitio del programa que crea un ticket de Jira (simulado), y solo lo hace si
una persona aprueba de forma explícita (aplicar_decision con aprobar=True). El agente solo produce Borradores:
no tiene ninguna forma de llegar hasta aquí por su cuenta.
"""
import json
import os
from datetime import datetime
from typing import Optional

from . import config
from .modelos import Borrador, Decision


class AprobacionError(Exception):
    """La decisión no se puede aplicar (texto vacío, ticket ya escalado...)."""


def _carpeta(nombre: str):
    c = config.RUTA_SALIDA / nombre  # se lee en el momento de usarla (los tests la desvían a una carpeta temporal)
    c.mkdir(parents=True, exist_ok=True)
    return c


def _escribir_json(ruta, datos) -> None:
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)  # atómico: nunca queda un archivo a medias


def guardar_borrador(b: Borrador) -> str:
    """Guarda el borrador (con su evidencia) en output/borradores/. No crea nada externo."""
    ruta = _carpeta("borradores") / f"ticket_{b.ticket_id:02d}.json"
    _escribir_json(ruta, b.model_dump(mode="json"))
    return str(ruta)


def ruta_jira(ticket_id: int):
    return config.RUTA_SALIDA / "jira" / f"ticket_{ticket_id:02d}.json"


def _auditar(b: Borrador, d: Decision) -> None:
    linea = {
        **d.model_dump(),
        "modo_agente": b.modo, "prioridad": b.prioridad, "area": b.area, "sospechoso": b.sospechoso,
        "motivo_escalado": b.motivo_escalado,
        "texto_original_del_agente": b.texto,
        "consultas": [e.consulta for e in b.evidencia if e.tipo == "sql"],
        "consultas_rechazadas": [p.entrada.get("sql") for p in b.pasos if p.rechazado],
        "runbooks_citados": [e.runbook_id for e in b.evidencia if e.tipo == "runbook" and e.runbook_id],
    }
    ruta = _carpeta("") / "auditoria.jsonl"
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def aplicar_decision(b: Borrador, aprobar: bool, texto_final: Optional[str] = None, quien: str = "operador") -> Decision:
    """Aplica la decisión de la persona. Con aprobar=False no se crea nada (solo queda en la auditoría)."""
    texto = (texto_final if texto_final is not None else b.texto).strip()
    if not texto:
        raise AprobacionError("El texto final no puede estar vacío.")
    quien = (quien or "").strip()
    if not quien:
        raise AprobacionError("Indica quién aprueba.")
    if aprobar and b.accion == "escalar" and ruta_jira(b.ticket_id).exists():
        # Igual que un cobro duplicado: no se crea dos veces el mismo ticket de Jira
        raise AprobacionError(f"El ticket {b.ticket_id} ya se escaló antes.")

    ejecutada = "ninguna"
    cuando = datetime.now().isoformat(timespec="seconds")
    if aprobar and b.accion == "escalar":
        _escribir_json(_carpeta("jira") / f"ticket_{b.ticket_id:02d}.json",
                       {**(b.jira or {}), "descripcion": texto, "aprobado_por": quien, "aprobado_en": cuando, "estado": "Creado (simulado)"})
        ejecutada = "jira_creado"
    elif aprobar:
        ejecutada = "respuesta_aprobada"  # se aprueba la respuesta; no se envía nada desde este prototipo

    decision = Decision(ticket_id=b.ticket_id, decision="aprobar" if aprobar else "rechazar", quien=quien, cuando=cuando,
                        texto_final=texto, accion_propuesta=b.accion, accion_ejecutada=ejecutada)
    _auditar(b, decision)
    return decision
