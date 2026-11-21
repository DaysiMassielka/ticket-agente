"""Búsqueda en runbooks: el runbook correcto sale primero y lo que no está documentado no supera el umbral."""
import csv
import json

import pytest

from src import config
from src.rag import Indice, tokenizar, trocear


@pytest.fixture(scope="module")
def indice(tmp_path_factory):
    return Indice.construir(cache=tmp_path_factory.mktemp("cache"))


def _tickets():
    esperado = {r["ticket_id"]: r for r in csv.DictReader(open(config.RUTA_ESPERADO, encoding="utf-8"))}
    for i in range(1, 11):
        t = json.loads((config.RUTA_TICKETS / f"ticket_{i:02d}.json").read_text(encoding="utf-8"))
        yield t, esperado[str(i)]["runbook_esperado"]


def test_trocea_los_5_runbooks_en_sus_4_secciones(indice):
    fr = trocear(config.RUTA_RUNBOOKS)
    assert {f.runbook_id for f in fr} == {"RB-01", "RB-02", "RB-03", "RB-04", "RB-05"}
    assert len(fr) == 20 and {f.seccion for f in fr} == {"Síntomas", "Diagnóstico", "Solución", "Cuándo escalar"}


def test_el_runbook_correcto_sale_primero_para_cada_ticket(indice):
    aciertos, con_runbook = 0, 0
    for t, rb in _tickets():
        if not rb:
            continue
        con_runbook += 1
        top = indice.buscar(t["asunto"] + "\n" + t["cuerpo"])[0]
        aciertos += top.runbook_id == rb
    assert con_runbook == 9 and aciertos == 9  # el prompt pedía al menos 8 de 10; sale 9 de 9


def test_el_ticket_sin_runbook_no_supera_el_umbral_y_los_demas_si(indice):
    for t, rb in _tickets():
        h = indice.buscar(t["asunto"] + "\n" + t["cuerpo"])
        assert indice.hay_runbook(h) == bool(rb), (t["id"], h[0].puntuacion)


def test_busca_devuelve_k_resultados_ordenados_con_puntuacion_entre_0_y_1(indice):
    h = indice.buscar("me han cobrado dos veces", k=3)
    assert len(h) == 3 and [x.puntuacion for x in h] == sorted((x.puntuacion for x in h), reverse=True)
    assert all(0 <= x.puntuacion <= 1 for x in h) and h[0].runbook_id == "RB-01"


def test_consulta_vacia_o_sin_palabras_conocidas_no_rompe(indice):
    assert indice.hay_runbook(indice.buscar("")) is False
    assert indice.hay_runbook(indice.buscar("zzzz qqqq")) is False


def test_tokenizar_quita_tildes_stopwords_y_plurales():
    assert tokenizar("Cobros duplicados de la RESERVA") == tokenizar("cobro duplicado reservas") == ["cobro", "duplic", "reserv"]


def test_la_cache_se_reutiliza_y_se_reconstruye_si_esta_danada(tmp_path):
    a = Indice.construir(cache=tmp_path)
    archivo = next(tmp_path.glob("indice_tfidf_*.pkl"))
    assert Indice.construir(cache=tmp_path).buscar("reembolso")[0].runbook_id == "RB-05"
    archivo.write_bytes(b"roto")
    assert Indice.construir(cache=tmp_path).buscar("reembolso")[0].runbook_id == "RB-05"


def test_backend_desconocido_da_error():
    with pytest.raises(ValueError):
        Indice.construir(backend="otro")
