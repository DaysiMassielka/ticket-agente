"""Web: triaje, aprobación y auditoría (modo offline, sin red). Escribe en una carpeta temporal."""
import json

import pytest
from fastapi.testclient import TestClient

from src import config, web


@pytest.fixture()
def cliente(monkeypatch):
    monkeypatch.setenv("AGENTE", "offline")
    web._borradores.clear()
    web._decisiones.clear()
    monkeypatch.setattr(web, "_agente", None)
    return TestClient(web.app)


def _jiras():
    carpeta = config.RUTA_SALIDA / "jira"
    return sorted(p.name for p in carpeta.glob("*.json")) if carpeta.exists() else []


def test_pagina_y_modo(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "ticket-agente" in r.text and "Aprobar" in r.text
    assert cliente.get("/estilo/javbrian.css").status_code == 404 and cliente.get("/estilo/javbrain.css").status_code == 200
    e = cliente.get("/api/estado").json()
    assert e["modo"] == "offline" and e["es_llm"] is False


def test_lista_de_tickets_y_ticket_inexistente(cliente):
    lista = cliente.get("/api/tickets").json()
    assert len(lista) == 10 and all(t["estado"] == "sin analizar" for t in lista)
    assert cliente.get("/api/tickets/99").status_code == 404


def test_triar_no_crea_nada_externo_y_devuelve_evidencia(cliente):
    d = cliente.post("/api/tickets/5/triar").json()
    assert d["borrador"]["accion"] == "escalar" and d["borrador"]["evidencia"] and d["decision"] is None
    assert _jiras() == [] and not (config.RUTA_SALIDA / "auditoria.jsonl").exists()
    assert next(t for t in cliente.get("/api/tickets").json() if t["id"] == 5)["estado"] == "con borrador"


def test_aprobar_un_escalado_crea_el_jira_y_queda_en_la_auditoria(cliente):
    cliente.post("/api/tickets/5/triar")
    d = cliente.post("/api/tickets/5/decision", json={"decision": "aprobar", "texto_final": "Texto editado por la persona.", "quien": "daysi"}).json()
    assert d["decision"]["accion_ejecutada"] == "jira_creado" and _jiras() == ["ticket_05.json"]
    assert json.loads((config.RUTA_SALIDA / "jira" / "ticket_05.json").read_text(encoding="utf-8"))["descripcion"] == "Texto editado por la persona."
    a = cliente.get("/api/auditoria").json()
    assert a[0]["ticket_id"] == 5 and a[0]["quien"] == "daysi" and a[0]["decision"] == "aprobar"


def test_rechazar_no_crea_nada(cliente):
    cliente.post("/api/tickets/5/triar")
    d = cliente.post("/api/tickets/5/decision", json={"decision": "rechazar", "quien": "daysi"}).json()
    assert d["decision"]["accion_ejecutada"] == "ninguna" and _jiras() == []


def test_no_se_puede_decidir_sin_analizar_ni_dos_veces(cliente):
    assert cliente.post("/api/tickets/5/decision", json={"decision": "aprobar", "quien": "x"}).status_code == 409
    cliente.post("/api/tickets/5/triar")
    assert cliente.post("/api/tickets/5/decision", json={"decision": "aprobar", "quien": "x"}).status_code == 200
    assert cliente.post("/api/tickets/5/decision", json={"decision": "aprobar", "quien": "x"}).status_code == 409
    assert cliente.post("/api/tickets/5/triar").status_code == 409  # ya decidido: no se vuelve a analizar
    assert _jiras() == ["ticket_05.json"]


def test_validaciones_de_la_decision(cliente):
    cliente.post("/api/tickets/5/triar")
    assert cliente.post("/api/tickets/5/decision", json={"decision": "quizas", "quien": "x"}).status_code == 400
    assert cliente.post("/api/tickets/5/decision", json={"decision": "aprobar", "quien": "  "}).status_code == 422
    assert cliente.post("/api/tickets/5/decision", json={}).status_code == 422
    assert _jiras() == []


def test_ticket_sospechoso_se_marca_en_la_web(cliente):
    b = cliente.post("/api/tickets/10/triar").json()["borrador"]
    assert b["sospechoso"] is True and b["accion"] == "escalar"


def test_reiniciar_olvida_borradores_pero_no_la_auditoria(cliente):
    cliente.post("/api/tickets/5/triar")
    cliente.post("/api/tickets/5/decision", json={"decision": "aprobar", "quien": "x"})
    cliente.post("/api/reiniciar")
    assert all(t["estado"] == "sin analizar" for t in cliente.get("/api/tickets").json())
    assert len(cliente.get("/api/auditoria").json()) == 1 and _jiras() == ["ticket_05.json"]


def test_configuracion_invalida_da_503(cliente, monkeypatch):
    monkeypatch.setenv("AGENTE", "claude")  # sin clave
    r = cliente.post("/api/tickets/5/triar")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    monkeypatch.setenv("AGENTE", "otro")
    assert cliente.get("/api/estado").json()["modo"] == "error"


def test_el_javascript_de_la_pagina_es_sintacticamente_valido(cliente, tmp_path):
    """Un salto de linea mal escapado en la cadena de Python rompe todo el script sin que ningun test de la API lo note."""
    import re
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está instalado")
    js = re.search(r"<script>(.*)</script>", cliente.get("/").text, re.S).group(1)
    archivo = tmp_path / "pagina.js"
    archivo.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(archivo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
