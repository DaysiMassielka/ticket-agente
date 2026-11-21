"""Configuración común de los tests: nunca se llama a la API real ni se escribe en output/ ni en data/."""
import runpy
from pathlib import Path

import pytest

from src import config


@pytest.fixture(scope="session", autouse=True)
def base_de_prueba():
    # La base es un archivo generado (no se sube a git): se recrea de cero antes de los tests
    runpy.run_path(str(Path(config.RAIZ) / "scripts" / "crear_bd.py"), run_name="__main__")


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENTE", raising=False)
    monkeypatch.delenv("EMBEDDINGS", raising=False)
    monkeypatch.setattr(config, "RUTA_SALIDA", tmp_path / "output")  # auditoría y Jira simulado, a una carpeta temporal
    monkeypatch.setattr(config, "RUTA_CACHE", tmp_path / "cache")
