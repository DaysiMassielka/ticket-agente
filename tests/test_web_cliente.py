"""Versión para cliente: guía a un operador sin enseñar nada técnico, y mantiene las mismas garantías de aprobación."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from src import config, web_cliente

PROHIBIDAS = [r"\bsql\b", r"runbook", r"\brb-\d", r"similitud", r"puntuaci", r"offline", r"\bllm\b", r"\bselect\b", r"embedding",
              r"umbral", r"\bapi\b", r"\bjson\b", r"\bjira\b", r"5xx", r"endpoint", r"tf-idf", r"\bmodo\b"]


@pytest.fixture()
def cliente(monkeypatch):
    monkeypatch.setenv("AGENTE", "offline")
    web_cliente._borradores.clear()
    web_cliente._decisiones.clear()
    monkeypatch.setattr(web_cliente, "_agente", None)
    return TestClient(web_cliente.app)


def _jiras():
    carpeta = config.RUTA_SALIDA / "jira"
    return sorted(p.name for p in carpeta.glob("*.json")) if carpeta.exists() else []


def _textos(obj):
    """Todos los textos visibles de una respuesta (valores, no claves)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _textos(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _textos(v)


def _sin_tecnicismos(textos):
    for t in textos:
        for patron in PROHIBIDAS:
            assert not re.search(patron, t, re.IGNORECASE), f"lenguaje técnico ({patron}) en: {t[:120]}"


def test_la_pagina_no_muestra_lenguaje_tecnico(cliente):
    html = cliente.get("/").text
    visible = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
    _sin_tecnicismos([visible])
    assert "Demostraci" in html  # sigue avisando de que son datos ficticios


def test_ningun_caso_filtra_lenguaje_tecnico_en_lo_que_ve_el_operador(cliente):
    for i in range(1, 11):
        d = cliente.post(f"/api/casos/{i}/revisar").json()
        visible = {k: v for k, v in d["revision"].items() if k not in ("texto",)} | {"texto": d["revision"]["texto"]}
        _sin_tecnicismos(_textos(visible))  # el mensaje original del cliente (d["caso"]) no se revisa: lo escribe el cliente


def test_la_revision_solo_trae_lo_que_guia_al_operador(cliente):
    r = cliente.post("/api/casos/5/revisar").json()["revision"]
    assert set(r) == {"ticket_id", "prioridad", "prioridad_codigo", "prioridad_explicacion", "tipo", "siguiente_paso", "titular", "motivo",
                      "procedimiento", "sospechoso", "tabla", "texto", "etiqueta_texto", "boton_aprobar", "se_crea_algo"}
    assert r["prioridad"] == "Alta" and r["tipo"] == "Datos de la cuenta" and r["siguiente_paso"] == "Escalar"
    assert r["titular"] == "Hay que pasarlo a Desarrollo" and r["boton_aprobar"] == "Aprobar y pasar a Desarrollo"
    assert r["tabla"]["titulo"] == "Reserva y pago" and "Estado del pago" in r["tabla"]["columnas"]
    assert ["Cobrado"] in [[c for c in fila if c == "Cobrado"] for fila in r["tabla"]["filas"]]


def test_tabla_con_nombres_y_valores_legibles(cliente):
    t = cliente.post("/api/casos/1/revisar").json()["revision"]["tabla"]
    assert t["columnas"] == ["Nº", "Reserva", "Importe (€)", "Estado", "Referencia", "Fecha"]
    assert t["filas"][0][2] == "120,00" and t["filas"][0][3] == "Cobrado"  # importes con coma y estados con palabras normales


def test_ticket_sospechoso_avisa_con_palabras_normales(cliente):
    r = cliente.post("/api/casos/10/revisar").json()["revision"]
    assert r["sospechoso"] is True and r["siguiente_paso"] == "Escalar"


def test_caso_sin_procedimiento_se_explica_sin_jerga(cliente):
    r = cliente.post("/api/casos/9/revisar").json()["revision"]
    assert "No existe un procedimiento definido" in r["procedimiento"] and r["tabla"] is None
    assert "no hay un procedimiento definido" in r["motivo"]


def test_aprobar_escalado_crea_el_traspaso_y_lo_dice_en_claro(cliente):
    cliente.post("/api/casos/5/revisar")
    d = cliente.post("/api/casos/5/decision", json={"aprobar": True, "texto": "Resumen revisado.", "quien": "Daysi"}).json()
    assert d["decision"]["mensaje"].startswith("Hecho: el caso se ha pasado a Desarrollo") and d["caso"]["estado"] == "Aprobado"
    assert _jiras() == ["ticket_05.json"]
    h = cliente.get("/api/historial").json()
    assert h == [{"cuando": h[0]["cuando"], "caso": 5, "quien": "Daysi", "resultado": "Pasado al equipo"}]


def test_no_aprobar_no_hace_nada(cliente):
    cliente.post("/api/casos/5/revisar")
    d = cliente.post("/api/casos/5/decision", json={"aprobar": False, "quien": "Daysi"}).json()
    assert d["decision"]["mensaje"] == "No se ha aprobado. No se ha enviado ni creado nada." and _jiras() == []
    assert cliente.get("/api/historial").json()[0]["resultado"] == "No aprobado"


def test_aprobar_una_respuesta_no_pasa_nada_al_equipo(cliente):
    cliente.post("/api/casos/3/revisar")
    d = cliente.post("/api/casos/3/decision", json={"aprobar": True, "quien": "Daysi"}).json()
    assert d["decision"]["mensaje"].startswith("Respuesta aprobada") and _jiras() == []


def test_sin_nombre_no_se_puede_aprobar_y_el_mensaje_esta_en_claro(cliente):
    cliente.post("/api/casos/5/revisar")
    r = cliente.post("/api/casos/5/decision", json={"aprobar": True, "quien": " "})
    assert r.status_code == 422 and r.json()["detail"] == "Escribe tu nombre para poder aprobar." and _jiras() == []
    r = cliente.post("/api/casos/5/decision", json={"aprobar": True, "texto": "  ", "quien": "Daysi"})
    assert r.status_code == 422 and r.json()["detail"] == "El texto no puede estar vacío."


def test_no_se_puede_decidir_sin_revisar_ni_dos_veces(cliente):
    assert cliente.post("/api/casos/5/decision", json={"aprobar": True, "quien": "x"}).status_code == 409
    cliente.post("/api/casos/5/revisar")
    assert cliente.post("/api/casos/5/decision", json={"aprobar": True, "quien": "x"}).status_code == 200
    r = cliente.post("/api/casos/5/decision", json={"aprobar": True, "quien": "x"})
    assert r.status_code == 409 and r.json()["detail"] == "Este caso ya está resuelto."
    assert cliente.post("/api/casos/5/revisar").status_code == 409


def test_la_bandeja_refleja_el_estado_de_cada_caso(cliente):
    estados = lambda: {c["id"]: c["estado"] for c in cliente.get("/api/bandeja").json()}
    assert set(estados().values()) == {"Por revisar"}
    cliente.post("/api/casos/5/revisar")
    cliente.post("/api/casos/3/revisar")
    cliente.post("/api/casos/3/decision", json={"aprobar": False, "quien": "x"})
    assert (estados()[5], estados()[3], estados()[1]) == ("Revisado", "No aprobado", "Por revisar")
    assert cliente.get("/api/casos/99").status_code == 404


def test_si_el_asistente_no_esta_disponible_el_mensaje_no_enseña_detalles_internos(cliente, monkeypatch):
    monkeypatch.setenv("AGENTE", "claude")  # sin clave
    r = cliente.post("/api/casos/5/revisar")
    assert r.status_code == 503 and r.json()["detail"] == web_cliente.NO_DISPONIBLE and "ANTHROPIC" not in r.text


def test_el_javascript_es_valido(cliente, tmp_path):
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está instalado")
    js = re.search(r"<script>(.*)</script>", cliente.get("/").text, re.S).group(1)
    f = tmp_path / "p.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
