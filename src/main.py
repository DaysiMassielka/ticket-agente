"""CLI:  python -m src.main --ticket 5        triaje de un ticket y pregunta de aprobación
       python -m src.main --todos            los 10 tickets, uno a uno
       python -m src.main --ticket 5 --solo-borrador   muestra el borrador y NO pregunta ni crea nada
"""
import argparse
import sys

from .agente import ConfiguracionError, obtener_agente
from .aprobacion import AprobacionError, aplicar_decision, guardar_borrador
from .modelos import Borrador
from .tickets import cargar_ticket, cargar_todos


def mostrar(b: Borrador, ticket) -> None:
    print("=" * 78)
    print(f"Ticket {ticket.id}: {ticket.asunto}")
    print(f"Cliente: {ticket.cliente_email}\n{ticket.cuerpo}")
    print("-" * 78)
    print(f"Clasificación: prioridad {b.prioridad} · área {b.area} · acción propuesta: {b.accion.upper()}"
          + (f" → {b.equipo}" if b.equipo else ""))
    if b.sospechoso:
        print("⚠ CONTENIDO SOSPECHOSO: el ticket intenta dar órdenes al agente.")
    if b.motivo_escalado:
        print(f"Motivo: {b.motivo_escalado}")
    print("\nPasos del agente:")
    for i, p in enumerate(b.pasos, 1):
        marca = "RECHAZADO " if p.rechazado else ""
        entrada = p.entrada.get("sql") or p.entrada.get("consulta") or ""
        print(f"  {i}. {p.herramienta}: {marca}{p.resumen}\n     entrada: {entrada[:110].replace(chr(10), ' ')}")
    print("\nEvidencia:")
    for e in b.evidencia:
        if e.tipo == "sql":
            print(f"  [SQL] {e.consulta}\n        parámetros {e.parametros} → {e.n_filas} fila(s): {e.filas[:3]}")
        elif e.tipo == "runbook":
            print(f"  [Runbook] {e.runbook_id or 'ninguno'}" + (f" · {e.seccion} · puntuación {e.puntuacion}" if e.runbook_id else f" · {e.nota}"))
        else:
            print(f"  [Sistema] {e.nota}")
    print("\nBorrador:\n  " + b.texto.replace("\n", "\n  "))
    print("=" * 78)


def preguntar(b: Borrador) -> None:
    """Pide la decisión. Sin respuesta (o con EOF) no se hace nada: el valor por defecto es NO actuar."""
    texto = b.texto
    while True:
        accion = "escalar a Jira" if b.accion == "escalar" else "enviar la respuesta"
        try:
            r = input(f"¿Qué haces? [a]probar ({accion}) · [r]echazar · [e]ditar el texto · [s]altar: ").strip().lower()
        except EOFError:
            r = "s"
        if r.startswith("e"):
            nuevo = input("Nuevo texto (una línea; vacío = no cambiar): ").strip()
            texto = nuevo or texto
            print(f"Texto actual: {texto}")
            continue
        if r.startswith(("a", "r")):
            try:
                d = aplicar_decision(b, aprobar=r.startswith("a"), texto_final=texto, quien="operador")
            except AprobacionError as e:
                print(f"No se pudo aplicar: {e}")
                return
            print(f"→ {d.decision.upper()} · acción ejecutada: {d.accion_ejecutada} · registrado en la auditoría")
            return
        print("Sin decisión: no se ha creado nada.")
        return


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="ticket-agente")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticket", type=int, help="id del ticket (1 a 10)")
    g.add_argument("--todos", action="store_true", help="todos los tickets de ejemplo")
    ap.add_argument("--solo-borrador", action="store_true", help="no preguntar ni crear nada")
    args = ap.parse_args()

    try:
        agente = obtener_agente()
    except ConfiguracionError as e:
        print(f"Error de configuración: {e}")
        return 2
    print(f"Modo del agente: {agente.nombre.upper()}"
          + ("" if agente.es_llm else "  (SIN modelo de lenguaje: reglas y plantillas, solo para demostrar el flujo)"))
    try:
        tickets = cargar_todos() if args.todos else [cargar_ticket(args.ticket)]
    except KeyError as e:
        print(e.args[0])
        return 2
    for t in tickets:
        b = agente.triar(t)
        guardar_borrador(b)
        mostrar(b, t)
        if not args.solo_borrador:
            preguntar(b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
