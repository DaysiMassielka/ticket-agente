"""Versión para CLIENTE de la web: solo lo que guía a un operador. Sin SQL, sin procedimientos internos, sin puntuaciones.

Usa el mismo agente y la misma puerta de aprobación que la versión técnica (src/web.py), que sigue intacta.

Arranque (desde la carpeta ticket-agente):
    python -m uvicorn src.web_cliente:app --port 8767
"""
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import config
from .agente import ConfiguracionError, obtener_agente
from .aprobacion import AprobacionError, aplicar_decision, guardar_borrador
from .modelos import Borrador, Decision
from .presentacion import a_vista, resultado_decision
from .tickets import cargar_ticket, cargar_todos

app = FastAPI(title="Bandeja de incidencias")

_candado = threading.Lock()
_borradores: dict[int, Borrador] = {}
_decisiones: dict[int, Decision] = {}
_agente = None

NO_DISPONIBLE = "El asistente no está disponible en este momento. Inténtalo de nuevo en unos minutos."


class PeticionDecision(BaseModel):
    aprobar: bool
    texto: str = ""
    quien: str = ""


def _asistente():
    global _agente
    if _agente is None:
        try:
            _agente = obtener_agente()
        except (ConfiguracionError, RuntimeError):
            raise HTTPException(status_code=503, detail=NO_DISPONIBLE)
    return _agente


def _ticket(ticket_id: int):
    try:
        return cargar_ticket(ticket_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No existe ese caso.")


def _estado(ticket_id: int) -> str:
    d = _decisiones.get(ticket_id)
    if d:
        return "Aprobado" if d.decision == "aprobar" else "No aprobado"
    return "Revisado" if ticket_id in _borradores else "Por revisar"


def _decision_vista(ticket_id: int):
    d, b = _decisiones.get(ticket_id), _borradores.get(ticket_id)
    if not d or not b:
        return None
    return {"mensaje": resultado_decision(d.accion_ejecutada, d.decision, b.equipo), "quien": d.quien, "cuando": d.cuando.replace("T", " ")[:16],
            "texto": d.texto_final, "aprobado": d.decision == "aprobar"}


def _detalle(ticket_id: int) -> dict:
    t = _ticket(ticket_id)
    b = _borradores.get(ticket_id)
    return {"caso": {"id": t.id, "asunto": t.asunto, "cliente": t.cliente_email, "mensaje": t.cuerpo, "estado": _estado(t.id)},
            "revision": a_vista(b) if b else None, "decision": _decision_vista(ticket_id)}


@app.get("/api/bandeja")
def api_bandeja():
    with _candado:
        return [{"id": t.id, "asunto": t.asunto, "cliente": t.cliente_email, "estado": _estado(t.id)} for t in cargar_todos()]


@app.get("/api/casos/{ticket_id}")
def api_caso(ticket_id: int):
    with _candado:
        return _detalle(ticket_id)


@app.post("/api/casos/{ticket_id}/revisar")
def api_revisar(ticket_id: int):
    t = _ticket(ticket_id)
    asistente = _asistente()
    with _candado:
        if ticket_id in _decisiones:
            raise HTTPException(status_code=409, detail="Este caso ya está resuelto.")
        b = asistente.triar(t)
        _borradores[ticket_id] = b
        try:
            guardar_borrador(b)
        except OSError:
            pass
        return _detalle(ticket_id)


@app.post("/api/casos/{ticket_id}/decision")
def api_decision(ticket_id: int, p: PeticionDecision):
    with _candado:
        b = _borradores.get(ticket_id)
        if b is None:
            raise HTTPException(status_code=409, detail="Primero hay que revisar el caso.")
        if ticket_id in _decisiones:
            raise HTTPException(status_code=409, detail="Este caso ya está resuelto.")
        try:
            d = aplicar_decision(b, aprobar=p.aprobar, texto_final=p.texto or b.texto, quien=p.quien)
        except AprobacionError as e:
            msg = str(e)
            raise HTTPException(status_code=422, detail="Escribe tu nombre para poder aprobar." if "quién" in msg
                                else "El texto no puede estar vacío." if "vacío" in msg else "Este caso ya se había pasado al equipo.")
        except OSError:
            raise HTTPException(status_code=500, detail="No se pudo guardar la decisión. Inténtalo de nuevo.")
        _decisiones[ticket_id] = d
        return _detalle(ticket_id)


@app.post("/api/reiniciar")
def api_reiniciar():
    with _candado:
        _borradores.clear()
        _decisiones.clear()
    return {"ok": True}


@app.get("/api/historial")
def api_historial(limite: int = 10):
    ruta = config.RUTA_SALIDA / "auditoria.jsonl"
    if not ruta.exists():
        return []
    lineas = ruta.read_text(encoding="utf-8").splitlines()[-max(1, min(limite, 50)):]
    out = []
    for a in map(json.loads, reversed(lineas)):
        accion = {"jira_creado": "Pasado al equipo", "respuesta_aprobada": "Respuesta aprobada", "ninguna": "No aprobado"}[a["accion_ejecutada"]]
        out.append({"cuando": a["cuando"].replace("T", " ")[:16], "caso": a["ticket_id"], "quien": a["quien"], "resultado": accion})
    return out


@app.get("/", response_class=HTMLResponse)
def pagina():
    return PAGINA


@app.get("/estilo/javbrain.css")
def hoja_de_estilos():
    return FileResponse(Path(__file__).parent / "estilo" / "javbrain.css", media_type="text/css")


PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bandeja de incidencias</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/estilo/javbrain.css">
<style>
  main { max-width: 1180px; }
  .disposicion { display: grid; grid-template-columns: minmax(250px, 340px) minmax(0, 1fr); gap: 18px; align-items: start; }
  @media (max-width: 860px) { .disposicion { grid-template-columns: 1fr; } }
  .disposicion > section { margin-top: 0; }
  .caso { display: block; width: 100%; text-align: left; margin: 0 0 8px; padding: 12px 14px; border-radius: 12px; background: var(--tarjeta);
          color: var(--tinta); border: 1px solid var(--linea); font-weight: 600; }
  .caso:hover { background: var(--tarjeta-fuerte); box-shadow: none; }
  .caso.activo { border-color: var(--acento); background: var(--acento-suave); }
  .caso small { display: block; margin-top: 3px; font-weight: 400; }
  .caso .estado { float: right; margin-left: 8px; }
  .mensaje { margin: 0 0 14px; padding: 14px 16px; border: 1px solid var(--linea); border-radius: 12px; background: var(--tarjeta); white-space: pre-wrap; }
  .aviso { color: var(--aviso); background: var(--aviso-f); border-left: 3px solid var(--aviso); padding: 10px 14px; border-radius: 6px; margin: 12px 0; }
  .grande { font-size: 1.05rem; }
  h3 { margin: 18px 0 8px; font-size: 0.78rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--tenue); }
  textarea { min-height: 130px; font-family: var(--f-texto); font-size: 0.98rem; }
  .estado.p-critica { background: var(--error-f); color: var(--error); }
  .estado.p-alta { background: var(--aviso-f); color: var(--aviso); }
  .estado.p-media { background: var(--info-f); color: var(--info); }
  .estado.p-baja { background: var(--ok-f); color: var(--ok); }
  .estado.s-aprobado { background: var(--ok-f); color: var(--ok); }
  .estado.s-no-aprobado { background: var(--error-f); color: var(--error); }
  .estado.s-revisado { background: var(--info-f); color: var(--info); }
  .estado.s-por-revisar { background: var(--aviso-f); color: var(--aviso); }
  .vacio-central { text-align: center; padding: 50px 10px; }
</style>
</head>
<body>
<main>
  <p class="etiqueta">Atenci&oacute;n al cliente <span class="punto">&middot;</span><span class="punto">&middot;</span> Bandeja de incidencias</p>
  <h1>Resuelve cada caso <span class="acento">con todo a la vista</span></h1>
  <p class="sub">El asistente prepara el an&aacute;lisis y una propuesta. <b>T&uacute; revisas, ajustas y decides</b>: nada se env&iacute;a ni se pasa a otro equipo sin tu aprobaci&oacute;n.</p>

  <div class="disposicion">
    <section>
      <p class="etiqueta">Casos</p>
      <div id="bandeja"></div>
      <button id="btn-reiniciar" class="sec">Empezar de nuevo la demo</button>
    </section>

    <section id="detalle"><div class="vacio-central vacio">Elige un caso de la bandeja para empezar.</div></section>
  </div>

  <section>
    <p class="etiqueta">Historial</p>
    <h2>Decisiones <span class="acento">recientes</span></h2>
    <div id="historial" class="tabla-scroll"><span class="vacio">Todav&iacute;a no hay decisiones.</span></div>
  </section>

  <p class="pie">Demostraci&oacute;n &middot; datos ficticios</p>
</main>

<script>
function esc(v) {
  return String(v === null || v === undefined ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
const $ = (id) => document.getElementById(id);
let actual = null;

async function api(url, opciones) {
  let resp;
  try { resp = await fetch(url, opciones); } catch (e) { throw new Error("No hay conexión con el servidor."); }
  let datos = null;
  try { datos = await resp.json(); } catch (e) { /* sin JSON */ }
  if (!resp.ok) {
    let d = datos && datos.detail;
    if (Array.isArray(d)) d = "Revisa los datos escritos.";
    throw new Error(d || "Algo ha fallado. Inténtalo de nuevo.");
  }
  return datos;
}
const post = (url, cuerpo) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });
const clase = (txt) => String(txt).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ /g, "-");

async function cargarBandeja() {
  const lista = await api("/api/bandeja");
  $("bandeja").innerHTML = lista.map(c =>
    '<button class="caso' + (c.id === actual ? " activo" : "") + '" data-id="' + esc(c.id) + '"><span class="estado s-' + clase(c.estado) + '">' + esc(c.estado) + "</span>" +
    esc(c.asunto) + "<small>" + esc(c.cliente) + "</small></button>").join("");
}

function cifra(titulo, valor, extra) {
  return '<div class="cifra"><small>' + esc(titulo) + '</small><b style="font-size:1.9rem">' + esc(valor) + "</b>" + (extra ? "<small>" + esc(extra) + "</small>" : "") + "</div>";
}

function tabla(t) {
  if (!t) return "";
  if (t.vacia) return "<h3>" + esc(t.titulo) + '</h3><p class="vacio">No se ha encontrado ningún dato.</p>';
  return "<h3>" + esc(t.titulo) + '</h3><div class="tabla-scroll"><table><thead><tr>' + t.columnas.map(c => "<th>" + esc(c) + "</th>").join("") + "</tr></thead><tbody>" +
    t.filas.map(f => "<tr>" + f.map(x => "<td>" + esc(x) + "</td>").join("") + "</tr>").join("") + "</tbody></table></div>";
}

function pintar(d) {
  const c = d.caso, r = d.revision, dec = d.decision;
  let h = '<p class="etiqueta">Caso ' + esc(c.id) + ' <span class="punto">&middot;</span> <span class="estado s-' + clase(c.estado) + '">' + esc(c.estado) + "</span></p>" +
    "<h2>" + esc(c.asunto) + "</h2>" + '<p><small>' + esc(c.cliente) + '</small></p><div class="mensaje">' + esc(c.mensaje) + "</div>";
  if (!r) {
    h += '<div class="fila"><button id="btn-revisar">Revisar con el asistente</button></div><div id="error"></div>';
    $("detalle").innerHTML = h; return;
  }
  if (r.sospechoso) h += '<div class="aviso"><b>Atención:</b> este mensaje contiene instrucciones extrañas dirigidas al sistema. Se han ignorado y el caso pasa a Seguridad para su revisión.</div>';
  h += '<div class="cifras">' + cifra("Prioridad", r.prioridad, r.prioridad_explicacion) + cifra("Tipo de caso", r.tipo) + cifra("Siguiente paso", r.siguiente_paso) + "</div>";
  h += '<h3>Qué recomienda el asistente</h3><p class="grande"><b>' + esc(r.titular) + "</b></p>" + (r.motivo ? "<p>" + esc(r.motivo) + "</p>" : "") + "<p><small>" + esc(r.procedimiento) + "</small></p>";
  h += tabla(r.tabla);
  if (dec) {
    h += '<h3>Decisión</h3><div class="' + (dec.aprobado ? "nota" : "aviso") + '"><b>' + esc(dec.mensaje) + "</b><br><small>" + esc(dec.quien) + " · " + esc(dec.cuando) + '</small></div><div class="mensaje">' + esc(dec.texto) + "</div>";
  } else {
    h += '<h3>' + esc(r.etiqueta_texto) + '</h3><textarea id="texto">' + esc(r.texto) + '</textarea>' +
      '<div class="fila"><label for="quien">Tu nombre</label><input id="quien" type="text" maxlength="80" placeholder="Quién aprueba" autocomplete="off"></div>' +
      '<div class="fila"><button id="btn-aprobar">' + esc(r.boton_aprobar) + '</button><button id="btn-rechazar" class="sec">No aprobar</button></div>' +
      '<p><small>' + (r.se_crea_algo ? "Al aprobar, el caso se pasa al equipo con este resumen." : "Al aprobar, la respuesta queda lista para enviarse.") + " Si no apruebas, no se hace nada.</small></p><div id=\\"error\\"></div>";
  }
  $("detalle").innerHTML = h;
}

async function abrir(id) {
  actual = id;
  try { pintar(await api("/api/casos/" + encodeURIComponent(id))); await cargarBandeja(); }
  catch (e) { $("detalle").innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>"; }
}
function fallo(e) { const x = $("error"); if (x) x.innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>"; }

async function cargarHistorial() {
  const f = await api("/api/historial");
  $("historial").innerHTML = f.length ? "<table><thead><tr><th>Cuándo</th><th>Caso</th><th>Quién</th><th>Resultado</th></tr></thead><tbody>" +
    f.map(a => "<tr><td>" + esc(a.cuando) + "</td><td>" + esc(a.caso) + "</td><td>" + esc(a.quien) + "</td><td>" + esc(a.resultado) + "</td></tr>").join("") + "</tbody></table>"
    : '<span class="vacio">Todavía no hay decisiones.</span>';
}

$("bandeja").addEventListener("click", (ev) => { const b = ev.target.closest("[data-id]"); if (b) abrir(Number(b.dataset.id)); });
$("detalle").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  b.disabled = true;
  try {
    if (b.id === "btn-revisar") { pintar(await post("/api/casos/" + actual + "/revisar")); await cargarBandeja(); }
    else if (b.id === "btn-aprobar" || b.id === "btn-rechazar") {
      pintar(await post("/api/casos/" + actual + "/decision", { aprobar: b.id === "btn-aprobar", texto: $("texto").value, quien: $("quien").value }));
      await Promise.all([cargarBandeja(), cargarHistorial()]);
    }
  } catch (e) { b.disabled = false; fallo(e); }
});
$("btn-reiniciar").addEventListener("click", async () => { await post("/api/reiniciar"); actual = null; $("detalle").innerHTML = '<div class="vacio-central vacio">Elige un caso de la bandeja para empezar.</div>'; await cargarBandeja(); });

(async () => { try { await Promise.all([cargarBandeja(), cargarHistorial()]); } catch (e) { $("bandeja").innerHTML = '<div class="error-msg">' + esc(e.message) + "</div>"; } })();
</script>
</body>
</html>
"""
