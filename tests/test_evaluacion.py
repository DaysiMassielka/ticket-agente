"""La evaluación detecta los fallos de verdad y los controles detectan un escalado sin aprobación."""
import json

import pytest

from src import config
from src.agente import AgenteOffline
from src.aprobacion import aplicar_decision, ruta_jira
from src.evaluacion import cargar_esperado, controles, evaluar
from src.rag import Indice
from src.tickets import cargar_todos


@pytest.fixture(scope="module")
def borradores(tmp_path_factory):
    agente = AgenteOffline(Indice.construir(cache=tmp_path_factory.mktemp("cache")))
    return [agente.triar(t) for t in cargar_todos()]


def test_evaluar_da_10_de_10_en_modo_offline(borradores):
    ev = evaluar(borradores, cargar_esperado())
    assert ev["ticket_completo"] == 10 and ev["porcentaje_completo"] == 100.0 and ev["errores"] == []


def test_evaluar_detecta_un_fallo_y_dice_cual(borradores):
    rotos = [b.model_copy(update={"prioridad": "P4"}) if b.ticket_id == 1 else b for b in borradores]  # la 1 era P2
    ev = evaluar(rotos, cargar_esperado())
    assert ev["ticket_completo"] == 9 and ev["porcentaje_completo"] == 90.0
    assert ev["errores"] == [{"ticket": 1, "fallos": ["prioridad: esperado P2 / obtenido P4"]}]
    assert ev["por_campo"]["prioridad"] == {"aciertos": 9, "de": 10} and ev["por_campo"]["area"]["aciertos"] == 10


def test_controles_en_cero_cuando_todo_va_bien(borradores):
    assert controles(borradores) == {"borradores_sin_evidencia": 0, "consultas_no_select_ejecutadas": 0,
                                     "escalados_sin_aprobacion": 0, "consultas_rechazadas": 0}


def test_el_control_detecta_un_jira_sin_aprobacion_en_la_auditoria(borradores):
    aplicar_decision(borradores[0], aprobar=True)  # legítimo: aprobado, con auditoría
    assert controles(borradores)["escalados_sin_aprobacion"] == 0
    ruta_jira(4).parent.mkdir(parents=True, exist_ok=True)
    ruta_jira(4).write_text(json.dumps({"colado": True}), encoding="utf-8")  # alguien crea un Jira por su cuenta
    assert controles(borradores)["escalados_sin_aprobacion"] == 1


def test_el_control_detecta_una_consulta_no_select_en_la_evidencia(borradores):
    from src.modelos import Evidencia
    e = Evidencia(tipo="sql", consulta="DELETE FROM pagos")
    malo = borradores[0].model_copy(update={"evidencia": [e]})
    assert controles([malo])["consultas_no_select_ejecutadas"] == 1
