"""Carga de los tickets de ejemplo (data/tickets/ticket_NN.json)."""
import json

from . import config
from .modelos import Ticket


def cargar_todos() -> list[Ticket]:
    return [Ticket(**json.loads(a.read_text(encoding="utf-8"))) for a in sorted(config.RUTA_TICKETS.glob("ticket_*.json"))]


def cargar_ticket(ticket_id: int) -> Ticket:
    for t in cargar_todos():
        if t.id == ticket_id:
            return t
    raise KeyError(f"No existe el ticket {ticket_id}")
