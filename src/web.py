"""Interfaz web (FastAPI, una sola página): elegir un ticket, ver clasificación, pasos y evidencia, editar y aprobar.

Arranque (desde la carpeta ticket-agente):
    python -m uvicorn src.web:app --port 8766
"""
import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import config
from .agente import ConfiguracionError, modo_activo, obtener_agente
from .aprobacion import AprobacionError, aplicar_decision, guardar_borrador
from .modelos import Borrador, Decision
from .tickets import cargar_ticket, cargar_todos

app = FastAPI(title="ticket-agente", description="El modelo propone, el código controla, la persona aprueba.")

_candado = threading.Lock()
_borradores: dict[int, Borrador] = {}  # en memoria; los borradores también se guardan en output/borradores/
_decisiones: dict[int, Decision] = {}
_agente = None  # se crea la primera vez que se necesita


class PeticionDecision(BaseModel):
    decision: str  # "aprobar" | "rechazar"
    texto_final: str = ""
    quien: str = ""


def _obtener_agente():
    global _agente
    if _agente is None:
        try:
            _agente = obtener_agente()
        except ConfiguracionError as e:
            raise HTTPException(status_code=503, detail=f"Configuración del agente: {e}")
        except RuntimeError as e:  # p. ej. EMBEDDINGS=st sin la librería instalada
            raise HTTPException(status_code=503, detail=str(e))
    return _agente


def _ticket(ticket_id: int):
    try:
        return cargar_ticket(ticket_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No existe el ticket {ticket_id}.")


@app.get("/api/estado")
def api_estado():
    try:
        modo = modo_activo()
    except ConfiguracionError as e:
        return {"modo": "error", "es_llm": False, "error": str(e)}
    return {"modo": modo, "es_llm": modo == "claude", "modelo": config.nombre_modelo() if modo == "claude" else None, "error": None}


@app.get("/api/tickets")
def api_tickets():
    with _candado:
        return [{"id": t.id, "asunto": t.asunto,
                 "estado": "decidido" if t.id in _decisiones else ("con borrador" if t.id in _borradores else "sin analizar")}
                for t in cargar_todos()]


def _detalle(ticket_id: int) -> dict:
    t = _ticket(ticket_id)
    return {"ticket": t.model_dump(), "borrador": _borradores[ticket_id].model_dump(mode="json") if ticket_id in _borradores else None,
            "decision": _decisiones[ticket_id].model_dump() if ticket_id in _decisiones else None}


@app.get("/api/tickets/{ticket_id}")
def api_ticket(ticket_id: int):
    with _candado:
        return _detalle(ticket_id)


@app.post("/api/tickets/{ticket_id}/triar")
def api_triar(ticket_id: int):
    """Analiza el ticket. Solo genera un borrador: no crea nada externo."""
    t = _ticket(ticket_id)
    agente = _obtener_agente()
    with _candado:
        if ticket_id in _decisiones:
            raise HTTPException(status_code=409, detail="Este ticket ya tiene una decisión registrada.")
        b = agente.triar(t)
        _borradores[ticket_id] = b
        try:
            guardar_borrador(b)
        except OSError:
            pass  # si no se puede escribir en disco, la web sigue funcionando
        return _detalle(ticket_id)


@app.post("/api/tickets/{ticket_id}/decision")
def api_decision(ticket_id: int, p: PeticionDecision):
    """La persona aprueba o rechaza. Solo aquí se puede crear el Jira simulado."""
    if p.decision not in ("aprobar", "rechazar"):
        raise HTTPException(status_code=400, detail="La decisión debe ser aprobar o rechazar.")
    with _candado:
        b = _borradores.get(ticket_id)
        if b is None:
            raise HTTPException(status_code=409, detail="Primero hay que analizar el ticket.")
        if ticket_id in _decisiones:
            raise HTTPException(status_code=409, detail="Este ticket ya tiene una decisión registrada.")
        try:
            d = aplicar_decision(b, aprobar=p.decision == "aprobar", texto_final=p.texto_final or b.texto, quien=p.quien)
        except AprobacionError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"No se pudo guardar la decisión: {e}")
        _decisiones[ticket_id] = d
        return _detalle(ticket_id)


@app.post("/api/reiniciar")
def api_reiniciar():
    """Olvida los borradores y decisiones de esta sesión (la auditoría y los Jira ya creados NO se borran)."""
    with _candado:
        _borradores.clear()
        _decisiones.clear()
    return {"ok": True}


@app.get("/api/auditoria")
def api_auditoria(limite: int = 15):
    ruta = config.RUTA_SALIDA / "auditoria.jsonl"
    if not ruta.exists():
        return []
    lineas = ruta.read_text(encoding="utf-8").splitlines()[-max(1, min(limite, 100)):]
    return [{k: a.get(k) for k in ("cuando", "ticket_id", "quien", "decision", "accion_propuesta", "accion_ejecutada", "sospechoso")}
            for a in map(json.loads, reversed(lineas))]


@app.get("/", response_class=HTMLResponse)
def pagina():
    return PAGINA


@app.get("/estilo/javbrain.css")
def hoja_de_estilos():
    return FileResponse(Path(__file__).parent / "estilo" / "javbrain.css", media_type="text/css")


# ------------------------------------------------------------------------------------
# La página. Todo lo que viene de los tickets o del modelo pasa por esc() antes de usar innerHTML.
# ------------------------------------------------------------------------------------
PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ticket-agente</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/estilo/javbrain.css">
<style>
  .cifra b.txt { font-size: 2rem; }
  .evid { margin: 0 0 10px; padding: 12px 14px; border: 1px solid var(--linea); border-radius: 12px; background: var(--tarjeta); }
  .evid pre { margin: 6px 0 0; padding: 8px 10px; white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--f-codigo); font-size: 0.82rem; background: #060d19; border-radius: 8px; }
  .evid h4 { margin: 0 0 4px; font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--tenue); }
  .peligro { color: var(--error); background: var(--error-f); border-left: 3px solid var(--error); padding: 10px 14px; border-radius: 6px; margin: 10px 0; }
  textarea#texto-final { min-height: 120px; font-family: var(--f-texto); }
</style>
</head>
<body>
<main>
  <p class="etiqueta">ticket-agente <span class="punto">&middot;</span><span class="punto">&middot;</span> Ejercicio 2 <span class="punto">&middot;</span><span class="punto">&middot;</span> Automatizaci&oacute;n con IA</p>
  <h1>Triaje de incidencias <span class="acento">con evidencia y aprobaci&oacute;n humana</span></h1>
  <p class="sub">El modelo <b>propone</b>, el c&oacute;digo <b>controla</b>, la persona <b>aprueba</b>. El agente solo lee: nada se escala sin tu OK. Demo con datos ficticios.</p>

  <section id="modo">Cargando modo del agente...</section>

  <section>
    <p class="etiqueta">01 <span class="punto">&middot;</span> Ticket</p>
    <h2>Elegir <span class="acento">un ticket</span></h2>
    <div class="fila">
      <select id="lista" aria-label="Ticket"></select>
      <button id="btn-triar">Analizar con el agente</button>
      <button id="btn-reiniciar" class="sec">Olvidar borradores de esta sesi&oacute;n</button>
    </div>
    <div id="ticket"></div>
    <div id="error-triar"></div>
  </section>

  <section id="sec-agente" hidden>
    <p class="etiqueta">02 <span class="punto">&middot;</span> Agente</p>
    <h2>Lo que <span class="acento">ha encontrado</span></h2>
    <div id="clasificacion"></div>
    <div id="sospechoso"></div>
    <h3>Pasos <small>(cada herramienta, con su entrada y su salida)</small></h3>
    <div id="pasos" class="tabla-scroll"></div>
    <h3>Evidencia <small>(la construye el c&oacute;digo con lo que de verdad se ejecut&oacute;)</small></h3>
    <div id="evidencia"></div>
  </section>

  <section id="sec-aprobacion" hidden>
    <p class="etiqueta">03 <span class="punto">&middot;</span> Control humano</p>
    <h2>Aprobar <span class="acento">o rechazar</span></h2>
    <div class="editor">
      <p id="accion-texto"></p>
      <label for="texto-final">Borrador (puedes editarlo antes de decidir)</label>
      <textarea id="texto-final"></textarea>
      <div class="fila">
        <label for="quien">Qui&eacute;n decide</label>
        <input id="quien" type="text" maxlength="80" placeholder="Tu nombre" autocomplete="off">
      </div>
      <div class="fila"><button id="btn-aprobar">Aprobar</button><button id="btn-rechazar" class="sec">Rechazar</button></div>
      <div id="error-decision"></div>
    </div>
    <div id="resultado-decision"></div>
  </section>

  <section>
    <p class="etiqueta">04 <span class="punto">&middot;</span> Auditor&iacute;a</p>
    <h2>Qu&eacute; se <span class="acento">ha decidido</span></h2>
    <div id="auditoria" class="tabla-scroll"><span class="vacio">Todav&iacute;a no hay decisiones.</span></div>
  </section>

  <p class="pie">Prototipo de ejercicio &middot; datos ficticios &middot; Daysi Delgado</p>
</main>

<script>
function esc(v) {
  return String(v === null || v === undefined ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
const $ = (id) => document.getElementById(id);

async function api(url, opciones) {
  let resp;
  try { resp = await fetch(url, opciones); } catch (e) { throw new Error("No se pudo conectar con el servidor."); }
  let datos = null;
  try { datos = await resp.json(); } catch (e) { /* sin JSON */ }
  if (!resp.ok) {
    let d = datos && datos.detail;
    if (Array.isArray(d)) d = d.map(x => x.msg).join("; ");
    throw new Error(d || ("Error " + resp.status));
  }
  return datos;
}
const post = (url, cuerpo) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });
function error(id, e) { $(id).innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>"; }

async function cargarModo() {
  try {
    const m = await api("/api/estado");
    let h = 'Modo del agente: <span class="badge ' + (m.modo === "claude" ? "claude" : (m.modo === "offline" ? "offline" : "error")) + '">' +
      (m.modo === "claude" ? "CLAUDE" : (m.modo === "offline" ? "OFFLINE-reglas" : "ERROR")) + "</span>";
    if (m.modelo) h += " <small>modelo " + esc(m.modelo) + "</small>";
    if (m.modo === "offline")
      h += '<div class="nota"><b>Atenci&oacute;n:</b> en este modo NO hay modelo de lenguaje. Son reglas por palabras clave y plantillas de consulta, ' +
           "sin red ni clave. Sirve para demostrar el flujo, la herramienta SQL de solo lectura y la aprobaci&oacute;n humana; no la comprensi&oacute;n de un LLM.</div>";
    if (m.error) h += '<div class="error-msg">' + esc(m.error) + "</div>";
    $("modo").innerHTML = h;
  } catch (e) { error("modo", e); }
}

async function cargarLista(seleccionar) {
  const lista = await api("/api/tickets");
  const actual = seleccionar || $("lista").value;
  $("lista").innerHTML = lista.map(t => '<option value="' + esc(t.id) + '">#' + esc(t.id) + " &middot; " + esc(t.asunto) + " (" + esc(t.estado) + ")</option>").join("");
  if (actual) $("lista").value = actual;
}

function cifra(titulo, valor) { return '<div class="cifra"><small>' + esc(titulo) + '</small><b class="txt">' + esc(valor) + "</b></div>"; }

function pintar(d) {
  const t = d.ticket, b = d.borrador;
  $("ticket").innerHTML = '<pre class="original"><b>' + esc(t.asunto) + "</b>\\n" + esc(t.cliente_email) + "\\n\\n" + esc(t.cuerpo) + "</pre>";
  $("sec-agente").hidden = !b; $("sec-aprobacion").hidden = !b;
  if (!b) return;
  $("clasificacion").innerHTML = '<div class="cifras">' + cifra("Prioridad", b.prioridad) + cifra("Área", b.area) +
    cifra("Acción propuesta", b.accion + (b.equipo ? " → " + b.equipo : "")) + cifra("Modo", b.modo) + "</div>" +
    (b.motivo_escalado ? "<p><small>Motivo: " + esc(b.motivo_escalado) + "</small></p>" : "");
  $("sospechoso").innerHTML = b.sospechoso ? '<div class="peligro"><b>Contenido sospechoso:</b> el ticket intenta dar &oacute;rdenes al agente. Se ha ignorado y se escala para revisi&oacute;n.</div>' : "";
  $("pasos").innerHTML = "<table><thead><tr><th>#</th><th>Herramienta</th><th>Entrada</th><th>Salida</th></tr></thead><tbody>" +
    b.pasos.map((p, i) => "<tr><td>" + (i + 1) + "</td><td>" + esc(p.herramienta) + "</td><td><small>" + esc((p.entrada.sql || p.entrada.consulta || "").slice(0, 160)) +
      "</small></td><td>" + (p.rechazado ? '<span class="estado fallida">rechazado</span> ' : "") + esc(p.resumen) + "</td></tr>").join("") + "</tbody></table>";
  $("evidencia").innerHTML = b.evidencia.map(e => {
    if (e.tipo === "sql") return '<div class="evid"><h4>Consulta SQL (solo lectura)</h4><pre>' + esc(e.consulta) + "</pre><small>Par&aacute;metros: " + esc(JSON.stringify(e.parametros)) +
      " &middot; " + esc(e.n_filas) + " fila(s)</small><pre>" + esc(JSON.stringify(e.filas.slice(0, 5), null, 1)) + "</pre></div>";
    if (e.tipo === "runbook") return '<div class="evid"><h4>Runbook citado</h4>' + (e.runbook_id ? "<b>" + esc(e.runbook_id) + "</b> &middot; " + esc(e.seccion) + " &middot; similitud " + esc(e.puntuacion) +
      "<pre>" + esc(e.fragmento) + "</pre>" : "Ninguno: " + esc(e.nota) + " (mejor similitud " + esc(e.puntuacion) + ")") + "</div>";
    return '<div class="evid"><h4>Sistema</h4>' + esc(e.nota) + "</div>";
  }).join("");
  const dec = d.decision;
  $("accion-texto").innerHTML = "Acci&oacute;n propuesta: <b>" + (b.accion === "escalar" ? "escalar a Jira (se crear&aacute; un ticket simulado si apruebas)" : "enviar esta respuesta al cliente (en este prototipo no se env&iacute;a nada)") + "</b>";
  $("texto-final").value = dec ? dec.texto_final : b.texto;
  for (const id of ["texto-final", "quien", "btn-aprobar", "btn-rechazar"]) $(id).disabled = !!dec;
  $("resultado-decision").innerHTML = dec ? '<div class="nota">Decisi&oacute;n registrada: <b>' + esc(dec.decision) + "</b> por " + esc(dec.quien) + " &middot; acci&oacute;n ejecutada: <b>" + esc(dec.accion_ejecutada) + "</b></div>" : "";
}

async function abrir(id) {
  limpiar();
  try { pintar(await api("/api/tickets/" + encodeURIComponent(id))); } catch (e) { error("error-triar", e); }
}
function limpiar() { $("error-triar").innerHTML = ""; $("error-decision").innerHTML = ""; }

$("lista").addEventListener("change", () => abrir($("lista").value));
$("btn-triar").addEventListener("click", async () => {
  const btn = $("btn-triar"); btn.disabled = true; limpiar();
  try { pintar(await post("/api/tickets/" + encodeURIComponent($("lista").value) + "/triar")); await cargarLista(); }
  catch (e) { error("error-triar", e); }
  btn.disabled = false;
});
async function decidir(decision) {
  limpiar();
  try {
    const d = await post("/api/tickets/" + encodeURIComponent($("lista").value) + "/decision",
      { decision, texto_final: $("texto-final").value, quien: $("quien").value });
    pintar(d); await Promise.all([cargarLista(), cargarAuditoria()]);
  } catch (e) { error("error-decision", e); }
}
$("btn-aprobar").addEventListener("click", () => decidir("aprobar"));
$("btn-rechazar").addEventListener("click", () => decidir("rechazar"));
$("btn-reiniciar").addEventListener("click", async () => { await post("/api/reiniciar"); await cargarLista(); await abrir($("lista").value); });

async function cargarAuditoria() {
  try {
    const f = await api("/api/auditoria");
    if (!f.length) { $("auditoria").innerHTML = '<span class="vacio">Todav&iacute;a no hay decisiones.</span>'; return; }
    $("auditoria").innerHTML = "<table><thead><tr><th>Cu&aacute;ndo</th><th>Ticket</th><th>Qui&eacute;n</th><th>Decisi&oacute;n</th><th>Propuesta</th><th>Ejecutado</th></tr></thead><tbody>" +
      f.map(a => "<tr><td>" + esc(a.cuando) + "</td><td>" + esc(a.ticket_id) + "</td><td>" + esc(a.quien) + "</td><td>" + esc(a.decision) + "</td><td>" + esc(a.accion_propuesta) +
        "</td><td>" + esc(a.accion_ejecutada) + (a.sospechoso ? ' <span class="estado fallida">sospechoso</span>' : "") + "</td></tr>").join("") + "</tbody></table>";
  } catch (e) { error("auditoria", e); }
}

(async () => { await cargarModo(); await cargarLista(); await cargarAuditoria(); if ($("lista").value) abrir($("lista").value); })();
</script>
</body>
</html>
"""
