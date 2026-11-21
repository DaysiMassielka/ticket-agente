"""Modelos de datos (Pydantic). El modelo de lenguaje solo rellena una parte; la EVIDENCIA la añade el código."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Prioridad = Literal["P1", "P2", "P3", "P4"]
Area = Literal["SQL", "API", "negocio"]
Accion = Literal["responder", "escalar"]


class Ticket(BaseModel):
    id: int
    asunto: str
    cuerpo: str
    cliente_email: str = ""
    creado: str = ""

    @property
    def texto(self) -> str:
        return f"{self.asunto}\n{self.cuerpo}"


class Evidencia(BaseModel):
    """Una prueba de lo que el agente dice. La construye el código a partir de las herramientas que SÍ se ejecutaron."""

    tipo: Literal["sql", "runbook", "sistema"]
    # sql
    consulta: Optional[str] = None
    parametros: dict = Field(default_factory=dict)
    filas: list[dict] = Field(default_factory=list)
    n_filas: int = 0
    # runbook
    runbook_id: Optional[str] = None  # None = ningún runbook supera el umbral
    seccion: Optional[str] = None
    fragmento: Optional[str] = None
    puntuacion: Optional[float] = None
    nota: str = ""


class Paso(BaseModel):
    """Una llamada a una herramienta, con su entrada y un resumen de la salida (la traza del agente)."""

    herramienta: str
    entrada: dict
    resumen: str
    rechazado: bool = False


class EntregaModelo(BaseModel):
    """Lo que el LLM entrega con la herramienta entregar_borrador (todo se valida antes de usarlo)."""

    prioridad: Prioridad
    area: Area
    accion: Accion
    texto: str = Field(min_length=10, max_length=4000)
    motivo_escalado: str = Field(default="", max_length=500)
    sospechoso: bool = False

    @field_validator("texto")
    @classmethod
    def _sin_espacios(cls, v):
        if not v.strip():
            raise ValueError("el texto está vacío")
        return v.strip()


class Borrador(BaseModel):
    ticket_id: int
    prioridad: Prioridad
    area: Area
    accion: Accion
    texto: str
    motivo_escalado: str = ""
    sospechoso: bool = False
    equipo: str = ""  # a quién se escalaría
    evidencia: list[Evidencia]
    pasos: list[Paso] = Field(default_factory=list)
    modo: str = ""
    jira: Optional[dict] = None  # borrador del ticket de Jira (solo si la acción es escalar)

    @model_validator(mode="after")
    def _exige_evidencia(self):
        # Regla del ejercicio: un borrador sin evidencia no se acepta
        if not self.evidencia:
            raise ValueError("un borrador sin evidencia no es válido")
        return self


class Decision(BaseModel):
    """Lo que decidió la persona. Queda en la auditoría."""

    ticket_id: int
    decision: Literal["aprobar", "rechazar"]
    quien: str
    cuando: str
    texto_final: str
    accion_propuesta: Accion
    accion_ejecutada: Literal["jira_creado", "respuesta_aprobada", "ninguna"]
