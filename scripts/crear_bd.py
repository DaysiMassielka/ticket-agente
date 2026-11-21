"""Crea (de cero) la base de prueba data/reservas.db. Todos los datos son ficticios.

Uso:  python scripts/crear_bd.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import RUTA_DB  # noqa: E402

ESQUEMA = """
CREATE TABLE usuarios (id INTEGER PRIMARY KEY, email TEXT NOT NULL, estado TEXT NOT NULL, rol TEXT, ultimo_acceso TEXT);
CREATE TABLE reservas (id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id), fecha TEXT NOT NULL,
                       estado TEXT NOT NULL, importe REAL NOT NULL);
CREATE TABLE pagos (id INTEGER PRIMARY KEY, reserva_id INTEGER NOT NULL REFERENCES reservas(id), importe REAL NOT NULL,
                    estado TEXT NOT NULL, referencia TEXT NOT NULL, creado_en TEXT NOT NULL);
CREATE TABLE logs_api (id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL, codigo INTEGER NOT NULL, mensaje TEXT, creado_en TEXT NOT NULL);
"""

USUARIOS = [
    (1, "ana.lopez@example.com", "activo", "cliente", "2026-11-18 09:12:00"),
    (2, "carlos.ruiz@example.com", "bloqueado_intentos", "cliente", "2026-11-19 22:41:00"),  # ticket 3
    (3, "marta.gil@example.com", "activo", None, None),  # ticket 4: sin rol
    (4, "luis.perez@example.com", "activo", None, None),  # ticket 10: sin rol
    (5, "sofia.ramos@example.com", "activo", "cliente", "2026-11-15 10:00:00"),
    (6, "pedro.nieto@example.com", "activo", "cliente", "2026-11-16 18:28:00"),
    (7, "lucia.mora@example.com", "activo", "cliente", "2026-11-17 09:10:00"),
    (8, "jorge.sanz@example.com", "activo", "cliente", "2026-11-19 19:58:00"),
    (9, "irene.vidal@example.com", "activo", "cliente", "2026-11-20 10:10:00"),
    (10, "raul.cano@example.com", "activo", "cliente", "2026-11-12 16:00:00"),
]

RESERVAS = [
    (1001, 5, "2026-11-15", "confirmada", 120.00),
    (1002, 6, "2026-11-16", "confirmada", 80.00),
    (1003, 7, "2026-11-17", "pendiente", 200.00),
    (1004, 8, "2026-11-19", "pendiente", 150.00),
    (1005, 9, "2026-11-20", "pendiente", 175.00),
    (1006, 10, "2026-11-12", "cancelada", 90.00),
    (1007, 1, "2026-11-10", "confirmada", 60.00),
    (1008, 1, "2026-11-18", "confirmada", 95.00),
]

PAGOS = [
    (1, 1001, 120.00, "cobrado", "REF-S1001", "2026-11-15 10:02:11"),  # ticket 1: dos cobros con la misma referencia
    (2, 1001, 120.00, "cobrado", "REF-S1001", "2026-11-15 10:02:43"),
    (3, 1002, 80.00, "cobrado", "REF-P1002", "2026-11-16 18:30:05"),  # ticket 2: uno cobrado y otro solo retenido
    (4, 1002, 80.00, "retenido", "REF-P1002-RET", "2026-11-16 18:30:40"),
    (5, 1003, 200.00, "cobrado", "REF-L1003", "2026-11-17 09:15:20"),  # ticket 5: cobrado y reserva pendiente
    (6, 1004, 150.00, "pendiente", "REF-J1004", "2026-11-19 20:01:00"),  # ticket 6: pago aún pendiente
    (7, 1005, 175.00, "fallido", "REF-I1005-1", "2026-11-20 10:12:03"),  # ticket 7: intentos fallidos
    (8, 1005, 175.00, "fallido", "REF-I1005-2", "2026-11-20 10:14:40"),
    (9, 1005, 175.00, "fallido", "REF-I1005-3", "2026-11-20 10:19:55"),
    (10, 1006, 90.00, "reembolso_en_proceso", "REF-R1006", "2026-11-18 12:00:00"),  # ticket 8: pedido hace 3 días
    (11, 1007, 60.00, "cobrado", "REF-A1007", "2026-11-10 08:30:00"),
    (12, 1008, 95.00, "cobrado", "REF-A1008", "2026-11-18 09:15:00"),
]

# Pico de errores 502 en el cobro entre las 10:05 y las 10:25 del 20/11 (ticket 7)
LOGS = [("/api/pagos/cobrar", 200, "ok", f"2026-11-20 09:{m:02d}:10") for m in (48, 52, 57)]
LOGS += [("/api/pagos/cobrar", 502, "Bad Gateway: pasarela de pago sin respuesta", f"2026-11-20 10:{m:02d}:30")
         for m in (5, 7, 9, 12, 14, 16, 19, 22, 25)]
LOGS += [("/api/pagos/cobrar", 200, "ok", "2026-11-20 11:02:10"), ("/api/pagos/cobrar", 200, "ok", "2026-11-20 11:40:55"),
         ("/api/reservas", 200, "ok", "2026-11-20 10:10:00"), ("/api/reservas", 500, "error aislado al listar", "2026-11-19 08:00:00")]


def main() -> None:
    RUTA_DB.parent.mkdir(parents=True, exist_ok=True)
    if RUTA_DB.exists():
        RUTA_DB.unlink()
    con = sqlite3.connect(RUTA_DB)
    con.executescript(ESQUEMA)
    con.executemany("INSERT INTO usuarios VALUES (?,?,?,?,?)", USUARIOS)
    con.executemany("INSERT INTO reservas VALUES (?,?,?,?,?)", RESERVAS)
    con.executemany("INSERT INTO pagos VALUES (?,?,?,?,?,?)", PAGOS)
    con.executemany("INSERT INTO logs_api (endpoint, codigo, mensaje, creado_en) VALUES (?,?,?,?)", LOGS)
    con.commit()
    con.close()
    print(f"Base creada en {RUTA_DB} ({len(USUARIOS)} usuarios, {len(RESERVAS)} reservas, {len(PAGOS)} pagos, {len(LOGS)} logs)")


if __name__ == "__main__":
    main()
