"""La herramienta SQL solo lee. Cada intento de escribir o saltarse las reglas debe quedar rechazado."""
import sqlite3

import pytest

from src import config
from src.herramientas_sql import consultar_sql, validar, ConsultaRechazada


@pytest.fixture()
def bd(tmp_path):
    ruta = tmp_path / "t.db"
    con = sqlite3.connect(ruta)
    con.executescript("CREATE TABLE pagos (id INTEGER, estado TEXT); CREATE TABLE usuarios (id INTEGER, email TEXT);"
                      "CREATE TABLE secretos (id INTEGER, dato TEXT);")
    con.executemany("INSERT INTO pagos VALUES (?, 'cobrado')", [(i,) for i in range(80)])
    con.execute("INSERT INTO usuarios VALUES (1, 'a@example.com')")
    con.execute("INSERT INTO secretos VALUES (1, 'x')")
    con.commit()
    con.close()
    return ruta


def _cuenta(ruta, tabla="pagos"):
    con = sqlite3.connect(ruta)
    n = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    con.close()
    return n


@pytest.mark.parametrize("sql", [
    "DROP TABLE pagos",
    "DELETE FROM pagos",
    "UPDATE pagos SET estado = 'x'",
    "INSERT INTO pagos VALUES (999, 'x')",
    "PRAGMA query_only = OFF",
    "ATTACH DATABASE 'otra.db' AS o",
    "CREATE TABLE t (a)",
    "SELECT * FROM pagos; DROP TABLE pagos",
    "SELECT * FROM pagos; SELECT * FROM usuarios",
    "SELECT * FROM pagos -- y luego algo",
    "SELECT * FROM pagos /* comentario */",
    "SELECT * FROM secretos",
    "SELECT * FROM pagos JOIN secretos ON secretos.id = pagos.id",
    "SELECT * FROM (SELECT * FROM secretos)",
    "WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x",
    "SELECT load_extension('evil')",
    "   ",
    "",
])
def test_consultas_peligrosas_se_rechazan_y_no_tocan_nada(bd, sql):
    antes = _cuenta(bd)
    r = consultar_sql(sql, ruta_db=bd)
    assert r["ok"] is False and r["error"].startswith("consulta rechazada")
    assert _cuenta(bd) == antes == 80 and _cuenta(bd, "secretos") == 1


def test_select_valido_devuelve_filas_como_diccionarios(bd):
    r = consultar_sql("SELECT id, email FROM usuarios WHERE id = :id;", {"id": 1}, ruta_db=bd)
    assert r == {"ok": True, "consulta": "SELECT id, email FROM usuarios WHERE id = :id", "filas": [{"id": 1, "email": "a@example.com"}],
                 "n_filas": 1, "truncado": False}


def test_maximo_50_filas_y_avisa_de_que_hay_mas(bd):
    r = consultar_sql("SELECT id FROM pagos", ruta_db=bd)
    assert r["ok"] and r["n_filas"] == config.MAX_FILAS == 50 and r["truncado"] is True


def test_una_palabra_prohibida_dentro_de_un_texto_entre_comillas_no_bloquea(bd):
    r = consultar_sql("SELECT id FROM pagos WHERE estado = 'delete from drop'", ruta_db=bd)
    assert r["ok"] is True and r["n_filas"] == 0


def test_la_capa_de_conexion_protege_aunque_fallara_la_validacion(bd):
    """Defensa en profundidad: aunque se saltara validar(), la conexión de solo lectura no deja escribir."""
    from src.herramientas_sql import _conectar_solo_lectura
    con = _conectar_solo_lectura(bd)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM pagos")
    con.close()
    assert _cuenta(bd) == 80


def test_base_inexistente_da_error_claro_sin_crearla(tmp_path):
    r = consultar_sql("SELECT * FROM pagos", ruta_db=tmp_path / "no_existe.db")
    assert r["ok"] is False and "base de datos" in r["error"] and not (tmp_path / "no_existe.db").exists()


def test_validar_lanza_con_el_motivo():
    with pytest.raises(ConsultaRechazada, match="SELECT"):
        validar("DELETE FROM pagos")


def test_tiempo_maximo(bd, monkeypatch):
    monkeypatch.setattr(config, "TIEMPO_MAX_SQL", 0.05)
    # Producto cartesiano enorme: sin límite de tiempo tardaría mucho
    r = consultar_sql("SELECT COUNT(*) FROM pagos a, pagos b, pagos c, pagos d, pagos e, pagos f", ruta_db=bd)
    assert r["ok"] is False and "interrupted" in r["error"].lower()
