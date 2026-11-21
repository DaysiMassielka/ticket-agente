"""La puerta humana: sin aprobación explícita no se crea nada, y todo queda en la auditoría."""
import json

import pytest

from src import config
from src.agente import AgenteOffline
from src.aprobacion import AprobacionError, aplicar_decision, guardar_borrador, ruta_jira
from src.rag import Indice
from src.tickets import cargar_ticket, cargar_todos


@pytest.fixture(scope="module")
def indice(tmp_path_factory):
    return Indice.construir(cache=tmp_path_factory.mktemp("cache"))


def _auditoria():
    ruta = config.RUTA_SALIDA / "auditoria.jsonl"
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines()] if ruta.exists() else []


def _jiras():
    carpeta = config.RUTA_SALIDA / "jira"
    return sorted(p.name for p in carpeta.glob("*.json")) if carpeta.exists() else []


def test_a_el_agente_solo_no_crea_nada_aunque_triemos_los_10(indice):
    """(a) Sin aprobación explícita no se crea nada: ni Jira ni auditoría."""
    agente = AgenteOffline(indice)
    for t in cargar_todos():
        guardar_borrador(agente.triar(t))  # guardar el borrador no es escalar
    assert _jiras() == [] and _auditoria() == []
    assert len(list((config.RUTA_SALIDA / "borradores").glob("*.json"))) == 10


def test_b_escalar_aprobado_crea_el_jira_simulado_con_la_evidencia(indice):
    b = AgenteOffline(indice).triar(cargar_ticket(1))
    d = aplicar_decision(b, aprobar=True, quien="daysi")
    assert d.accion_ejecutada == "jira_creado" and _jiras() == ["ticket_01.json"]
    jira = json.loads(ruta_jira(1).read_text(encoding="utf-8"))
    assert jira["aprobado_por"] == "daysi" and jira["equipo"] == "Finanzas" and jira["prioridad"] == "P2"
    assert any(e["tipo"] == "sql" and e["consulta"] for e in jira["evidencia"]) and any(e["tipo"] == "runbook" for e in jira["evidencia"])


def test_c_rechazar_no_crea_nada_pero_queda_auditado(indice):
    b = AgenteOffline(indice).triar(cargar_ticket(1))
    d = aplicar_decision(b, aprobar=False, quien="daysi")
    assert d.accion_ejecutada == "ninguna" and _jiras() == []
    assert [a["decision"] for a in _auditoria()] == ["rechazar"]


def test_aprobar_una_respuesta_no_crea_jira(indice):
    b = AgenteOffline(indice).triar(cargar_ticket(3))  # responder
    d = aplicar_decision(b, aprobar=True)
    assert b.accion == "responder" and d.accion_ejecutada == "respuesta_aprobada" and _jiras() == []


def test_d_la_auditoria_guarda_el_texto_editado_y_el_original_del_agente(indice):
    b = AgenteOffline(indice).triar(cargar_ticket(5))
    aplicar_decision(b, aprobar=True, texto_final="Texto corregido por la persona.", quien="daysi")
    a = _auditoria()[0]
    assert a["texto_final"] == "Texto corregido por la persona." and a["texto_original_del_agente"] == b.texto
    assert a["quien"] == "daysi" and a["cuando"] and a["consultas"] and a["runbooks_citados"] == ["RB-03"]
    assert json.loads(ruta_jira(5).read_text(encoding="utf-8"))["descripcion"] == "Texto corregido por la persona."


def test_la_auditoria_recoge_las_consultas_rechazadas(indice):
    b = AgenteOffline(indice).triar(cargar_ticket(10))
    b.pasos.append(b.pasos[-1].model_copy(update={"herramienta": "consultar_sql", "entrada": {"sql": "DELETE FROM pagos"},
                                                  "resumen": "consulta rechazada: solo se permiten consultas SELECT", "rechazado": True}))
    aplicar_decision(b, aprobar=True)
    assert _auditoria()[0]["consultas_rechazadas"] == ["DELETE FROM pagos"] and _auditoria()[0]["sospechoso"] is True


def test_no_se_escala_dos_veces_el_mismo_ticket(indice):
    b = AgenteOffline(indice).triar(cargar_ticket(1))
    aplicar_decision(b, aprobar=True)
    with pytest.raises(AprobacionError, match="ya se escaló"):
        aplicar_decision(b, aprobar=True)
    assert len(_auditoria()) == 1  # el segundo intento no deja una decisión falsa


@pytest.mark.parametrize("texto,quien", [("   ", "daysi"), ("ok", "  ")])
def test_texto_vacio_o_sin_responsable_se_rechaza_sin_crear_nada(indice, texto, quien):
    b = AgenteOffline(indice).triar(cargar_ticket(1))
    with pytest.raises(AprobacionError):
        aplicar_decision(b, aprobar=True, texto_final=texto, quien=quien)
    assert _jiras() == [] and _auditoria() == []


def test_un_borrador_sin_evidencia_no_es_valido():
    from src.modelos import Borrador
    with pytest.raises(ValueError, match="sin evidencia"):
        Borrador(ticket_id=1, prioridad="P3", area="SQL", accion="escalar", texto="x", evidencia=[])


def test_cli_sin_respuesta_no_hace_nada(indice, monkeypatch, capsys):
    from src import main as cli
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError()))
    cli.preguntar(AgenteOffline(indice).triar(cargar_ticket(1)))
    assert _jiras() == [] and _auditoria() == [] and "Sin decisión" in capsys.readouterr().out


def test_cli_aprobar_editando_el_texto(indice, monkeypatch):
    from src import main as cli
    respuestas = iter(["e", "Texto editado en la CLI", "a"])
    monkeypatch.setattr("builtins.input", lambda *_: next(respuestas))
    cli.preguntar(AgenteOffline(indice).triar(cargar_ticket(1)))
    assert _jiras() == ["ticket_01.json"] and _auditoria()[0]["texto_final"] == "Texto editado en la CLI"
