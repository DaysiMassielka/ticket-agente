"""Ejecuta el agente sobre los 10 tickets SIN interacción y compara con data/esperado.csv.

Uso:   python evaluar.py            (modo según AGENTE / ANTHROPIC_API_KEY)
No aprueba ni escala nada: solo triaje y medición. Escribe output/evaluacion.json.
"""
import json
import sys

from src import config
from src.agente import ConfiguracionError, obtener_agente
from src.aprobacion import guardar_borrador
from src.evaluacion import CAMPOS, cargar_esperado, controles, evaluar
from src.tickets import cargar_todos


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        agente = obtener_agente()
    except ConfiguracionError as e:
        print(f"Error de configuración: {e}")
        return 2
    borradores = []
    for t in cargar_todos():
        b = agente.triar(t)
        guardar_borrador(b)
        borradores.append(b)

    ev, ctl = evaluar(borradores, cargar_esperado()), controles(borradores)
    print(f"Modo del agente: {agente.nombre}" + ("" if agente.es_llm else "  (SIN LLM: reglas; mide el flujo, no la comprensión de un modelo)"))
    print(f"Tickets completos (todos los campos bien): {ev['ticket_completo']}/{ev['tickets']} ({ev['porcentaje_completo']}%)")
    print("Acierto por campo:")
    for c in CAMPOS:
        print(f"  {c:<11} {ev['por_campo'][c]['aciertos']}/{ev['por_campo'][c]['de']}")
    for e in ev["errores"]:
        print(f"  ✗ ticket {e['ticket']}: " + "; ".join(e["fallos"]))
    print("\nControles de seguridad (deben ser 0, salvo las consultas rechazadas, que son buena señal):")
    print(f"  borradores sin evidencia:          {ctl['borradores_sin_evidencia']}")
    print(f"  consultas no SELECT ejecutadas:    {ctl['consultas_no_select_ejecutadas']}")
    print(f"  escalados sin aprobación:          {ctl['escalados_sin_aprobacion']}")
    print(f"  consultas rechazadas por el código: {ctl['consultas_rechazadas']}")

    config.RUTA_SALIDA.mkdir(parents=True, exist_ok=True)
    (config.RUTA_SALIDA / "evaluacion.json").write_text(
        json.dumps({"modo": agente.nombre, "evaluacion": ev, "controles": ctl}, ensure_ascii=False, indent=2), encoding="utf-8")
    seguro = ctl["borradores_sin_evidencia"] == ctl["consultas_no_select_ejecutadas"] == ctl["escalados_sin_aprobacion"] == 0
    return 0 if seguro and not ev["errores"] else 1


if __name__ == "__main__":
    sys.exit(main())
