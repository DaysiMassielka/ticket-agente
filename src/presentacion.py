"""Traduce un Borrador técnico a lenguaje de operador: sin SQL, sin ids de runbook, sin puntuaciones ni pasos internos.

Lo usa la versión para cliente (src/web_cliente.py). La versión técnica (src/web.py) sigue mostrando todo el detalle.
"""
import re
from typing import Optional

from .modelos import Borrador, Evidencia

PRIORIDAD = {"P1": ("Crítica", "Afecta a muchos clientes: hay que actuar ya."),
             "P2": ("Alta", "Un cliente ha pagado y no recibe lo que debe, o tiene un cobro erróneo."),
             "P3": ("Media", "Un cliente no puede usar el servicio, pero no hay dinero en riesgo."),
             "P4": ("Baja", "Consulta o espera normal.")}
AREA = {"SQL": "Datos de la cuenta", "API": "Sistema o integración", "negocio": "Atención al cliente"}

COLUMNAS = {
    "id": "Nº", "reserva_id": "Reserva", "pago_id": "Pago", "importe": "Importe (€)", "estado": "Estado", "referencia": "Referencia",
    "creado_en": "Fecha", "email": "Correo", "rol": "Rol", "ultimo_acceso": "Último acceso", "estado_reserva": "Estado de la reserva",
    "estado_pago": "Estado del pago", "codigo": "Código de error", "total": "Veces", "desde": "Desde", "hasta": "Hasta",
}
VALORES = {
    "cobrado": "Cobrado", "retenido": "Retenido por el banco", "pendiente": "Pendiente", "fallido": "Fallido", "confirmada": "Confirmada",
    "cancelada": "Cancelada", "activo": "Activo", "bloqueado_intentos": "Bloqueada por intentos fallidos",
    "reembolso_en_proceso": "Reembolso en proceso",
}
TITULO_TABLA = {"RB-01": "Pagos de la reserva", "RB-02": "Cuenta del cliente", "RB-03": "Reserva y pago",
                "RB-04": "Errores del cobro online", "RB-05": "Pago y reembolso"}
# Nombres de los procedimientos en lenguaje de operador (los títulos internos de los runbooks son más técnicos)
PROCEDIMIENTO = {"RB-01": "Pago duplicado", "RB-02": "Usuario sin acceso", "RB-03": "Reserva sin confirmar",
                 "RB-04": "Errores al cobrar online", "RB-05": "Reembolso pendiente"}
# Columnas que no aportan a un operador
OCULTAS = {"id_usuario"}


def _celda(v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}".replace(".", ",")
    return VALORES.get(str(v), str(v))


def _tabla(e: Evidencia, titulo: str) -> Optional[dict]:
    if not e.filas:
        return {"titulo": titulo, "columnas": [], "filas": [], "vacia": True}
    cols = [c for c in e.filas[0] if c not in OCULTAS]
    return {"titulo": titulo, "columnas": [COLUMNAS.get(c, c.replace("_", " ").capitalize()) for c in cols],
            "filas": [[_celda(f.get(c)) for c in cols] for f in e.filas[:8]], "vacia": False}


def _limpiar(texto: str) -> str:
    """Quita referencias internas como (RB-01) del texto."""
    return re.sub(r"\s*\(RB-\d+\)", "", texto).strip()


def a_vista(b: Borrador) -> dict:
    nombre_prio, explicacion = PRIORIDAD[b.prioridad]
    rb = next((e for e in b.evidencia if e.tipo == "runbook"), None)
    rb_id = rb.runbook_id if rb else None
    sql = next((e for e in b.evidencia if e.tipo == "sql"), None)

    if rb_id:
        procedimiento = f"Se ha seguido el procedimiento «{PROCEDIMIENTO.get(rb_id, 'interno')}»."
    else:
        procedimiento = "No existe un procedimiento definido para este caso, por eso lo revisa una persona."

    if b.accion == "escalar":
        titular = f"Hay que pasarlo a {b.equipo}" if b.equipo else "Hay que pasarlo a otro equipo"
        motivo = _limpiar(b.motivo_escalado.replace("sin procedimiento documentado", "no hay un procedimiento definido para este tipo de petición"))
        boton = f"Aprobar y pasar a {b.equipo}" if b.equipo else "Aprobar y escalar"
        etiqueta_texto = "Resumen para el equipo (puedes editarlo)"
    else:
        titular = "Se puede resolver con una respuesta al cliente"
        motivo = ""
        boton = "Aprobar respuesta"
        etiqueta_texto = "Respuesta al cliente (puedes editarla)"

    return {
        "ticket_id": b.ticket_id,
        "prioridad": nombre_prio, "prioridad_codigo": b.prioridad, "prioridad_explicacion": explicacion,
        "tipo": AREA[b.area],
        "siguiente_paso": "Escalar" if b.accion == "escalar" else "Responder",
        "titular": titular, "motivo": motivo, "procedimiento": procedimiento,
        "sospechoso": b.sospechoso,
        "tabla": _tabla(sql, TITULO_TABLA.get(rb_id, "Datos consultados")) if sql else None,
        "texto": b.texto, "etiqueta_texto": etiqueta_texto, "boton_aprobar": boton,
        "se_crea_algo": b.accion == "escalar",
    }


def resultado_decision(accion_ejecutada: str, decision: str, equipo: str = "") -> str:
    if decision == "rechazar":
        return "No se ha aprobado. No se ha enviado ni creado nada."
    if accion_ejecutada == "jira_creado":
        return f"Hecho: el caso se ha pasado a {equipo or 'el equipo'}. Queda registrado quién lo aprobó y cuándo."
    return "Respuesta aprobada. Queda registrado quién la aprobó y cuándo."
