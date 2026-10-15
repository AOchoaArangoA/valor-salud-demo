"""Tablero gerencial de Valor en Salud (retina) — 5 niveles de gestión.

Sigue la "Propuesta tablero por niveles de gestión" (17-09-2026) y la figura "De los datos a la
gestión del valor": 1 Visión ejecutiva · 2 Cohortes · 3 Gestión de la atención · 4 paciente-ojo reingreso · 5 Valor.

Ejecutar:  streamlit run dashboard/app.py      (antes: python -m pipeline.main)
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib  # noqa: E402

import logic as L  # noqa: E402
from pipeline import config, ingest, seguridad  # noqa: E402  (la ruta del proyecto la agrega logic)

# Streamlit conserva los módulos importados en memoria entre ejecuciones (y en Google Drive no siempre detecta los cambios):
# se recargan, en orden de dependencia, para que el tablero nunca use una versión vieja de logic.py ni de pipeline/.
for _modulo in ("pipeline.config", "pipeline.seguridad", "pipeline.utils", "pipeline.extract", "pipeline.transform_bev", "pipeline.transform_costos",
                "pipeline.transform_ecv", "pipeline.mart", "pipeline.load", "pipeline.main", "pipeline.ingest"):
    if _modulo in sys.modules:
        importlib.reload(sys.modules[_modulo])
L = importlib.reload(L)

st.set_page_config(page_title="Valor en Salud · Retina", page_icon="👁️", layout="wide")

# Color de cada nivel (figura "De los datos a la gestión del valor") y paleta categórica validada
NIVEL = {1: "#1F3A8A", 2: "#0A8FA3", 3: "#4C9A2A", 4: "#7A4FB0", 5: "#7A4FB0", 6: "#D26E00"}
CAT = ["#1F5FBF", "#D26E00", "#0A8FA3", "#7A4FB0", "#4C9A2A", "#8A5A44", "#C2185B"]
GRIS, SEL = "#8A94A3", "#D6336C"
COLOR_CUANTIL = {"Atípico inferior": "#C0392B", "Bigote abajo": "#E08A00", "Caja": "#1F5FBF", "Bigote arriba": "#4C9A2A", "Atípico superior": "#0A8FA3"}
VERDE, AMBAR, ROJO = "#4C9A2A", "#E0A100", "#C0392B"
COLOR_CAMBIO = {"Mejora (> +5)": VERDE, "Se mantiene (±5)": GRIS, "Empeora (< −5)": ROJO}

st.markdown(
    """<style>
    .block-container {padding-top: 1.6rem; max-width: 1400px;}
    div[data-testid="stMetric"] {background:#fff; border:1px solid #E3E7ED; border-radius:10px; padding:8px 12px;}
    div[data-testid="stMetricValue"] {font-size:1.55rem;}
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *, [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {white-space: normal !important; overflow: visible !important; text-overflow: clip !important;}
    [data-testid="stMetricLabel"] p {line-height:1.15;}
    .nivel {border-left:6px solid var(--c); padding:2px 12px; margin:0 0 .6rem 0;}
    .nivel h3 {margin:0; color:var(--c);} .nivel p {margin:0; color:#5B6675;}
    .nd {color:#8A94A3; font-style:italic;}
    .dxn {display:inline-block; margin-right:22px; color:#33415C;} .dxn b {color:#1B2430;}
    .flujo {display:flex; align-items:stretch; gap:6px; margin:.4rem 0 1rem 0;}
    .etapa {flex:1; background:#fff; border:1px solid #E3E7ED; border-radius:12px; padding:10px 12px; text-align:center;}
    .etapa .num {color:#8A94A3; font-size:.75rem;} .etapa .tit {font-weight:700; letter-spacing:.04em; font-size:.8rem; color:#1B2430;}
    .etapa .val {font-size:1.7rem; font-weight:800; color:#1B2430; margin:.2rem 0;} .etapa .sub {color:#5B6675; font-size:.78rem;}
    .flecha {align-self:center; color:#8A94A3; font-size:1.3rem;}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Cargando datos…")
def _datos(ruta: str, marca: float, llave: bytes | None = None):
    """`marca` = fecha de modificación de los resultados: si se vuelve a correr el proceso, la caché se renueva sola."""
    return L.cargar(Path(ruta), llave)


@st.cache_data(show_spinner=False)
def _aplicaciones(ruta: str, marca: float, llave: bytes | None = None):
    return L.cargar_aplicaciones(Path(ruta), llave)


def pantalla_clave() -> None:
    """Datos protegidos: se piden la clave una vez por sesión; la llave derivada queda solo en memoria."""
    st.title("Datos protegidos")
    st.markdown("Esta corrida está **cifrada**. Escriba la clave para abrirla; los datos se descifran solo en memoria.")
    with st.form("clave"):
        clave = st.text_input("Clave", type="password")
        enviar = st.form_submit_button("Desbloquear")
    if enviar:
        llave = seguridad.llave_desde_clave(clave)
        if llave is None:
            st.error("Clave incorrecta.")
        else:
            st.session_state["llave_datos"] = llave
            st.rerun()


def pantalla_carga(corridas: list) -> None:
    """Cargar un insumo nuevo (datos reales): se valida, se guarda en la carpeta compartida y se procesa."""
    st.title("Cargar nuevo insumo")
    st.markdown("Suba el libro del formulario de un prestador. Se **valida**, se **guarda** en la carpeta de datos "
                f"compartida (`{config.DATA_ROOT}`) y se **procesa**; al terminar el tablero muestra la nueva carga. "
                "Si algo falla, no se pierde ni se modifica ninguna carga anterior.")
    c1, c2, c3 = st.columns(3)
    usuario = c1.text_input("Su nombre *", key="up_usuario", help="Queda registrado en el manifest de la entrega.")
    existentes = ingest.listar_prestadores()
    elegido = c2.selectbox("Prestador *", existentes + ["➕ Nuevo prestador"], key="up_prestador")
    prestador = c2.text_input("Código del nuevo prestador", key="up_prestador_nuevo", placeholder="p. ej. p3") if elegido.startswith("➕") else elegido
    version = c3.text_input("Versión del formulario *", key="up_version", placeholder="p. ej. 5.3.3")
    libro = st.file_uploader("Libro del formulario (.xlsm) *", type=["xlsm", "xlsx"], key="up_libro")
    with st.expander("Calidad de vida y costos (opcional)"):
        ecv = st.file_uploader("Resultado de calidad de vida (prom_dimensiones, .xlsx)", type=["xlsx"], key="up_ecv",
                               help="Sin este archivo los indicadores de ECV quedan vacíos; nunca se toman de otro prestador.")
        modo_txt = st.radio("Costos unitarios", ["Hoja 'maestra_costos' del libro", "Subir la tabla de costos", "Tabla de costos de referencia del proyecto"], key="up_costos_modo")
        costos = st.file_uploader("Tabla de costos (.xlsx, hoja 'maestra_costos')", type=["xlsx"], key="up_costos") if modo_txt.startswith("Subir") else None
    modo = "archivo" if modo_txt.startswith("Subir") else ("dummy" if modo_txt.startswith("Tabla de costos de referencia") else "libro")
    pin = st.text_input("Clave de carga", type="password", key="up_pin") if config.UPLOAD_PIN else ""
    if st.button("Validar y procesar", type="primary", disabled=libro is None, key="up_boton"):
        if config.UPLOAD_PIN and pin != config.UPLOAD_PIN:
            st.error("Clave de carga incorrecta.")
        else:
            with st.status("Procesando…", expanded=True) as estado:
                try:
                    res = ingest.registrar_entrega(
                        prestador=prestador or "", version=version, usuario=usuario, libro=libro.getvalue(), libro_nombre=libro.name,
                        ecv=ecv.getvalue() if ecv else None, ecv_nombre=ecv.name if ecv else "ecv.xlsx", costos_modo=modo,
                        costos=costos.getvalue() if costos else None, costos_nombre=costos.name if costos else "costos.xlsx",
                        progreso=lambda m: st.write(m))
                except ingest.CargaError as e:
                    estado.update(label="No se pudo cargar el insumo", state="error")
                    st.error(str(e))
                    res = None
                except Exception as e:  # noqa: BLE001 -- se muestra completo para poder reportarlo
                    estado.update(label="Error inesperado", state="error")
                    st.error("Error inesperado: avise al equipo técnico con este detalle.")
                    st.exception(e)
                    res = None
            if res is not None:
                st.cache_data.clear()
                st.session_state["corrida_ruta"] = str(res["processed"])
                st.session_state["_ir_tablero"] = True
                st.session_state["_aviso"] = f"Insumo cargado y procesado: {res['processed'].parent.name.upper()} · {res['processed'].name}."
                st.rerun()
    if corridas:
        st.markdown("##### Cargas disponibles")
        st.dataframe(pd.DataFrame([{"Prestador": str(c["meta"].get("prestador", "")).upper(), "Versión": c["meta"].get("version", "—"),
                                    "Generada": str(c["generado"])[:16].replace("T", " "), "Cargada por": c["meta"].get("cargado_por", "—"),
                                    "Costos": "Tabla de referencia" if c["meta"].get("costos_es_dummy") else (c["meta"].get("costos_fuente") or "—")} for c in corridas]),
                     hide_index=True)


# ---- sección (Tablero / Cargar insumo) y corrida de datos
CORRIDAS = L.listar_corridas()
st.sidebar.title("Valor en Salud")
if st.session_state.pop("_ir_tablero", False):
    st.session_state["seccion"] = "Tablero"
st.session_state.setdefault("seccion", "Tablero" if CORRIDAS else "Cargar insumo")
if getattr(config, "CARGA_HABILITADA", True):
    SECCION = st.sidebar.radio("Sección", ["Tablero", "Cargar insumo"], key="seccion")
else:   # despliegue de solo consulta: sin carga de archivos
    SECCION = "Tablero"
if SECCION == "Cargar insumo":
    pantalla_carga(CORRIDAS)
    st.stop()
if not CORRIDAS:
    st.title("Valor en Salud · Retina")
    st.info("Todavía no hay datos procesados. Vaya a **Cargar insumo** (barra lateral) y suba el libro del formulario.")
    st.stop()

_cifradas = {str(c["ruta"]) for c in CORRIDAS if seguridad.carpeta_cifrada(c["ruta"])}
_etiquetas = [(c["etiqueta"] + (" 🔒" if str(c["ruta"]) in _cifradas else "")) if [x["etiqueta"] for x in CORRIDAS].count(c["etiqueta"]) == 1 else f'{c["etiqueta"]} ({i + 1})'
              for i, c in enumerate(CORRIDAS)]
_pos = next((i for i, c in enumerate(CORRIDAS) if str(c["ruta"]) == st.session_state.get("corrida_ruta")), 0)
_i = _etiquetas.index(st.sidebar.selectbox("Corrida de datos", _etiquetas, index=_pos,
                                           help="Cada carga queda guardada con su prestador y versión; elija cuál ver (por defecto, la más reciente)."))
st.session_state["corrida_ruta"] = str(CORRIDAS[_i]["ruta"])
LLAVE = st.session_state.get("llave_datos") or (seguridad.llave_de_entorno() if seguridad.hay_cifrado() else None)
if str(CORRIDAS[_i]["ruta"]) in _cifradas and LLAVE is None:
    pantalla_clave()
    st.stop()
try:
    MART, META = _datos(str(CORRIDAS[_i]["ruta"]), (CORRIDAS[_i]["ruta"] / "metadata.json").stat().st_mtime, LLAVE)
except (FileNotFoundError, OSError, ValueError) as e:
    st.error(f"No se pudo leer la corrida seleccionada: {e}")
    st.stop()
st.sidebar.markdown("---")

APL_TODAS = _aplicaciones(str(CORRIDAS[_i]["ruta"]), (CORRIDAS[_i]["ruta"] / "metadata.json").stat().st_mtime, LLAVE)
TOL_PROG = int(META.get("tolerancia_programacion_dias", 8))   # corridas anteriores a la unificación usaban ±8
DQ = META.get("calidad_insumo", {})
SECA_OK = DQ.get("retina_seca_evaluable", True)
CUMPL_OK = DQ.get("cumplimiento_programacion_evaluable", True)
NO_EVAL = "No evaluable: el insumo no trae los campos necesarios (ver nota de calidad de datos)."
PRESTADOR = META.get("prestador", "sin_definir")
COSTOS_DUMMY = bool(META.get("costos_es_dummy"))
TAG_DUMMY = ""   # los costos ya no llevan etiqueta de prueba en pantalla
AVISOS_DEMO = config.MOSTRAR_AVISOS_DEMO   # interruptor opcional (VLM_MOSTRAR_AVISOS_DEMO=1): nota discreta de datos de demostración


def encabezado(nivel: int, titulo: str, pregunta: str) -> None:
    st.markdown(f'<div class="nivel" style="--c:{NIVEL[nivel]}"><h3>{nivel}. {titulo}</h3><p>{pregunta}</p></div>',
                unsafe_allow_html=True)


def card(col, etiqueta: str, valor: str, n: int, delta: str | None = None, ok: bool = True, ayuda: str = "") -> None:
    with col:
        if not ok:
            st.metric(etiqueta, "N/E", help=NO_EVAL)
        else:
            st.metric(etiqueta, valor, delta=delta, help=(ayuda + f" (n = {n:,})").strip())


def delta(a, b, dec=1, unidad=""):
    return None if pd.isna(a) or pd.isna(b) else f"{L.f_num(b - a, dec, True)}{unidad} A2 vs A1"


def par(a, b, f) -> str:
    return f"{f(a)} / {f(b)}"


def color_sem(pct) -> str:
    if pd.isna(pct):
        return GRIS
    return VERDE if pct >= L.UMBRAL_VERDE else (AMBAR if pct >= L.UMBRAL_AMBAR else ROJO)


def rgba(hexc: str, a: float) -> str:
    h = hexc.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def etq(t) -> str:
    """Etiqueta de categoría en dos líneas: 'DMREh · Aflibercept' -> 'DMREh<br>Aflibercept' (no se corta ni se amontona)."""
    return str(t).replace(" · ", "<br>")


def ejex_categorico(fig, categorias, textos=None) -> None:
    """Muestra TODAS las categorías del eje x (plotly omite algunas cuando no caben)."""
    cats = list(dict.fromkeys(categorias))
    fig.update_xaxes(tickmode="array", tickvals=cats, ticktext=[etq(t) for t in (textos or cats)])


def rango_con_holgura(valores, holgura=0.2, piso_cero=True):
    """Rango del eje y con espacio para que las etiquetas de datos queden DENTRO del gráfico."""
    v = pd.to_numeric(pd.Series(list(valores)), errors="coerce").dropna()
    if v.empty:
        return None
    lo = min(0.0, float(v.min())) if piso_cero else float(v.min())
    hi = max(0.0, float(v.max())) if piso_cero else float(v.max())
    span = (hi - lo) or 1.0
    return [lo - holgura * span if (lo < 0 or not piso_cero) else lo, hi + holgura * span]


def base_layout(fig, titulo: str, alto: int, **kw) -> None:
    """Título envuelto en varias líneas (no se corta en columnas angostas) y leyenda horizontal SIEMPRE visible
    justo debajo del título, con el margen superior calculado para ambos. Los ejes reservan espacio solos (automargin)."""
    kw.pop("legend", None)                     # la posición de la leyenda es única para todas las gráficas
    forzar = kw.pop("showlegend", None) is True
    lineas = textwrap.wrap(titulo, 44) or [titulo]
    t_titulo = 22 * len(lineas) + 16
    nombres = [str(t.name) for t in fig.data if t.name and t.showlegend is not False]
    con_leyenda = len(nombres) > 1 or (forzar and len(nombres) >= 1)
    filas = max(1, -(-int(sum(len(n) + 7 for n in nombres) * 6.6) // 340)) if con_leyenda else 0
    t_leyenda = filas * 19 + (6 if filas else 0)
    total = alto + t_leyenda + (t_titulo - 28)
    fig.update_layout(
        height=total,
        title=dict(text="<br>".join(lineas), font_size=14, x=0, xanchor="left", y=1, yanchor="top", yref="container", pad=dict(t=14)),
        margin=dict(l=10, r=14, t=t_titulo + t_leyenda + 12, b=10), plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=bool(filas),
        legend=dict(orientation="h", yref="container", yanchor="top", y=1 - (t_titulo + 2) / total, x=0, xanchor="left",
                    font=dict(size=11), tracegroupgap=2),
        uniformtext=dict(minsize=9, mode="show"), **kw)
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(gridcolor="#EEF0F3", automargin=True)


# ============================================================================ filtros
st.sidebar.markdown("### Filtros")
dx_all = MART["diagnostico"].value_counts().index.tolist()
dx_def = [d for d in ("DMREn", "EMD") if d in dx_all]
if len(dx_def) < 2:   # p. ej. un prestador escribe "DMREh": no esconder datos por defecto; se parte de todos los diagnósticos
    dx_def = dx_all
dx_sel = st.sidebar.multiselect("Diagnóstico", dx_all, default=dx_def)
med_all = sorted(MART["medicamento_label"].unique())
med_sel = st.sidebar.multiselect("Medicamento", med_all, default=med_all)
anios = MART["anio_inicio"].dropna().astype(int)
rango = st.sidebar.slider("Año de inicio del tratamiento", int(anios.min()), int(anios.max()),
                          (int(anios.min()), int(anios.max())))
seg = st.sidebar.radio("Seguimiento", ["Todos", "Con AV a S52", "Con AV a S104"],
                       help="Los indicadores de S52/S104 solo usan paciente-ojo reingreso con dato en esa semana; "
                            "este filtro restringe TODO el tablero a esa cohorte.")

df = MART[MART["diagnostico"].isin(dx_sel) & MART["medicamento_label"].isin(med_sel)
          & MART["anio_inicio"].between(*rango)]
if seg == "Con AV a S52":
    df = df[df["tiene_s52"]]
elif seg == "Con AV a S104":
    df = df[df["tiene_s104"]]

BANDAS_SEL = st.sidebar.multiselect(
    "Cuartil de AV inicial", L.BANDAS_AV, default=L.BANDAS_AV,
    help="Q1: AV inicial de 0 a 30 letras · Q2-Q3: 30 a 65 · Q4: 65 a 85. Filtra TODO el tablero (menos calidad de vida, que usa "
         "su propio universo).")
if set(BANDAS_SEL) != set(L.BANDAS_AV):
    df = df[L.banda_av(df["AV_letras_inicial"]).isin(BANDAS_SEL)]

if df.empty:
    st.sidebar.warning("Los filtros no dejan ningún paciente-ojo reingreso.")
    st.warning("Los filtros no dejan ningún paciente-ojo reingreso.")
    st.stop()

# ---- gráfico de espagueti: todos los paciente-ojo reingreso disponibles + filtro por cantidad
TRAY = L.trayectorias_av(df)
st.sidebar.markdown("---")
st.sidebar.markdown("**Gráfico de trayectorias (espagueti)**")
VARIABLES_Q = {"AV inicial": "AV_letras_inicial", "Δ AV S16": "dif_lts_sem16", "Δ AV S52": "dif_lts_sem52", "Δ AV S104": "dif_lts_sem104"}
VAR_Q = st.sidebar.selectbox("Cuantiles de", list(VARIABLES_Q), index=0,
                             help="Variable con la que se calculan la caja y los bigotes (regla de Tukey, 1,5 × RIQ) sobre los paciente-ojo reingreso "
                                  "del filtro actual (diagnóstico, medicamento, año y seguimiento).")
BASE_Q = df.set_index("pacienteojoreingreso")[VARIABLES_Q[VAR_Q]]
GRUPO_Q = L.grupo_cuantil(BASE_Q)
TUKEY_Q = L.tukey(BASE_Q)
GRUPOS_Q = st.sidebar.multiselect("Grupo (cuantil)", L.GRUPOS_CUANTIL, default=L.GRUPOS_CUANTIL,
                                  help="Bigote abajo: del límite inferior a Q1 · Caja: Q1 a Q3 · Bigote arriba: Q3 al límite superior · "
                                       "Atípicos: fuera de los bigotes.")
if TUKEY_Q:
    cuentas_q = GRUPO_Q.value_counts()
    st.sidebar.caption(f"{VAR_Q}: Q1 = {L.f_num(TUKEY_Q['q1'])} · Q3 = {L.f_num(TUKEY_Q['q3'])} · bigotes [{L.f_num(TUKEY_Q['lim_inf'])}; "
                       f"{L.f_num(TUKEY_Q['lim_sup'])}]. " + " · ".join(f"{g}: {int(cuentas_q.get(g, 0)):,}" for g in L.GRUPOS_CUANTIL))
if set(GRUPOS_Q) != set(L.GRUPOS_CUANTIL):
    TRAY = TRAY[TRAY["id"].map(GRUPO_Q).isin(GRUPOS_Q)]
TOTAL_TRAY = int(TRAY["id"].nunique())
if TOTAL_TRAY > 1:
    N_DIBUJAR = st.sidebar.slider("Paciente-ojo reingreso a dibujar", 1, TOTAL_TRAY, TOTAL_TRAY,
                                  help=f"Por defecto se dibujan los {TOTAL_TRAY:,} paciente-ojo reingreso con al menos una medición "
                                       "posterior a la línea base. Bájelo para ver menos líneas.")
else:
    N_DIBUJAR = TOTAL_TRAY
CRITERIO = st.sidebar.selectbox("Cuáles mostrar", L.CRITERIOS_ESPAGUETI, disabled=N_DIBUJAR >= TOTAL_TRAY,
                                help="Criterio para escoger los paciente-ojo reingreso cuando se dibujan menos que el total.")
COLOR_POR = st.sidebar.selectbox("Colorear por", ["Sin color", "Cambio AV (mejora / se mantiene / empeora)", "Grupo de cuantil", "Diagnóstico", "Medicamento"])
IDS_DIBUJAR = L.elegir_pacientes(TRAY, N_DIBUJAR, CRITERIO)

st.sidebar.markdown("---")
st.sidebar.metric("Paciente-ojo reingreso en el filtro", f"{len(df):,}".replace(",", "."))
st.sidebar.caption(f"Paciente-ojo: {df['pacienteojo'].nunique():,} · Pacientes con degeneración macular: {df['numero_doc'].nunique():,}".replace(",", "."))
st.sidebar.caption(f"Prestador: **{PRESTADOR.upper()}** · insumo: {META.get('insumo', '—')} · corrida {META.get('generado', '—')}")
if COSTOS_DUMMY:
    st.sidebar.caption("Costos unitarios: tabla de referencia")
else:
    st.sidebar.caption(f"Costos unitarios: {META.get('costos_fuente', '—')}")
if AVISOS_DEMO and (COSTOS_DUMMY or META.get("es_demo")):
    st.sidebar.caption("ℹ️ Modo demostración: costos de referencia y/o datos sintéticos.")

df = L.enmascarar_anios(df)   # año 1/2: solo paciente-ojo reingreso con 2 años de seguimiento posible
K = L.kpis(df)
if "sel" not in st.session_state or st.session_state["sel"] not in set(MART["pacienteojoreingreso"]):
    st.session_state["sel"] = None

st.title("Valor en Salud · Retina")
if st.session_state.get("_aviso"):
    st.success(st.session_state.pop("_aviso"))
notas = []
if not SECA_OK:
    notas.append(f"**{L.N_SECA} y % respondedores no son evaluables**: `oct_srf` viene {DQ.get('oct_srf_completo_pct', 0)} % completo "
                 f"y `oct_irf` es constante en el insumo.")
if not CUMPL_OK:
    notas.append(f"**{L.N_CUMPL} no es evaluable**: `fecha_programacion` viene "
                 f"{DQ.get('fecha_programacion_completa_pct', 0)} % completa.")
if notas:
    with st.expander("⚠️ Calidad de datos del insumo", expanded=False):
        for t in notas:
            st.markdown("- " + t)
        st.caption("Corrija en el formulario de origen y vuelva a correr el pipeline: los KPIs se activan solos.")


# ============================================================================ componentes
def espagueti(key: str, titulo: str = "Trayectoria individual del cambio en agudeza visual") -> None:
    """Figura de la propuesta: una línea por paciente-ojo reingreso (LB → S16 → S52 → S104), promedio en trazo grueso y
    umbral de +5 letras. Dibuja los paciente-ojo reingreso elegidos en la barra lateral; el promedio usa SIEMPRE a todos.
    Clic en un punto = selecciona el paciente-ojo reingreso (ficha en la pestaña 4)."""
    if TOTAL_TRAY == 0:
        st.info("Sin trayectorias con al menos una medición posterior a la línea base para este filtro.")
        return
    sub = TRAY[TRAY["id"].isin(IDS_DIBUJAR)].copy()
    if COLOR_POR.startswith("Cambio"):
        sub["grupo"] = sub["ultimo"].map(L.clase_cambio)
    elif COLOR_POR == "Grupo de cuantil":
        sub["grupo"] = sub["id"].map(GRUPO_Q)
    elif COLOR_POR == "Diagnóstico":
        sub["grupo"] = sub["diagnostico"]
    elif COLOR_POR == "Medicamento":
        sub["grupo"] = sub["medicamento_label"]
    else:
        sub["grupo"] = "paciente-ojo reingreso"
    orden_g = list(COLOR_CAMBIO) + L.GRUPOS_CUANTIL
    grupos = sorted(sub["grupo"].unique(), key=lambda g: (orden_g.index(g), "") if g in orden_g else (len(orden_g), str(g)))
    transp = 0.28 if len(IDS_DIBUJAR) > 150 else 0.5

    fig = go.Figure()
    for i, g in enumerate(grupos):
        color = COLOR_CAMBIO.get(g) or COLOR_CUANTIL.get(g) or (GRIS if g == "paciente-ojo reingreso" else CAT[i % len(CAT)])
        xs, ys, cd = [], [], []
        for pid, t in sub[sub["grupo"] == g].groupby("id"):
            xs += t["x"].tolist() + [None]
            ys += t["valor"].tolist() + [None]
            cd += [pid] * len(t) + [None]
        n_g = sub.loc[sub["grupo"] == g, "id"].nunique()
        fig.add_trace(go.Scatter(x=xs, y=ys, customdata=cd, mode="lines+markers", name=f"{g} ({n_g})", legendgroup=g,
                                 line=dict(color=rgba(color, transp), width=1), marker=dict(size=5, color=rgba(color, min(1, transp + .25))),
                                 hovertemplate="%{customdata}<br>%{y:+.0f} letras<extra>" + g + "</extra>", connectgaps=False))
    prom = TRAY.groupby(["x", "etiqueta"])["valor"].mean().reset_index()
    fig.add_trace(go.Scatter(x=prom["x"], y=prom["valor"], mode="lines+markers+text", name=f"Promedio (todos: {TOTAL_TRAY:,})",
                             line=dict(color="#0B7285", width=4), marker=dict(size=10),
                             hovertemplate="Promedio %{customdata}: %{y:+.1f} letras<extra></extra>", customdata=prom["etiqueta"],
                             text=[f"{v:+.1f}" for v in prom["valor"]], textposition="bottom center", textfont=dict(size=12, color="#0B7285"),
                             cliponaxis=False))
    fig.add_trace(go.Scatter(x=[-0.15, 3.15], y=[L.UMBRAL_MEJORA_LETRAS] * 2, mode="lines", name="Umbral +5 letras",
                             line=dict(color="#1F77B4", dash="dash", width=1.5), hoverinfo="skip"))
    n_x = TRAY.groupby("x")["id"].nunique()
    sel = st.session_state["sel"]
    if sel is not None and sel in set(TRAY["id"]):
        t = TRAY[TRAY["id"] == sel]
        fig.add_trace(go.Scatter(x=t["x"], y=t["valor"], mode="lines+markers", name=f"Seleccionado: {sel}",
                                 line=dict(color=SEL, width=3.5), marker=dict(size=11, line=dict(width=2, color="#fff"))))
    base_layout(fig, titulo, 460, clickmode="event+select",
                xaxis=dict(tickmode="array", tickvals=list(range(len(L.PUNTOS_ESPAGUETI))),
                           ticktext=[f"{p[0]}<br>n={int(n_x.get(i, 0)):,}" for i, p in enumerate(L.PUNTOS_ESPAGUETI)], range=[-0.15, 3.15]),
                yaxis=dict(title="Cambio AV (letras)", zeroline=True, zerolinecolor="#C9CFD8"))
    ev = st.plotly_chart(fig, key=key, on_select="rerun", selection_mode="points", use_container_width=True)
    pts = (ev or {}).get("selection", {}).get("points", []) if isinstance(ev, dict) or hasattr(ev, "get") else []
    for p in pts:
        cdv = p.get("customdata")
        cdv = cdv[0] if isinstance(cdv, (list, tuple)) and cdv else cdv
        if cdv and cdv != st.session_state["sel"]:
            st.session_state["sel"] = cdv
            st.rerun()
    n_dib = len(IDS_DIBUJAR)
    cuales = "todos los paciente-ojo reingreso disponibles" if n_dib >= TOTAL_TRAY else f"selección: {CRITERIO.lower()}"
    st.caption(f"Mostrando **{n_dib:,} de {TOTAL_TRAY:,}** paciente-ojo reingreso ({cuales}). El promedio usa a todos. "
               "Ajuste la cantidad en la barra lateral. Clic en un punto para seleccionar un paciente-ojo reingreso.")


def ficha_panel(fila: pd.Series) -> None:
    """FICHA PACIENTE-OJO de la propuesta, en columna."""
    def v(c, f=lambda x: L.f_num(x, 1)):
        return f(fila[c]) if c in fila and pd.notna(fila[c]) else "—"
    si_no = lambda x: "—" if pd.isna(x) else ("Sí" if x >= 0.5 else "No")  # noqa: E731
    st.markdown(f"#### Ficha · `{fila['pacienteojoreingreso']}`")
    a, b = st.columns(2)
    a.metric("Diagnóstico", fila["diagnostico"])
    b.metric("Medicamento", fila["medicamento_label"])
    a, b, c = st.columns(3)
    for col, s in zip((a, b, c), (16, 52, 104)):
        col.metric(f"Δ AV S{s}", v(f"dif_lts_sem{s}", lambda x: L.f_num(x, 0, True)))
    a, b, c = st.columns(3)
    a.metric(L.N_ADH, si_no(fila["adherencia_carga"]))
    b.metric("Respondedor", si_no(fila["respondedor"]) if SECA_OK else "N/E")
    c.metric(L.N_SECA, si_no(fila["RetinaSeca_sem52"]) if SECA_OK else "N/E")
    a, b, c = st.columns(3)
    a.metric("Extensión S52 (sem)", v("extension_sem52"))
    b.metric("Extensión S104 (sem)", v("extension_sem104"))
    c.metric(L.N_CUMPL, "N/E" if not CUMPL_OK else v("cumplimiento_anio1", lambda x: f"{x * 100:.0f} %"))
    st.metric("Δ ECV", v("delta_ecv", lambda x: L.f_num(x, 1, True)))
    a, b = st.columns(2)
    a.metric("Inyecciones A1 / A2", f"{v('apl_anio1', lambda x: f'{x:.0f}')} / {v('apl_anio2', lambda x: f'{x:.0f}')}")
    b.metric(f"Costo A1 / A2{TAG_DUMMY}", f"{v('costofin_anio1', L.f_millones)} / {v('costofin_anio2', L.f_millones)}")


def trayectoria_paciente(fila: pd.Series, key: str) -> None:
    sem = [16, 52, 104]
    av = [fila.get("AV_letras_inicial")] + [fila.get(f"AV_letras_sem{s}") for s in sem]
    oc = [fila.get("OCT_inicial")] + [fila.get(f"OCT_sem{s}") for s in sem]
    x = ["LB"] + [f"S{s}" for s in sem]
    g1, g2 = st.columns(2)
    for col, y, nom, color, suf in ((g1, av, "AV (letras ETDRS)", CAT[0], "av"), (g2, oc, "Espesor OCT (µm)", CAT[1], "oct")):
        fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers+text", text=[L.f_num(t, 0) for t in y], textposition="top center",
                                   line=dict(color=color, width=3), marker=dict(size=9), connectgaps=True, cliponaxis=False))
        rg = rango_con_holgura(y, 0.25, piso_cero=False)
        base_layout(fig, nom, 270, **({"yaxis": dict(range=rg)} if rg else {}))
        col.plotly_chart(fig, use_container_width=True, key=f"{key}-{suf}")


def barras_cohorte(res: pd.DataFrame, cols: dict, titulo: str, fmt=".1f", ejey="", ok=True, alto=320, vertical=False):
    """Barras por cohorte con TODAS las etiquetas: valor sobre cada barra y 'cohorte (n=…)' en el eje. Con más de 5 cohortes
    pasa a barras horizontales para que cada etiqueta quepa entera en vez de girarse o amontonarse."""
    if not ok:
        st.markdown(f"**{titulo}**")
        st.markdown(f'<span class="nd">{NO_EVAL}</span>', unsafe_allow_html=True)
        return
    horizontal = len(res) > 5 and not vertical   # con AV el valor va siempre en el eje Y
    etiquetas = [f"{c} (n={n})" for c, n in zip(res["cohorte"], res["n"])] if "n" in res else list(res["cohorte"])
    fig = go.Figure()
    for i, (c, nom) in enumerate(cols.items()):
        textos = res[c].map(lambda t: "" if pd.isna(t) else format(t, fmt))
        comun = dict(name=nom, marker_color=CAT[i % len(CAT)], text=textos, textposition="outside", cliponaxis=False)
        if horizontal:
            fig.add_trace(go.Bar(y=etiquetas, x=res[c], orientation="h", hovertemplate="%{y}<br>" + nom + ": %{x:" + fmt + "}<extra></extra>", **comun))
        else:
            fig.add_trace(go.Bar(x=etiquetas, y=res[c], hovertemplate="%{x}<br>" + nom + ": %{y:" + fmt + "}<extra></extra>", **comun))
    rg = rango_con_holgura(res[list(cols)].to_numpy().ravel(), 0.25)
    if horizontal:
        alto = max(alto, 46 * len(res) * max(1, len(cols) * 0.6) + 90)
        base_layout(fig, titulo, int(alto), barmode="group", showlegend=True, xaxis=dict(title=ejey, **({"range": rg} if rg else {})),
                    yaxis=dict(autorange="reversed", tickmode="array", tickvals=etiquetas, ticktext=etiquetas))
    else:
        base_layout(fig, titulo, alto, barmode="group", showlegend=True, yaxis=dict(title=ejey, **({"range": rg} if rg else {})))
        ejex_categorico(fig, etiquetas, [e.replace(" (n=", "<br>n=").rstrip(")") for e in etiquetas])
    st.plotly_chart(fig, use_container_width=True, key=f"cohorte-{titulo}")


def violines(d: pd.DataFrame, cols: dict, titulo: str, key: str, eje: str, alto=340, minimo=3) -> None:
    """Violín/boxplot por cohorte; `cols` = {columna: etiqueta} (varias = series agrupadas, p. ej. Año 1 y Año 2)."""
    fig, hay = go.Figure(), False
    for i, (c, nom) in enumerate(cols.items()):
        ok = d.groupby("cohorte")[c].count()
        ok = ok[ok >= minimo].index
        dd = d[d["cohorte"].isin(ok) & d[c].notna()]
        if dd.empty:
            continue
        hay = True
        fig.add_trace(go.Violin(x=dd["cohorte"], y=dd[c], name=nom, legendgroup=nom, scalegroup=nom, box_visible=True,
                                meanline_visible=True, line_color=CAT[i], fillcolor=rgba(CAT[i], .35), opacity=1,
                                points="all", pointpos=0, jitter=.35, marker=dict(size=3, color=CAT[i], opacity=.5)))
    if not hay:
        st.markdown(f"**{titulo}**")
        st.markdown(f'<span class="nd">Ninguna cohorte tiene al menos {minimo} paciente-ojo reingreso con dato.</span>', unsafe_allow_html=True)
        return
    cats = [c for c in d["cohorte"].unique() if any(d.loc[d["cohorte"] == c, k].notna().sum() >= minimo for k in cols)]
    textos = [f"{c}<br>n=" + "/".join(str(int(d.loc[d["cohorte"] == c, k].notna().sum())) for k in cols) for c in cats]
    if len(cols) == 1:   # una sola serie: la media va escrita sobre cada violín
        k = next(iter(cols))
        med = d[d["cohorte"].isin(cats)].groupby("cohorte")[k].mean().reindex(cats)
        fig.add_trace(go.Scatter(x=cats, y=med.values, mode="markers+text", name="Media", marker=dict(symbol="diamond", size=9, color="#1B2430"),
                                 text=[L.f_num(v, 1) for v in med.values], textposition="middle right", textfont=dict(size=11),
                                 cliponaxis=False, hovertemplate="Media: %{y:.1f}<extra></extra>"))
    base_layout(fig, titulo, alto, violinmode="group", showlegend=True, yaxis=dict(title=eje))
    ejex_categorico(fig, cats, textos)
    st.plotly_chart(fig, use_container_width=True, key=key)


def _dispersion(d: pd.DataFrame, semana: int, costo: str, nombre_costo: str, key: str, alto: int) -> None:
    """'Resultado funcional vs costo': un punto por paciente-ojo reingreso. AV (Δ letras) en el eje Y, costo en el eje X."""
    titulo = f"Δ AV S{semana} vs {nombre_costo}"
    pts = L.dispersion_valor(d, semana, costo).merge(d[["pacienteojoreingreso", "cohorte"]], on="pacienteojoreingreso")
    if pts.empty:
        st.markdown(f"**{titulo}**")
        st.markdown(f'<span class="nd">Ningún paciente-ojo reingreso tiene a la vez Δ AV a S{semana} y {nombre_costo.lower()}.</span>', unsafe_allow_html=True)
        return
    fig = go.Figure()
    for i, (coh, g) in enumerate(pts.groupby("cohorte")):
        fig.add_trace(go.Scatter(x=g["costo_total"], y=g[f"dif_lts_sem{semana}"], mode="markers", name=f"{coh} ({len(g)})",
                                 marker=dict(size=9, color=rgba(CAT[i % len(CAT)], .75), line=dict(width=1, color="#fff")),
                                 customdata=g["pacienteojoreingreso"],
                                 hovertemplate="%{customdata}<br>Δ AV: %{y:+.0f} letras<br>" + nombre_costo + ": $ %{x:,.0f}<extra></extra>"))
    fig.add_hline(y=L.UMBRAL_MEJORA_LETRAS, line_dash="dash", line_color="#1F77B4", annotation_text="Umbral +5 letras",
                  annotation_position="top right", annotation_font=dict(size=11, color="#1F77B4"))
    base_layout(fig, titulo, alto, showlegend=True, xaxis=dict(title=f"{nombre_costo} ($)", gridcolor="#EEF0F3"),
                yaxis=dict(title=f"Δ AV S{semana} (letras)"))
    st.plotly_chart(fig, use_container_width=True, key=key)
    st.caption(f"n = {len(pts):,} paciente-ojo reingreso con Δ AV a S{semana} y {nombre_costo.lower()}. Línea punteada: umbral +5 letras.")


def dispersion_costos(d: pd.DataFrame, semana: int, key: str, alto: int = 360, lado_a_lado: bool = True) -> None:
    """Dos figuras que responden al filtro de semana: S52 -> costo Año 1; S104 -> costo Año 2; y siempre Año 1 + Año 2."""
    anio = 1 if semana <= 52 else 2
    figuras = [(f"anio{anio}", f"Costo Año {anio}"), ("total", "Costo Año 1 + Año 2")]
    cols = st.columns(2) if lado_a_lado else [st.container(), st.container()]
    for col, (modo, nombre) in zip(cols, figuras):
        with col:
            _dispersion(d, semana, modo, nombre, f"{key}-{modo}", alto)


def panel_cb(df_: pd.DataFrame, columnas: dict, titulo: str, key: str, eje: str, alto: int = 330) -> list:
    """Caja y bigotes (Tukey, 1,5 × RIQ) de una o varias variables numéricas, con su tabla de variación al lado.
    Devuelve los nombres de las variables que quedaron fuera por tener muy pocos datos."""
    utiles = {c: n for c, n in columnas.items() if c in df_ and df_[c].notna().sum() >= 5}
    fuera = [n for c, n in columnas.items() if c not in utiles]
    if not utiles:
        st.markdown(f"**{titulo}**")
        st.markdown('<span class="nd">Sin datos suficientes en este insumo.</span>', unsafe_allow_html=True)
        return fuera
    izq, der = st.columns([3, 2])
    with izq:
        fig = go.Figure()
        for i, (c, n) in enumerate(utiles.items()):
            fig.add_trace(go.Box(y=df_[c].dropna(), name=f"{n} (n={int(df_[c].notna().sum()):,})", boxpoints="outliers", boxmean=True,
                                 marker=dict(color=CAT[i % len(CAT)], size=4, opacity=.6), line=dict(color=CAT[i % len(CAT)]),
                                 fillcolor=rgba(CAT[i % len(CAT)], .3), hovertemplate="%{y:.1f}<extra>" + n + "</extra>"))
        base_layout(fig, titulo, alto, showlegend=True, yaxis=dict(title=eje))
        ejex_categorico(fig, [f"{n} (n={int(df_[c].notna().sum()):,})" for c, n in utiles.items()],
                        [f"{n}<br>n={int(df_[c].notna().sum()):,}" for c, n in utiles.items()])
        st.plotly_chart(fig, use_container_width=True, key=key)
    with der:
        t = L.tabla_variacion(df_, utiles)
        est = ["Media", "Mediana", "Q1", "Q3", "Bigote inf.", "Bigote sup.", "Mín.", "Máx."]
        filas = {"n": [f"{int(x):,}".replace(",", ".") for x in t["n"]]}
        for e in est:
            filas[e] = [L.f_num(x, 1) for x in t[e]]
        filas["Atípicos"] = [f"{int(x):,}".replace(",", ".") for x in t["Atípicos"]]
        tabla_t = pd.DataFrame(filas, index=t["Variable"]).T
        st.markdown("**Tabla de variación**")
        st.dataframe(tabla_t, height=min(420, 38 * (len(tabla_t) + 1)))
        st.caption("Bigotes: último dato dentro de 1,5 × RIQ. Atípicos: fuera de los bigotes.")
    return fuera


# ============================================================================ pestañas
t1, t2, t3, t4, t_cv, t_valor = st.tabs(["1 · Visión ejecutiva", "2 · Cohortes", "3 · Gestión de la atención", "4 · Paciente-ojo", "5 · Calidad de vida", "6 · Valor"])

# ---------------------------------------------------------------- 1. Visión ejecutiva
with t1:
    encabezado(1, "Visión ejecutiva", "¿Estamos generando valor?")
    sexo = df["sexo"].fillna("Sin dato")
    sexos = [x for x in ("Femenino", "Masculino", "Sin dato") if x in set(sexo)]
    def _cuenta(col):
        return [df[col].nunique()] + [df.loc[sexo == x, col].nunique() for x in sexos]
    conteo = pd.DataFrame([_cuenta("numero_doc"), _cuenta("pacienteojo"), _cuenta("pacienteojoreingreso")], columns=["Total"] + sexos,
                          index=[L.N_PAC, "Paciente-ojo", "Paciente-ojo reingreso"])
    st.dataframe(conteo.map(lambda x: f"{int(x):,}".replace(",", ".")), height=38 * 4)
    cuentas = df.groupby("diagnostico").size().sort_values(ascending=False)
    st.markdown("".join(f'<span class="dxn"><b>{d}</b> · paciente-ojo reingreso · n={n:,}</span>' for d, n in cuentas.items()),
                unsafe_allow_html=True)
    st.markdown("**Resultados clínicos**")
    RESP_PRUEBA = config.RESPONDEDOR_PRUEBA is not None
    c = st.columns(4)
    card(c[0], "AV inicial | Δ AV S52 | Δ AV S104 (letras)",
         f"{L.f_num(K['av0_med'][0], 0)} | {L.f_num(K['dav52'][0], 1, True)} | {L.f_num(K['dav104'][0], 1, True)}", K["av0_med"][1],
         ayuda=f"AV inicial = mediana de la línea base (n={K['av0_med'][1]:,}). Δ = cambio promedio frente a la AV inicial "
               f"(S52 n={K['dav52'][1]:,} · S104 n={K['dav104'][1]:,}; S16: {L.f_num(K['dav16'][0], 1, True)}).")
    card(c[1], "% respondedores", L.f_pct(K["respondedor"][0]), K["respondedor"][1], ok=SECA_OK or RESP_PRUEBA,
         ayuda="Respondedor a S16 (criterio AV + líquido)." + (" VALOR DE PRUEBA fijado por configuración." if RESP_PRUEBA else ""))
    card(c[2], f"{L.N_SECA} S52 / S104", par(K["seca52"][0], K["seca104"][0], L.f_pct), K["seca52"][1], ok=SECA_OK)
    card(c[3], "OCT inicial | Δ OCT S52 | Δ OCT S104 (µm)",
         f"{L.f_num(K['oct0_med'][0], 0)} | {L.f_num(K['dmic52'][0], 0, True)} | {L.f_num(K['dmic104'][0], 0, True)}", K["oct0_med"][1],
         ayuda=f"OCT inicial = mediana del espesor macular central de la línea base (n={K['oct0_med'][1]:,}). Δ = cambio promedio "
               f"(S52 n={K['dmic52'][1]:,} · S104 n={K['dmic104'][1]:,}; S16: {L.f_num(K['dmic16'][0], 0, True)}). Negativo = el espesor baja.")
    st.markdown("**Utilización, paciente y costo**")
    c = st.columns(3)
    card(c[0], "Inyecciones (A1 / A2)", par(K["iny1"][0], K["iny2"][0], L.f_num), K["iny1"][1])
    card(c[1], "ECV (1 / 2)", par(K["ecv1"][0], K["ecv2"][0], lambda x: L.f_num(x, 1)), K["ecv2"][1],
         None if pd.isna(K["delta_ecv"][0]) else f"{L.f_num(K['delta_ecv'][0], 1, True)} (Δ)", ayuda="Encuesta 1 / encuesta 2 de calidad de vida, solo pacientes que respondieron ambas.")
    card(c[2], "Costo prom. (A1 / A2)", par(K["costo1"][0] / 1e6, K["costo2"][0] / 1e6, lambda x: L.f_num(x, 1)) + " M", K["costo1"][1],
         ayuda=f"A1 {L.f_money(K['costo1'][0])} · A2 {L.f_money(K['costo2'][0])}.")
    st.caption("Año 1 / año 2 (inyecciones, costos) usan solo paciente-ojo reingreso con 2 años de seguimiento posible. "
               f"Δ AV, respondedor y {L.N_SECA} usan a quienes tienen dato en cada semana.")

    izq, der = st.columns([2, 1])
    with izq:
        espagueti("spag1")
        if st.session_state["sel"] is not None:
            st.info(f"Seleccionado: **{st.session_state['sel']}** — su ficha está en la pestaña **4 · Paciente-ojo**.")
    with der:
        with st.container(border=True):
            st.markdown("**LECTURA EJECUTIVA**")
            partes = [f"• **Resultado funcional longitudinal:** Δ AV {L.f_num(K['dav16'][0], 1, True)} (S16), "
                      f"{L.f_num(K['dav52'][0], 1, True)} (S52) y {L.f_num(K['dav104'][0], 1, True)} letras (S104)."]
            partes.append("• **Respuesta clínica:** " + (f"{L.f_pct(K['respondedor'][0])} de respondedores." if SECA_OK else "no evaluable en este insumo."))
            partes.append("• **Resultado anatómico:** " + (f"{L.N_SECA.lower()} {L.f_pct(K['seca52'][0])} (S52) y {L.f_pct(K['seca104'][0])} (S104)." if SECA_OK else "no evaluable en este insumo."))
            if not pd.isna(K["oct0"][0]):
                partes.append(f"• **Espesor retiniano:** OCT inicial {L.f_num(K['oct0'][0], 0)} µm; cambio {L.f_num(K['dmic16'][0], 0, True)} (S16) y {L.f_num(K['dmic52'][0], 0, True)} µm (S52).")
            partes.append(f"• **Utilización de inyecciones:** {L.f_num(K['iny1'][0])} en el año 1 y {L.f_num(K['iny2'][0])} en el año 2.")
            partes.append(f"• **Costo por paciente-ojo reingreso{TAG_DUMMY}:** {L.f_money(K['costo1'][0])} el año 1 y {L.f_money(K['costo2'][0])} el año 2.")
            if not pd.isna(K["delta_ecv"][0]):
                partes.append(f"• **Calidad de vida:** Δ ECV {L.f_num(K['delta_ecv'][0], 1, True)} puntos entre encuestas.")
            partes.append("• **Profundizar en cohortes** (pestaña 2) cuando exista variabilidad entre paciente-ojo reingreso.")
            st.markdown("\n\n".join(partes).replace("$", "\\$"))

    # ---- 3.1 tabla de resultados (desplegable, mismos filtros)
    with st.expander("Tabla de resultados", expanded=False):
        def _f(v_, d_=1, sg=False):
            return L.f_num(v_, d_, sg)
        filas_t = [("AV inicial (letras)", _f(K["av0"][0]), K["av0"][1])]
        filas_t += [(f"Δ AV S{x} (letras)", _f(K[f"dav{x}"][0], 1, True), K[f"dav{x}"][1]) for x in (16, 52, 104)]
        filas_t += [("% respondedores", L.f_pct(K["respondedor"][0]) if SECA_OK else "N/E", K["respondedor"][1])]
        filas_t += [(f"{L.N_SECA} S{x}", L.f_pct(K[f"seca{x}"][0]) if SECA_OK else "N/E", K[f"seca{x}"][1]) for x in (16, 52, 104)]
        filas_t += [("OCT inicial (µm)", _f(K["oct0"][0], 0), K["oct0"][1])]
        filas_t += [(f"Δ OCT S{x} (µm)", _f(K[f"dmic{x}"][0], 0, True), K[f"dmic{x}"][1]) for x in (16, 52, 104)]
        filas_t += [(L.N_ADH, L.f_pct(K["carga"][0]), K["carga"][1]),
                    (f"{L.N_CUMPL} Año 1 / Año 2", "N/E" if not CUMPL_OK else par(K["cumpl1"][0], K["cumpl2"][0], L.f_pct), K["cumpl1"][1]),
                    (f"{L.N_EXT} (semanas)", _f(K["ext_ult"][0]), K["ext_ult"][1]),
                    ("Inyecciones Año 1 / Año 2", par(K["iny1"][0], K["iny2"][0], L.f_num), K["iny1"][1]),
                    (f"{L.N_ECV1} / ECV2 (puntaje total)", par(K["ecv1"][0], K["ecv2"][0], L.f_num), K["ecv2"][1]),
                    ("Costo promedio Año 1 / Año 2", par(K["costo1"][0], K["costo2"][0], L.f_money), K["costo1"][1])]
        st.dataframe(pd.DataFrame(filas_t, columns=["Indicador", "Valor", "n"]), hide_index=True)

    # ---- AV por cuartil de AV inicial: valor general vs. mediana y cambio frente a la base
    st.markdown("##### Agudeza visual por cuartil de AV inicial")
    rb = L.resumen_bandas_av(df)
    if not rb.empty:
        st.dataframe(rb.round(1), hide_index=True)
        st.caption("Cuartiles de la propuesta: Q1 (0 a 30), Q2-Q3 (30 a 65) y Q4 (65 a 85 letras). Cada fila compara el valor general (media) con la "
                   "mediana y muestra el cambio frente al valor base (AV inicial). Use el filtro «Cuartil de AV inicial» de la barra lateral para "
                   "filtrar todo el tablero.")

    # ---- 1.3 dispersión de las variables numéricas (caja y bigotes + tabla de variación)
    st.markdown("##### Dispersión de las variables numéricas")
    st.caption("Cada caja muestra la mediana, el rango intercuartílico (Q1–Q3), los bigotes (1,5 × RIQ) y los atípicos; el rombo es la media. "
               "Responde a los mismos filtros que el resto del tablero.")
    grupo_cb = st.radio("Revisión por", ["Agudeza visual", "OCT", "Utilización y proceso", "Calidad de vida", "Costos"], horizontal=True, key="cb-grupo")
    omitidas = []
    if grupo_cb == "Agudeza visual":
        omitidas += panel_cb(df, {"AV_letras_inicial": "AV inicial"}, "AV inicial (letras ETDRS)", "cb-av0", "AV (letras)", 300)
        omitidas += panel_cb(df, {f"dif_lts_sem{x}": f"Δ AV S{x}" for x in (16, 52, 104)}, "Δ AV vs. AV inicial (letras)", "cb-dav", "Δ AV (letras)")
    elif grupo_cb == "OCT":
        omitidas += panel_cb(df, {"OCT_inicial": "OCT inicial"}, "OCT inicial (CMT, µm)", "cb-oct0", "µm", 300)
        omitidas += panel_cb(df, {f"dif_micras_sem{x}": f"Δ OCT S{x}" for x in (16, 52, 104)}, "Δ OCT vs. OCT inicial (µm)", "cb-doct", "Δ OCT (µm)")
    elif grupo_cb == "Calidad de vida":
        Ec = MART[MART["ecv1"].notna() & MART["ecv2"].notna()].drop_duplicates("numero_doc")
        omitidas += panel_cb(Ec, {"ecv1": L.N_ECV1, "ecv2": L.N_ECV2}, "Puntaje total de calidad de vida (pacientes con ambas encuestas)", "cb-ecv", "Puntaje (0–100)")
        omitidas += panel_cb(Ec, {"delta_ecv": "Diferencia (2 − 1)"}, "Diferencia del puntaje total (puntos)", "cb-decv", "Puntos", 300)
    elif grupo_cb == "Costos":
        omitidas += panel_cb(df, {"costofin_anio1": "Costo Año 1", "costofin_anio2": "Costo Año 2"}, f"Costo promedio por paciente-ojo reingreso{TAG_DUMMY}", "cb-costo", "$ (COP)")
    else:
        omitidas += panel_cb(df, {"apl_anio1": "Inyecciones Año 1", "apl_anio2": "Inyecciones Año 2"}, "Número de inyecciones", "cb-iny", "Inyecciones", 300)
        omitidas += panel_cb(df, {"extension_ultima_dosis": L.N_EXT}, f"{L.N_EXT} (semanas)", "cb-ext", "Semanas", 300)
        omitidas += panel_cb(df, {"Oportunidad_inicio_tto": "Oportunidad de inicio"}, "Oportunidad de inicio del tratamiento (días)", "cb-oport", "Días", 300)
    if omitidas:
        st.caption("Sin datos suficientes en este insumo (menos de 5): " + ", ".join(omitidas) + ".")

# ---------------------------------------------------------------- 2. Cohortes
with t2:
    encabezado(2, "Cohortes", "¿Cómo evolucionan nuestros pacientes?  Diagnóstico y medicamento como filtros principales")
    a, b, c3 = st.columns([3, 1, 1])
    por = a.radio("Cohorte por", ["Diagnóstico", "Medicamento", "Diagnóstico × medicamento", "Año de inicio"], horizontal=True)
    sem2 = b.radio("Semana del resultado", [52, 104], index=1, horizontal=True, format_func=lambda s: f"S{s}")
    n_min = c3.slider("n mínimo por cohorte", 1, 50, 10, help="Oculta cohortes pequeñas para no sobreinterpretar.")
    res = L.resumen_cohortes(df, por, n_min)
    d2 = L.con_cohorte(df, por)
    d2 = d2[d2["cohorte"].isin(res["cohorte"])]
    if res.empty:
        st.info("Ninguna cohorte alcanza el n mínimo con los filtros actuales.")
    else:
        g1, g2 = st.columns(2)
        with g1:
            violines(d2, {f"dif_lts_sem{sem2}": f"Δ AV S{sem2}"}, f"Distribución de Δ AV S{sem2} por cohorte", f"vio-av-{sem2}", "Δ AV (letras)")
        with g2:
            barras_cohorte(res, {"dav16": "S16", "dav52": "S52", "dav104": "S104"}, "Δ AV promedio por cohorte (letras)", ".1f", "Δ AV (letras)", vertical=True)
        COSTOS_OPC = {"Año 1 (sem 52)": ("anio1", "Costo Año 1 (sem 52)"), "Año 2 (sem 52–104)": ("anio2", "Costo Año 2 (sem 52–104)"),
                      "Suma total (Año 1 + Año 2)": ("total", "Costo total (Año 1 + Año 2)")}
        modo_c = st.radio("Costo", list(COSTOS_OPC), horizontal=True, key="costo2")
        _dispersion(d2, sem2, COSTOS_OPC[modo_c][0], COSTOS_OPC[modo_c][1], f"disp-coh-{sem2}-{COSTOS_OPC[modo_c][0]}", 400)
        g1, g2, g3 = st.columns(3)
        with g1:
            barras_cohorte(res, {"respondedor": "% respondedores"}, "% respondedores por cohorte", ".1f", "%", ok=SECA_OK, alto=290)
        with g2:
            barras_cohorte(res, {"seca52": "S52", "seca104": "S104"}, f"% {L.N_SECA} por cohorte", ".1f", "%", ok=SECA_OK, alto=290)
        with g3:
            barras_cohorte(res, {"iny1": "Año 1 (≤ S52)", "iny2": "Año 2 (S52–S104)"}, "Inyecciones promedio por cohorte", ".1f", alto=290)
        barras_cohorte(res, {"costo1": "Año 1", "costo2": "Año 2"}, f"Costo promedio por paciente-ojo reingreso{TAG_DUMMY}", ",.0f", "$")
        tabla = res.rename(columns={"cohorte": "Cohorte", "dav16": "Δ AV S16", "dav52": "Δ AV S52", "dav104": "Δ AV S104",
                                    "respondedor": "% respond.", "seca52": f"% {L.N_SECA} S52", "seca104": f"% {L.N_SECA} S104",
                                    "iny1": "Iny. A1", "iny2": "Iny. A2", "costo1": "Costo A1", "costo2": "Costo A2"})
        with st.expander("Ver tabla de cohortes"):
            st.dataframe(tabla.round(1), hide_index=True)

# ---------------------------------------------------------------- 3. Gestión
with t3:
    encabezado(3, "Gestión de la atención", "Proceso asistencial que puede explicar diferencias de resultado")
    st.markdown("**Pregunta de gestión:** ¿en qué etapa del proceso se concentra la variabilidad y qué relación tiene con el resultado visual?")
    n_oport, n_carga = K["oportuno"][1], K["carga"][1]
    etapas = [
        ("01", "OPORTUNIDAD", "Inicio de tratamiento", L.f_pct(K["oportuno"][0]), color_sem(K["oportuno"][0]), True, n_oport),
        ("02", "ADHERENCIA A DOSIS DE CARGA", "Carga · dosis inicial", L.f_pct(K["carga"][0]), color_sem(K["carga"][0]), True, n_carga),
        ("03", "CUMPLIMIENTO DE APLICACIONES", "Año 1 · a tiempo", L.f_pct(K["cumpl1"][0]), color_sem(K["cumpl1"][0]), CUMPL_OK, K["cumpl1"][1]),
        ("04", "EXTENSIÓN ÚLTIMA DOSIS", "S52 / S104 · entre la penúltima y la última dosis", par(K["ext52"][0], K["ext104"][0], L.f_num) + " sem", GRIS, True, K["ext52"][1]),
        ("05", "ANATOMÍA SIN LÍQUIDO EN OCT", "S16", L.f_pct(K["seca16"][0]), color_sem(K["seca16"][0]), SECA_OK, K["seca16"][1]),
    ]
    html = '<div class="flujo">'
    for i, (num, tit, sub, val, col, ok, n) in enumerate(etapas):
        fondo = {VERDE: "#E8F5E1", AMBAR: "#FFF6D6", ROJO: "#FBE4E1"}.get(col, "#fff") if ok else "#fff"
        html += (f'<div class="etapa" style="border-top:6px solid {col if ok else GRIS};background:{fondo}" title="n = {n:,}">'
                 f'<div class="num">{num}</div><div class="tit">{tit}</div><div class="val">{val if ok else "N/E"}</div>'
                 f'<div class="sub">{sub}</div></div>')
        if i < len(etapas) - 1:
            html += '<div class="flecha">→</div>'
    st.markdown(html + "</div>", unsafe_allow_html=True)
    st.markdown(
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;font-size:.82rem;margin:-.4rem 0 .8rem 0">'
        f'<span style="background:#E8F5E1;border-left:5px solid {VERDE};padding:3px 10px;border-radius:4px"><b>Verde</b> · {L.UMBRAL_VERDE} % o más</span>'
        f'<span style="background:#FFF6D6;border-left:5px solid {AMBAR};padding:3px 10px;border-radius:4px"><b>Amarillo</b> · {L.UMBRAL_AMBAR} % a {L.UMBRAL_VERDE - 1} %</span>'
        f'<span style="background:#FBE4E1;border-left:5px solid {ROJO};padding:3px 10px;border-radius:4px"><b>Rojo</b> · menos de {L.UMBRAL_AMBAR} %</span>'
        f'<span style="background:#F1F3F6;border-left:5px solid {GRIS};padding:3px 10px;border-radius:4px"><b>Gris</b> · sin umbral definido o no evaluable (N/E)</span></div>',
        unsafe_allow_html=True)

    tabla = pd.DataFrame([
        ["Oportunidad", "Oportunidad inicio de tratamiento", "distribución / semáforo", f"{L.f_num(K['dias_inicio'][0])} d promedio · {L.f_pct(K['oportuno'][0])} oportuno"],
        [L.N_ADH, "Adherencia dosis carga", "% cumplimiento", L.f_pct(K["carga"][0])],
        [L.N_CUMPL, "Índice de cumplimiento", "barra Año 1 vs Año 2", "N/E" if not CUMPL_OK else par(K["cumpl1"][0], K["cumpl2"][0], L.f_pct)],
        [L.N_EXT, "Semanas entre la penúltima y la última dosis (S52 / S104)", "caja y bigotes (pestaña 1)", par(K["ext52"][0], K["ext104"][0], L.f_num) + " sem"],
        [L.N_ANAT, L.N_SECA, "% S52 y S104", "N/E" if not SECA_OK else par(K["seca52"][0], K["seca104"][0], L.f_pct)],
        ["Resultado", "Δ AV S16 / S52 / S104", "ver pestaña 1", " / ".join(L.f_num(K[f"dav{s}"][0], 1, True) for s in (16, 52, 104)) + " letras"],
    ], columns=["Etapa", "Variable principal", "Visual secundaria", "Valor actual"])
    st.dataframe(tabla, hide_index=True)

    st.markdown("##### Dónde profundizar")
    g1, g2 = st.columns(2)
    with g1:
        dias = df["Oportunidad_inicio_tto"].dropna().clip(-30, 180)
        fig = go.Figure(go.Histogram(x=dias, nbinsx=40, marker_color=CAT[0]))
        fig.add_vline(x=META.get("oportunidad_inicio_max_dias", 30), line_dash="dash", line_color=SEL, annotation_text="límite oportuno")
        base_layout(fig, "Oportunidad: días de diagnóstico a 1ª inyección", 300, xaxis=dict(title="días (recortado −30…180)"),
                    yaxis=dict(title="paciente-ojo reingreso"))
        st.plotly_chart(fig, use_container_width=True, key="gestion-hist")
    with g2:
        if CUMPL_OK:
            fig = go.Figure(go.Bar(x=["Año 1", "Año 2"], y=[K["cumpl1"][0], K["cumpl2"][0]], marker_color=[CAT[0], CAT[1]],
                                   text=[L.f_pct(K["cumpl1"][0]), L.f_pct(K["cumpl2"][0])], textposition="outside", cliponaxis=False))
            base_layout(fig, f"{L.N_CUMPL}: Año 1 vs Año 2", 300, yaxis=dict(title=f"% a tiempo (±{TOL_PROG} días)", range=[0, 110]))
            st.plotly_chart(fig, use_container_width=True, key="gestion-prog")
        else:
            st.markdown(f"**{L.N_CUMPL}: Año 1 vs Año 2**")
            st.markdown(f'<span class="nd">{NO_EVAL}</span>', unsafe_allow_html=True)
    if not SECA_OK:
        st.caption(f"{L.N_ANAT} ({L.N_SECA}, S52 y S104): no evaluable en este insumo.")
    # ---- inyecciones y extensión de las últimas dosis
    st.markdown("##### Inyecciones y extensión de las últimas dosis")
    k1, k2, k3 = st.columns(3)
    card(k1, "Inyecciones Año 1 (total)", f"{int(df['apl_anio1'].sum()):,}".replace(",", "."), int(df["apl_anio1"].notna().sum()),
         ayuda=f"Total de inyecciones hasta la semana 52. Promedio por paciente-ojo reingreso: {L.f_num(K['iny1'][0])}.")
    card(k2, "Inyecciones Año 2 (total)", f"{int(df['apl_anio2'].sum()):,}".replace(",", "."), int(df["apl_anio2"].notna().sum()),
         ayuda=f"Total de inyecciones entre la semana 52 y la 104. Promedio por paciente-ojo reingreso: {L.f_num(K['iny2'][0])}.")
    with k3:
        fig = go.Figure()
        for i_, (cc, nn) in enumerate((("extension_sem52", "S52"), ("extension_sem104", "S104"))):
            sv = df[cc].dropna()
            fig.add_trace(go.Histogram(x=sv, xbins=dict(start=0, end=60, size=2), name=f"{nn} (n={len(sv):,})", marker_color=CAT[i_], opacity=.7))
        base_layout(fig, "Extensión de las últimas dosis (semanas)", 260, barmode="overlay", showlegend=True,
                    xaxis=dict(title="semanas entre la penúltima y la última dosis"), yaxis=dict(title="paciente-ojo reingreso"))
        st.plotly_chart(fig, use_container_width=True, key="gestion-ext-dist")
    dosis = pd.DataFrame({"Año 1": df["apl_anio1"].dropna().astype(int).value_counts(), "Año 2": df["apl_anio2"].dropna().astype(int).value_counts()}).fillna(0).astype(int)
    dosis = dosis[(dosis["Año 1"] > 0) | (dosis["Año 2"] > 0)].sort_index()
    dosis.index.name = "Número de dosis aplicadas"
    st.markdown("**Paciente-ojo reingreso según el número de dosis aplicadas**")
    st.dataframe(dosis.reset_index(), hide_index=True, height=min(420, 38 * (len(dosis) + 1)))
    st.caption("Cuenta los paciente-ojo reingreso por la cantidad de dosis recibidas en el año 1 (hasta la semana 52) y en el año 2 (semana 52 a 104).")

    # ---- programación y extensión en detalle (reporte_aplicaciones_v4_501_2)
    st.markdown(f"##### {L.N_CUMPL} y extensión en detalle")
    st.caption("Misma lógica del reporte de aplicaciones: cumplimiento = fecha real de la dosis frente a la fecha programada en la dosis anterior; "
               "extensión = semanas entre dosis consecutivas.")
    if APL_TODAS is None:
        st.info("Esta corrida es anterior al detalle de programación y extensión: vuelva a procesar el insumo (sección Cargar insumo) para verlo.")
    else:
        apl = APL_TODAS[APL_TODAS["pacienteojoreingreso"].isin(df["pacienteojoreingreso"])]
        rp = L.resumen_programacion(apl, TOL_PROG)
        g1, g2 = st.columns(2)
        with g1:
            st.markdown(f"**{L.N_CUMPL}: fecha programada** (ventana ±{TOL_PROG} días)")
            if rp["n"] == 0:
                st.markdown(f'<span class="nd">{NO_EVAL}</span>', unsafe_allow_html=True)
            else:
                a, b, c = st.columns(3)
                a.metric(f"Dentro de ±{TOL_PROG} d", L.f_pct(rp["dentro"]), help=f"n = {rp['n']:,} aplicaciones con fecha programada previa")
                b.metric("Desvío promedio", f"{L.f_num(rp['promedio'])} d", help=f"Mediana {L.f_num(rp['mediana'])} d. Positivo = retraso.")
                c.metric("Retraso grave", L.f_pct(rp["grave"]), help=f"Más de {config.RETRASO_GRAVE_DIAS} días después de lo programado.")
                cl = apl[apl["Clasificacion_cumplimiento"] != "Sin dato"].groupby("Clasificacion_cumplimiento").size().sort_index()
                fig = go.Figure(go.Bar(y=cl.index[::-1], x=cl.values[::-1], orientation="h",
                                       marker_color=[L.COLOR_CLASE[k[0]] for k in cl.index[::-1]],
                                       text=[f"{v:,} ({v / cl.sum() * 100:.0f} %)" for v in cl.values[::-1]], textposition="outside", cliponaxis=False))
                base_layout(fig, f"{L.N_CUMPL}: clasificación (verde: dentro de la ventana · amarillo: fuera, no grave · rojo: retraso grave)", 300, xaxis=dict(range=[0, cl.max() * 1.35], title="aplicaciones"))
                st.plotly_chart(fig, use_container_width=True, key="prog-clases")
        with g2:
            if rp["n"] == 0:
                st.markdown(f"**{L.N_CUMPL}: distribución de días**")
                st.markdown(f'<span class="nd">{NO_EVAL}</span>', unsafe_allow_html=True)
            else:
                dias = apl["Oportunidad_aplicacion_dias"].dropna().clip(-30, 60)
                fig = go.Figure(go.Histogram(x=dias, xbins=dict(start=-30, end=61, size=2), marker_color=CAT[0]))
                fig.add_vrect(x0=-TOL_PROG, x1=TOL_PROG, fillcolor=VERDE, opacity=.12, line_width=0,
                              annotation_text=f"±{TOL_PROG} d", annotation_position="top left")
                base_layout(fig, "Días de desvío vs. fecha programada (recortado −30…60)", 300,
                            xaxis=dict(title="días (negativo = adelantado, positivo = retraso)"), yaxis=dict(title="aplicaciones"))
                st.plotly_chart(fig, use_container_width=True, key="prog-dias")
        e1, e2 = st.columns([2, 1])
        with e1:
            ext = apl[apl["con_dosis"] >= 2].copy()
            ext["dosis"] = ext["con_dosis"].clip(upper=9).astype(int).astype(str).replace("9", "9+")
            orden = [str(i) for i in range(2, 9)] + ["9+"]
            fig = go.Figure()
            hay_prog = apl["Semanas_Apl_a_Prog"].notna().any()
            for col, nom, color in (("Semanas_Entre_Dosis", "Real (entre dosis)", CAT[0]), ("Semanas_Apl_a_Prog", "Programada", CAT[1])):
                dd = ext[ext[col].notna() & (ext[col] >= 0)]
                if dd.empty:
                    continue
                fig.add_trace(go.Box(x=dd["dosis"], y=dd[col].clip(upper=52), name=nom, marker_color=color, boxpoints=False))
                med = dd.groupby("dosis")[col].median().reindex([o for o in orden if o in set(dd["dosis"])])
                fig.add_trace(go.Scatter(x=med.index, y=med.values, mode="text", text=[f"{v:.0f}" for v in med.values], textposition="top center",
                                         textfont=dict(size=10, color=color), showlegend=False, hoverinfo="skip", cliponaxis=False))
            base_layout(fig, "Extensión: semanas entre dosis, real vs. programada, por consecutivo de dosis", 320, boxmode="group",
                        showlegend=True, xaxis=dict(title="consecutivo de dosis"), yaxis=dict(title="semanas (tope 52)"))
            ejex_categorico(fig, [o for o in orden if o in set(ext["dosis"])])
            st.plotly_chart(fig, use_container_width=True, key="ext-cons")
        with e2:
            real, prog = apl["Semanas_Entre_Dosis"].dropna(), apl["Semanas_Apl_a_Prog"].dropna()
            st.metric("Intervalo real entre dosis (mediana)", f"{L.f_num(real.median(), 0)} sem" if len(real) else "—", help=f"n = {len(real):,}")
            st.metric("Intervalo programado (mediana)", f"{L.f_num(prog.median(), 0)} sem" if len(prog) else "N/E",
                      help="Semanas entre la aplicación y su fecha programada siguiente (n = " + f"{len(prog):,})" if len(prog) else NO_EVAL)
            if not hay_prog:
                st.caption("La extensión programada no es evaluable: el insumo no trae `fecha_programacion`.")

# ---------------------------------------------------------------- 4. Paciente-ojo
with t4:
    encabezado(4, "Paciente-ojo", "Selección de paciente-ojo reingreso para gestión individual")
    ids = df["pacienteojoreingreso"].tolist()
    actual = st.session_state["sel"]
    idx = ids.index(actual) if actual in ids else None
    elegido = st.selectbox("Paciente-ojo reingreso (o selecciónelo con un clic en el gráfico)", ids, index=idx, placeholder="Buscar…")
    if elegido and elegido != actual:
        st.session_state["sel"] = elegido
        st.rerun()
    buscar = st.text_input("Buscar por ID del paciente (documento)", key="buscar_doc", placeholder="Ej.: 657212")
    if buscar.strip():
        doc_txt = MART["numero_doc"].dropna().astype("int64").astype(str)
        enc = MART[doc_txt.reindex(MART.index).eq(buscar.strip())]
        if enc.empty:
            st.warning("No hay registros para ese ID con los datos cargados.")
        else:
            vista = enc[["pacienteojoreingreso", "ojo", "reingreso", "diagnostico", "medicamento_label"]].copy()
            vista["ojo"] = vista["ojo"].map({"OD": "Derecho (OD)", "OI": "Izquierdo (OI)"}).fillna(vista["ojo"])
            vista["reingreso"] = np.where(vista["reingreso"] > 0, "Reingreso " + vista["reingreso"].astype(int).astype(str), "Ingreso inicial")
            st.dataframe(vista.rename(columns={"pacienteojoreingreso": "Paciente-ojo reingreso", "ojo": "Ojo", "reingreso": "Ingreso / reingreso",
                                               "diagnostico": "Diagnóstico", "medicamento_label": "Medicamento"}), hide_index=True)
            opciones = enc["pacienteojoreingreso"].tolist()
            pick = st.radio("Ver la ficha de", opciones, horizontal=True, key="pick_doc")
            if pick != st.session_state["sel"]:
                st.session_state["sel"] = pick
                st.rerun()
    izq, der = st.columns([2, 1])
    with izq:
        espagueti("spag4")
    with der:
        if st.session_state["sel"] is not None:
            with st.container(border=True):
                ficha_panel(MART[MART["pacienteojoreingreso"] == st.session_state["sel"]].iloc[0])
        else:
            st.info("Seleccione un paciente-ojo reingreso (clic en el gráfico o búsqueda) para ver su ficha.")
    if st.session_state["sel"] is not None:
        trayectoria_paciente(MART[MART["pacienteojoreingreso"] == st.session_state["sel"]].iloc[0], "paciente")

# ---------------------------------------------------------------- 5. Valor
with t_valor:
    encabezado(6, "Valor: resultados + utilización + costos", "¿Qué resultados obtenemos con los recursos utilizados?")
    sem5 = st.radio("Semana del resultado", [52, 104], index=1, horizontal=True, format_func=lambda s: f"S{s}", key="sem5")
    por5 = st.radio("Comparar por", ["Diagnóstico", "Medicamento", "Diagnóstico × medicamento"], horizontal=True, key="por5")
    d5 = L.con_cohorte(df, por5)
    ok_coh = d5["cohorte"].value_counts()
    d5 = d5[d5["cohorte"].isin(ok_coh[ok_coh >= 5].index)]
    izq, der = st.columns([3, 2])
    with izq:
        if d5.empty:
            st.info("Sin cohortes con al menos 5 paciente-ojo reingreso.")
        else:
            for modo_v, nom_v in (("anio1", "Costo Año 1 (sem 52)"), ("anio2", "Costo Año 2 (sem 52–104)"), ("total", "Costo total (Año 1 + Año 2)")):
                _dispersion(d5, 104, modo_v, nom_v, f"valor-disp-{modo_v}", 300)
            st.caption("Los tres costos se cruzan siempre con el resultado de agudeza visual a la semana 104.")
    with der:
        with st.container(border=True):
            st.markdown("**DIMENSIONES DE VALOR**")
            st.markdown("**Resultados**")
            a, b, c = st.columns(3)
            a.metric(f"Δ AV S{sem5}", L.f_num(K[f"dav{sem5}"][0], 1, True), help=f"n = {K[f'dav{sem5}'][1]}")
            b.metric(f"{L.N_SECA} S{sem5}", L.f_pct(K[f"seca{sem5}"][0]) if SECA_OK else "N/E")
            c.metric("Δ ECV", L.f_num(K["delta_ecv"][0], 1, True), help=f"n = {K['delta_ecv'][1]} pacientes")
            st.markdown("**Utilización** (Año 1 → Año 2)")
            a, b = st.columns(2)
            a.metric("Inyecciones", f"{L.f_num(K['iny1'][0])} → {L.f_num(K['iny2'][0])}")
            b.metric("Moléculas distintas", f"{L.f_num(K['mol1'][0], 2)} → {L.f_num(K['mol2'][0], 2)}")
            a, b = st.columns(2)
            a.metric("Consultas retina", f"{L.f_num(K['consret1'][0])} → {L.f_num(K['consret2'][0])}")
            b.metric("Consultas oftalmología", f"{L.f_num(K['consoft1'][0])} → {L.f_num(K['consoft2'][0])}")
            st.metric("OCT", f"{L.f_num(K['oct1'][0])} → {L.f_num(K['oct2'][0])}")
            st.markdown(f"**Costos{TAG_DUMMY}**")
            a, b = st.columns(2)
            a.metric("Año 1", L.f_money(K["costo1"][0]), help=f"n = {K['costo1'][1]}")
            b.metric("Año 2", L.f_money(K["costo2"][0]), delta=delta(K["costo1"][0], K["costo2"][0], 0), delta_color="inverse", help=f"n = {K['costo2'][1]}")
    if not d5.empty:
        g1, g2 = st.columns(2)
        with g1:
            violines(d5, {"costofin_anio1": "Año 1", "costofin_anio2": "Año 2"}, f"Distribución del costo por cohorte{TAG_DUMMY}", "valor-vio-costo", "$", minimo=3)
        with g2:
            violines(d5, {"apl_anio1": "Año 1", "apl_anio2": "Año 2"}, "Distribución de inyecciones por cohorte", "valor-vio-iny", "N", minimo=3)
    st.markdown("##### Distribución de recursos por diagnóstico")
    r1, r2, r3 = st.columns(3)
    for col_, (v1, v2, tit_, k_) in zip((r1, r2, r3), (("Cons_Retina_NAnio1", "Cons_Retina_NAnio2", "Consultas de retina", "cb-cretina"),
                                                       ("Cons_Oftalmo_NAnio1", "Cons_Oftalmo_NAnio2", "Consultas de oftalmología", "cb-coft"),
                                                       ("TipoAyuda_OCT_NAnio1", "TipoAyuda_OCT_NAnio2", "Cantidad de OCT", "cb-coct"))):
        with col_:
            fig = go.Figure()
            for i_, (cc, nn) in enumerate(((v1, "Año 1"), (v2, "Año 2"))):
                dd_ = df[df[cc].notna()]
                fig.add_trace(go.Box(x=dd_["diagnostico"], y=dd_[cc], name=nn, boxpoints="outliers", boxmean=True, marker=dict(color=CAT[i_], size=4, opacity=.6),
                                     line=dict(color=CAT[i_]), fillcolor=rgba(CAT[i_], .3)))
            base_layout(fig, tit_, 320, boxmode="group", showlegend=True, yaxis=dict(title="Cantidad"))
            ejex_categorico(fig, sorted(df["diagnostico"].dropna().unique()))
            st.plotly_chart(fig, use_container_width=True, key=k_)
    st.caption("El costo no debe interpretarse aislado del resultado: compare siempre contra Δ AV y ECV.")

# ---------------------------------------------------------------- 5. Calidad de vida
with t_cv:
    st.markdown('<div class="nivel" style="--c:#7A4FB0"><h3>5. Calidad de vida (NEI VFQ-25)</h3>'
                '<p>¿El cambio clínico se traduce en un resultado que importa al paciente?</p></div>', unsafe_allow_html=True)
    # Universo propio de esta pestaña: SOLO pacientes con las dos encuestas. No usa los filtros de diagnóstico,
    # medicamento ni cuartiles, y el promedio de la encuesta 1 excluye a quien no tiene la encuesta 2.
    E = MART[MART["ecv1"].notna() & MART["ecv2"].notna()]
    perfil = L.ecv_perfil(E)
    tot = perfil[perfil["clave"] == "Total"].iloc[0] if not perfil.empty else None
    if tot is None or tot["n_par"] == 0:
        st.markdown(f'<span class="nd">{NO_EVAL} Cargue el resultado de calidad de vida del prestador en "Cargar insumo".</span>', unsafe_allow_html=True)
    else:
        n_pac = int(E["numero_doc"].nunique())
        st.caption(f"Universo: **{n_pac:,}** pacientes que contestaron las dos encuestas. Esta pestaña no usa los filtros de diagnóstico, "
                   "medicamento ni cuartiles; el promedio de la encuesta 1 excluye a quienes no tienen la encuesta 2.".replace(",", "."))
        c = st.columns(4)
        card(c[0], f"Puntaje total · {L.N_ECV1}", L.f_num(tot["par1"], 1), n_pac, ayuda="Promedio solo de los pacientes que también contestaron la encuesta 2.")
        card(c[1], f"Puntaje total · {L.N_ECV2}", L.f_num(tot["par2"], 1), n_pac)
        card(c[2], "Diferencia (encuesta 2 − encuesta 1)", L.f_num(tot["delta"], 1, True), n_pac)
        card(c[3], "Pacientes que mejoran", L.f_pct(tot["pct_mejora5"]), n_pac,
             ayuda="Porcentaje con una diferencia mayor a 5 puntos.")
        st.caption("Escala 0–100 (mayor = mejor). Diferencia > 5 puntos = evolución favorable. Meta puntaje total: > 70.")

        dim = perfil.copy()
        fav, meta = config.ECV_DELTA_FAVORABLE, config.ECV_META_TOTAL

        def celda_delta(x):
            if pd.isna(x):
                return "<td>—</td>"
            col = "#0A7A5A" if x > fav else ("#C0392B" if round(x) < 0 else "#555")
            return f'<td style="color:{col};font-weight:700">{(0 if round(x) == 0 else x):+.0f}</td>'
        filas = ""
        for _, r in pd.concat([dim[dim["clave"] != "Total"], dim[dim["clave"] == "Total"]]).iterrows():
            es_t = r["clave"] == "Total"
            filas += (f'<tr style="{"font-weight:700;background:#E6EEF4" if es_t else ""}"><td style="text-align:left">{r["dimension"]}</td>'
                      f'<td>{r["par1"]:.0f}</td><td>{r["par2"]:.0f}</td>{celda_delta(r["delta"])}</tr>')
        st.markdown(
            '<style>.tev{width:100%;border-collapse:collapse;font-size:.88rem}.tev th{background:#0F1F3D;color:#fff;padding:6px 8px;text-align:center}'
            '.tev td{padding:5px 8px;text-align:center;border-bottom:1px solid #E5E9F0}</style>'
            f'<table class="tev"><tr><th style="text-align:left">Dimensión</th><th>{L.N_ECV1}</th><th>{L.N_ECV2}</th><th>Δ</th></tr>'
            + filas + '</table>', unsafe_allow_html=True)
        st.caption(f"Δ > {fav:.0f} puntos = evolución favorable (verde). Meta del puntaje total: > {meta:.0f}. Solo pacientes con las dos encuestas.")

        g1, g2 = st.columns([3, 2])
        with g1:
            fig = go.Figure()
            for nom, col, color in ((L.N_ECV1, "par1", CAT[0]), (L.N_ECV2, "par2", CAT[1])):
                fig.add_trace(go.Bar(y=dim["dimension"], x=dim[col], name=nom, orientation="h", marker_color=color,
                                     text=dim[col].map(lambda t: "" if pd.isna(t) else f"{t:.1f}"), textposition="outside", cliponaxis=False,
                                     hovertemplate="%{y}<br>" + nom + ": %{x:.1f}<extra></extra>"))
            base_layout(fig, f"Puntaje por dimensión: {L.N_ECV1} vs {L.N_ECV2}", 60 * len(dim) + 60, barmode="group", showlegend=True,
                        xaxis=dict(title="Puntaje promedio (0–100)", range=[0, 112]),
                        yaxis=dict(autorange="reversed", tickmode="array", tickvals=list(dim["dimension"]), ticktext=list(dim["dimension"])))
            st.plotly_chart(fig, use_container_width=True, key="ecv-dims")
        with g2:
            d2 = dim[dim["clave"] != "Total"]
            colores = [VERDE if x > 0 else ROJO for x in d2["delta"].fillna(0)]
            fig = go.Figure(go.Bar(y=d2["dimension"], x=d2["delta"], orientation="h", marker_color=colores, name="Diferencia (puntos)",
                                   text=d2["delta"].map(lambda t: "" if pd.isna(t) else f"{t:+.1f}"), textposition="outside", cliponaxis=False,
                                   customdata=d2["n_par"], hovertemplate="%{y}<br>Diferencia: %{x:+.1f}<br>n = %{customdata}<extra></extra>"))
            rg = rango_con_holgura(d2["delta"].dropna(), 0.3)
            base_layout(fig, "Dónde cambia más la calidad de vida (puntos)", 60 * len(d2) + 60, showlegend=True,
                        xaxis=dict(title="Encuesta 2 − encuesta 1", **({"range": rg} if rg else {})),
                        yaxis=dict(autorange="reversed", tickmode="array", tickvals=list(d2["dimension"]),
                                   ticktext=[f"{a} (n={n})" for a, n in zip(d2["dimension"], d2["n_par"])]))
            fig.add_vline(x=0, line_color="#555", line_width=1)
            st.plotly_chart(fig, use_container_width=True, key="ecv-delta")
        st.caption("Dimensiones agrupadas en la propuesta: percepción de la visión (general, cercana, lejana, periférica, color), "
                   "funcionamiento (función social, rol, dependencia, conducción) y bienestar (bienestar y sufrimiento, dolor ocular). "
                   "Conducción solo la responde quien conduce: su n es menor.")

        pac = E.drop_duplicates("numero_doc")
        ojo = E.groupby("numero_doc").agg(dav=("dif_lts_sem52", "mean"), delta=("delta_ecv", "first")).dropna()
        h1, h2 = st.columns(2)
        with h1:
            fig = go.Figure(go.Histogram(x=pac["delta_ecv"], xbins=dict(size=2.5), marker_color=CAT[3], name="Pacientes",
                                         hovertemplate="Diferencia %{x}<br>%{y} pacientes<extra></extra>"))
            fig.add_vline(x=0, line_color="#555", line_dash="dash")
            base_layout(fig, "Distribución de la diferencia del puntaje total", 340, showlegend=True,
                        xaxis=dict(title="Encuesta 2 − encuesta 1 (puntos)"), yaxis=dict(title="Pacientes"))
            st.plotly_chart(fig, use_container_width=True, key="ecv-hist")
        with h2:
            if len(ojo) >= 5:
                umbral = L.UMBRAL_MEJORA_LETRAS
                ojo["lectura"] = np.where((ojo["dav"] >= umbral) & (ojo["delta"] > 0), "Alineado: AV y calidad de vida mejoran",
                                  np.where((ojo["dav"] >= umbral) & (ojo["delta"] <= 0), "Alerta: AV mejora y calidad de vida no",
                                  np.where(ojo["delta"] > 0, "Calidad de vida mejora sin mejora clara de AV", "Sin mejora en ninguno")))
                colmap = {"Alineado: AV y calidad de vida mejoran": VERDE, "Alerta: AV mejora y calidad de vida no": ROJO,
                          "Calidad de vida mejora sin mejora clara de AV": CAT[0], "Sin mejora en ninguno": GRIS}
                fig = go.Figure()
                for nom, g in ojo.groupby("lectura"):
                    fig.add_trace(go.Scatter(x=g["delta"], y=g["dav"], mode="markers", name=f"{nom} ({len(g)})",
                                             marker=dict(size=8, color=rgba(colmap[nom], .7), line=dict(width=1, color="#fff")),
                                             hovertemplate="Δ AV S52: %{y:+.0f} letras<br>Diferencia ECV: %{x:+.1f}<extra></extra>"))
                fig.add_hline(y=umbral, line_dash="dash", line_color="#1F77B4")
                fig.add_vline(x=0, line_dash="dash", line_color="#555")
                base_layout(fig, "Resultado visual vs calidad de vida (por paciente)", 340, showlegend=True,
                            xaxis=dict(title="Diferencia en calidad de vida (puntos)"), yaxis=dict(title="Δ AV S52 promedio de sus ojos (letras)"))
                st.plotly_chart(fig, use_container_width=True, key="ecv-disp")
            else:
                st.markdown('<span class="nd">Sin pacientes con Δ AV a S52 y las dos encuestas.</span>', unsafe_allow_html=True)

        st.markdown("**Seguimiento entre la encuesta 1 y la encuesta 2**")
        seg_t = dim.rename(columns={"dimension": "Dimensión", "n_par": "Total (con ambas)", "par1": f"Promedio {L.N_ECV1}", "med1": f"Mediana {L.N_ECV1}",
                                    "par2": f"Promedio {L.N_ECV2}", "med2": f"Mediana {L.N_ECV2}", "delta": "Diferencia (2 − 1)", "n_mejora5": "n dif. > 5",
                                    "pct_mejora5": "% dif. > 5", "n_ecv2_70": "n encuesta 2 > 70", "pct_ecv2_70": "% encuesta 2 > 70",
                                    "sem_entre": "Semanas entre encuestas"})
        cols_seg = ["Dimensión", "Total (con ambas)", f"Promedio {L.N_ECV1}", f"Mediana {L.N_ECV1}", f"Promedio {L.N_ECV2}", f"Mediana {L.N_ECV2}",
                    "Diferencia (2 − 1)", "n dif. > 5", "% dif. > 5", "n encuesta 2 > 70", "% encuesta 2 > 70", "Semanas entre encuestas"]
        st.dataframe(seg_t[cols_seg].round(1), hide_index=True)
        st.caption("Diferencias en puntos de la escala 0–100 (dif. > 5 = evolución favorable; meta encuesta 2 > 70).")

        # ---- paciente específico (del universo con las dos encuestas)
        st.markdown("##### Paciente específico")
        ids_e = sorted(E["numero_doc"].dropna().astype("int64").unique().tolist())
        doc = st.selectbox("Paciente (ID)", ids_e, index=None, placeholder="Buscar por ID…", key="ecv-doc")
        if doc is not None:
            reg = E[E["numero_doc"] == doc].copy()
            reg["Reingreso"] = np.where(reg["reingreso"] > 0, "Sí (reingreso " + reg["reingreso"].astype(int).astype(str) + ")", "No (ingreso inicial)")
            st.dataframe(reg[["numero_doc", "diagnostico", "ojo", "Reingreso", "medicamento_label"]].rename(columns={
                "numero_doc": "ID", "diagnostico": "Diagnóstico", "ojo": "Ojo", "medicamento_label": "Medicamento"}), hide_index=True)
            fila = E[E["numero_doc"] == doc].iloc[0]
            pd_ = pd.DataFrame([{"Dimensión": "Total", L.N_ECV1: fila["ecv1"], L.N_ECV2: fila["ecv2"], "Diferencia": fila["delta_ecv"]}] + [
                {"Dimensión": et, L.N_ECV1: fila.get(f"ecvd_{k}_1"), L.N_ECV2: fila.get(f"ecvd_{k}_2"),
                 "Diferencia": (fila.get(f"ecvd_{k}_2") - fila.get(f"ecvd_{k}_1")) if pd.notna(fila.get(f"ecvd_{k}_1")) and pd.notna(fila.get(f"ecvd_{k}_2")) else np.nan}
                for k, et, _ in config.ECV_DIMENSIONES])
            st.dataframe(pd_.round(1), hide_index=True)
