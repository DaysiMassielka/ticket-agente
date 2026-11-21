"""Búsqueda en los runbooks (RAG sencillo): trocear por secciones, vectorizar y buscar por similitud del coseno.

Dos formas de vectorizar:
  - "tfidf" (por defecto): TF-IDF escrito a mano, sin dependencias ni descargas. Compara PALABRAS, no
    significados: "no me deja entrar" y "acceso denegado" solo se parecen si comparten palabras.
  - "st": embeddings semánticos con sentence-transformers (opcional: pip install sentence-transformers y
    EMBEDDINGS=st). Está escrito pero NO se ha probado en este proyecto.
Cada fragmento conserva el id del runbook y el título de la sección para poder CITARLO como evidencia.
"""
import hashlib
import math
import os
import pickle
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config

STOP = set("""a al algo ante con como cual cuando de del desde donde el ella ellos en entre era es esta estan este esto estoy
fue ha han hasta hay la las le les lo los me mi mis muy no nos o para pero por que se si sin sobre su sus te tengo todo tu tus
un una uno unos y ya hola gracias buenas buenos saludo saludos favor puedo puede pueden quiero""".split())


@dataclass
class Fragmento:
    runbook_id: str
    titulo: str
    seccion: str
    texto: str


@dataclass
class Hallazgo:
    runbook_id: str
    titulo: str
    seccion: str
    fragmento: str
    puntuacion: float


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sin tildes, sin palabras vacías y con un recorte simple de plurales y terminaciones."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    out = []
    for w in re.findall(r"[a-z0-9]+", t):
        if w in STOP or len(w) < 2:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]  # plural
        out.append(w[:6])  # raíz aproximada: cobrado/cobro/cobraron comparten "cobr"
    return out


def trocear(ruta_runbooks: Path) -> list[Fragmento]:
    """Un fragmento por sección (## ...) de cada runbook (.md)."""
    fragmentos = []
    for archivo in sorted(Path(ruta_runbooks).glob("*.md")):
        md = archivo.read_text(encoding="utf-8")
        cab = re.match(r"#\s+(RB-\d+)\s*·\s*(.+)", md)
        if not cab:
            continue
        rid, titulo = cab.group(1), cab.group(2).strip()
        for bloque in re.split(r"^##\s+", md, flags=re.MULTILINE)[1:]:
            seccion, _, cuerpo = bloque.partition("\n")
            fragmentos.append(Fragmento(rid, titulo, seccion.strip(), cuerpo.strip()))
    return fragmentos


def _coseno(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


class IndiceTfidf:
    nombre = "tfidf"

    def __init__(self, fragmentos: list[Fragmento]):
        self.fragmentos = fragmentos
        docs = [tokenizar(f"{f.titulo} {f.titulo} {f.seccion} {f.texto}") for f in fragmentos]  # el título pesa doble
        n = len(docs)
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vectores = [self._vector(d) for d in docs]

    def _vector(self, tokens: list[str]) -> dict:
        tf = Counter(tokens)
        v = {t: (1 + math.log(c)) * self.idf[t] for t, c in tf.items() if t in self.idf}  # lo desconocido no cuenta
        norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norma for t, x in v.items()}

    def puntuaciones(self, consulta: str) -> list[float]:
        q = self._vector(tokenizar(consulta))
        return [_coseno(q, v) for v in self.vectores]


class IndiceSt:
    """Embeddings semánticos (opcional, SIN PROBAR aquí). Requiere sentence-transformers y descarga un modelo."""
    nombre = "st"
    MODELO = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, fragmentos: list[Fragmento]):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("EMBEDDINGS=st necesita: pip install sentence-transformers") from e
        self.fragmentos = fragmentos
        self.modelo = SentenceTransformer(self.MODELO)
        self.matriz = self.modelo.encode([f"{f.titulo}. {f.seccion}. {f.texto}" for f in fragmentos], normalize_embeddings=True)

    def puntuaciones(self, consulta: str) -> list[float]:
        q = self.modelo.encode([consulta], normalize_embeddings=True)[0]
        return [float(x) for x in self.matriz @ q]


class Indice:
    def __init__(self, motor):
        self.motor = motor
        self.fragmentos = motor.fragmentos

    @classmethod
    def construir(cls, ruta_runbooks: Optional[Path] = None, backend: Optional[str] = None, cache: Optional[Path] = None) -> "Indice":
        ruta = Path(ruta_runbooks) if ruta_runbooks is not None else config.RUTA_RUNBOOKS
        backend = backend or os.environ.get("EMBEDDINGS") or "tfidf"
        fragmentos = trocear(ruta)
        if not fragmentos:
            raise RuntimeError(f"No hay runbooks válidos en {ruta}")
        if backend == "st":
            return cls(IndiceSt(fragmentos))  # sin caché: el modelo ya guarda la suya
        if backend != "tfidf":
            raise ValueError(f"EMBEDDINGS desconocido: {backend}")
        # Caché local: se reconstruye sola si cambia el contenido de algún runbook
        huella = hashlib.sha256("".join(f"{f.runbook_id}{f.seccion}{f.texto}" for f in fragmentos).encode("utf-8")).hexdigest()[:16]
        carpeta = Path(cache) if cache is not None else config.RUTA_CACHE
        archivo = carpeta / f"indice_tfidf_{huella}.pkl"
        try:
            if archivo.exists():
                return cls(pickle.loads(archivo.read_bytes()))
        except Exception:
            pass  # caché dañada: se reconstruye
        motor = IndiceTfidf(fragmentos)
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            archivo.write_bytes(pickle.dumps(motor))
        except OSError:
            pass  # sin caché también funciona
        return cls(motor)

    @property
    def nombre(self) -> str:
        return self.motor.nombre

    def buscar(self, consulta: str, k: int = 3) -> list[Hallazgo]:
        """Los k fragmentos más parecidos, de mayor a menor puntuación (0 a 1)."""
        pts = self.motor.puntuaciones(consulta)
        orden = sorted(range(len(pts)), key=lambda i: pts[i], reverse=True)[:k]
        return [Hallazgo(f.runbook_id, f.titulo, f.seccion, f.texto, round(pts[i], 3))
                for i in orden for f in [self.fragmentos[i]]]

    def hay_runbook(self, hallazgos: list[Hallazgo]) -> bool:
        """¿El mejor fragmento llega al umbral? Si no, ningún runbook describe este caso."""
        return bool(hallazgos) and hallazgos[0].puntuacion >= config.UMBRAL_SIMILITUD
