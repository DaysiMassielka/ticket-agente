"""El mismo flujo como grafo de LangGraph, con una INTERRUPCIÓN antes del nodo que ejecuta la decisión.

    triar  ──►  [pausa: espera a la persona]  ──►  decidir  ──►  fin

El grafo se detiene SOLO antes de "decidir": ahí no se ha creado nada todavía. Continúa únicamente cuando
alguien rellena la decisión (aprobar o rechazar) en el estado y lo reanuda. Es opcional: el flujo principal
(src/main.py y src/web.py) usa un bucle simple y no depende de LangGraph.
"""
from typing import Optional, TypedDict

from .agente import obtener_agente
from .aprobacion import aplicar_decision
from .modelos import Borrador
from .tickets import cargar_ticket


class Estado(TypedDict, total=False):
    ticket_id: int
    borrador: dict  # Borrador serializado
    aprobar: Optional[bool]  # None = todavía sin decisión
    texto_final: str
    quien: str
    decision: dict


def construir_grafo(agente=None):
    """Devuelve el grafo compilado, con memoria (MemorySaver) y pausa antes de 'decidir'."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    agente = agente or obtener_agente()

    def triar(estado: Estado) -> Estado:
        b = agente.triar(cargar_ticket(estado["ticket_id"]))
        return {"borrador": b.model_dump(mode="json"), "aprobar": None}

    def decidir(estado: Estado) -> Estado:
        # Defensa extra: si por error se llegara aquí sin decisión, no se hace nada
        if estado.get("aprobar") is None:
            return {"decision": {"decision": "sin decisión", "accion_ejecutada": "ninguna"}}
        b = Borrador(**estado["borrador"])
        d = aplicar_decision(b, aprobar=bool(estado["aprobar"]), texto_final=estado.get("texto_final") or b.texto,
                             quien=estado.get("quien", ""))
        return {"decision": d.model_dump()}

    g = StateGraph(Estado)
    g.add_node("triar", triar)
    g.add_node("decidir", decidir)
    g.add_edge(START, "triar")
    g.add_edge("triar", "decidir")
    g.add_edge("decidir", END)
    return g.compile(checkpointer=MemorySaver(), interrupt_before=["decidir"])


def iniciar(grafo, ticket_id: int, hilo: str) -> dict:
    """Ejecuta hasta la pausa. Devuelve el estado (con el borrador); aún no se ha creado nada."""
    cfg = {"configurable": {"thread_id": hilo}}
    grafo.invoke({"ticket_id": ticket_id}, cfg)
    return grafo.get_state(cfg).values


def reanudar(grafo, hilo: str, aprobar: bool, quien: str, texto_final: str = "") -> dict:
    """La persona decide: se rellena la decisión en el estado y el grafo continúa desde la pausa."""
    cfg = {"configurable": {"thread_id": hilo}}
    grafo.update_state(cfg, {"aprobar": aprobar, "quien": quien, "texto_final": texto_final})
    grafo.invoke(None, cfg)
    return grafo.get_state(cfg).values
