"""El grafo de LangGraph se detiene antes de decidir y solo continúa cuando la persona decide."""
import json

import pytest

pytest.importorskip("langgraph")

from src import config  # noqa: E402
from src.agente import AgenteOffline  # noqa: E402
from src.grafo import construir_grafo, iniciar, reanudar  # noqa: E402
from src.rag import Indice  # noqa: E402


@pytest.fixture()
def grafo(tmp_path):
    return construir_grafo(AgenteOffline(Indice.construir(cache=tmp_path / "c")))


def _jiras():
    carpeta = config.RUTA_SALIDA / "jira"
    return sorted(p.name for p in carpeta.glob("*.json")) if carpeta.exists() else []


def test_el_grafo_se_detiene_antes_de_decidir_y_no_crea_nada(grafo):
    estado = iniciar(grafo, 5, "hilo-1")
    assert estado["borrador"]["accion"] == "escalar" and estado.get("decision") is None
    assert grafo.get_state({"configurable": {"thread_id": "hilo-1"}}).next == ("decidir",)  # parado en la pausa
    assert _jiras() == [] and not (config.RUTA_SALIDA / "auditoria.jsonl").exists()


def test_al_aprobar_continua_y_crea_el_jira(grafo):
    iniciar(grafo, 5, "hilo-2")
    estado = reanudar(grafo, "hilo-2", aprobar=True, quien="daysi", texto_final="Texto final.")
    assert estado["decision"]["accion_ejecutada"] == "jira_creado" and _jiras() == ["ticket_05.json"]
    assert grafo.get_state({"configurable": {"thread_id": "hilo-2"}}).next == ()  # el grafo terminó


def test_al_rechazar_continua_pero_no_crea_nada(grafo):
    iniciar(grafo, 5, "hilo-3")
    estado = reanudar(grafo, "hilo-3", aprobar=False, quien="daysi")
    assert estado["decision"]["accion_ejecutada"] == "ninguna" and _jiras() == []
    assert json.loads((config.RUTA_SALIDA / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()[0])["decision"] == "rechazar"


def test_dos_hilos_son_independientes(grafo):
    iniciar(grafo, 5, "a")
    iniciar(grafo, 1, "b")
    reanudar(grafo, "b", aprobar=True, quien="daysi")
    assert _jiras() == ["ticket_01.json"]  # el hilo "a" sigue parado, sin decidir
    assert grafo.get_state({"configurable": {"thread_id": "a"}}).next == ("decidir",)
