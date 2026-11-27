"""Piezas compartidas por todas las páginas: estilos, «última actualización», fechas, pie de página, la elección de la
corrida de datos, los filtros comunes (diagnóstico, medicamento, sede, EAPB) y el formato base de los gráficos."""
from __future__ import annotations

import textwrap
from decimal import ROUND_HALF_UP, Decimal
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

import logic as L
from pipeline import registro, seguridad

# El enrutador (app.py) deja aquí las páginas para que una página pueda llevar a otra con st.switch_page
PAGINAS: Dict[str, "st.Page"] = {}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

ESTILOS = """<style>
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
    .periodo {background:#F1F5FB; border:1px solid #D9E2F0; border-radius:8px; padding:8px 14px; margin:0 0 .8rem 0; color:#1B2430; font-size:.92rem;}
    .periodo span {color:#5B6675; font-size:.85rem;}
    .flujo {display:flex; align-items:stretch; gap:6px; margin:.4rem 0 1rem 0;}
    .etapa {flex:1; background:#fff; border:1px solid #E3E7ED; border-radius:12px; padding:10px 12px; text-align:center;}
    .etapa .num {color:#8A94A3; font-size:.75rem;} .etapa .tit {font-weight:700; letter-spacing:.04em; font-size:.8rem; color:#1B2430;}
    .etapa .val {font-size:1.45rem; font-weight:800; color:#1B2430; margin:.2rem 0;} .etapa .sub {color:#5B6675; font-size:.78rem;}
    .etapa .meta {color:#5B6675; font-size:.72rem; font-style:italic; margin-top:.25rem;}
    .flecha {align-self:center; color:#8A94A3; font-size:1.3rem;}
    </style>"""


def estilos() -> None:
    st.markdown(ESTILOS, unsafe_allow_html=True)


def fecha(iso: Optional[str], hora: bool = True) -> str:
    """'2026-10-27T21:28:19' -> '27-oct-2026 21:28'."""
    try:
        d = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return "—"
    return f"{d.day:02d}-{MESES[d.month - 1]}-{d.year}" + (f" {d:%H:%M}" if hora else "")


def ultima_actualizacion(corridas: Optional[List[Dict]] = None) -> Optional[Dict]:
    """La actualización de datos más reciente: la última ejecución exitosa de la bitácora o, si no hay bitácora
    (corridas anteriores a ella), la corrida generada más recientemente."""
    corridas = L.listar_corridas() if corridas is None else corridas
    candidatos = [{"cuando": c["generado"], "prestador": str(c["meta"].get("prestador", "")).upper(), "version": c["meta"].get("version"),
                   "por": c["meta"].get("cargado_por")} for c in corridas if c.get("generado")]
    candidatos += [{"cuando": r.get("fin") or r.get("inicio"), "prestador": str(r.get("prestador") or "").upper(), "version": r.get("version"),
                    "por": r.get("usuario")} for r in registro.leer() if r.get("estado") == "éxito"]
    return max(candidatos, key=lambda c: str(c["cuando"])) if candidatos else None


def aviso_actualizacion() -> None:
    """Va en la barra lateral de todas las páginas."""
    u = ultima_actualizacion()
    if u is None:
        st.sidebar.caption("Sin datos procesados todavía.")
        return
    detalle = " · ".join(x for x in (u["prestador"], f"v{u['version']}" if u.get("version") else "", u.get("por") or "") if x)
    st.sidebar.caption(f"Última actualización de datos: **{fecha(u['cuando'])}**" + (f"  \n{detalle}" if detalle else ""))


def pie() -> None:
    st.markdown('<div style="margin-top:2.5rem;padding-top:.8rem;border-top:1px solid #DDE2E8;text-align:center;color:#5B6675;font-size:.85rem">'
                'Proyecto Valor en Salud</div>', unsafe_allow_html=True)


# ============================================================================ paleta y formato de gráficos
CAT = ["#1F5FBF", "#D26E00", "#0A8FA3", "#7A4FB0", "#4C9A2A", "#8A5A44", "#C2185B"]   # paleta categórica validada
GRIS = "#8A94A3"


def rgba(hexc: str, a: float) -> str:
    h = hexc.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


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


# ============================================================================ corrida de datos
@st.cache_data(show_spinner="Cargando datos…")
def _datos(ruta: str, marca: float, llave: bytes | None = None):
    """`marca` = fecha de modificación de los resultados: si se vuelve a correr el proceso, la caché se renueva sola."""
    return L.cargar(Path(ruta), llave)


def pantalla_clave() -> None:
    """Datos protegidos: se pide la clave una vez por sesión; la llave derivada queda solo en memoria."""
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


def elegir_corrida() -> Tuple[Dict, pd.DataFrame, Dict, Optional[bytes]]:
    """Selector «Corrida de datos» de la barra lateral (el mismo en todas las páginas: la elección se recuerda) y carga
    de la tabla del tablero. Devuelve (corrida, mart, metadata, llave); detiene la página si no hay datos o falta la clave."""
    corridas = L.listar_corridas()
    if not corridas:
        st.title("Valor en Salud · Retina")
        st.info("Todavía no hay datos procesados. Vaya a **Pipeline de datos** (barra lateral) y suba el libro del formulario.")
        st.stop()
    cifradas = {str(c["ruta"]) for c in corridas if seguridad.carpeta_cifrada(c["ruta"])}
    etiquetas = [(c["etiqueta"] + (" 🔒" if str(c["ruta"]) in cifradas else "")) if [x["etiqueta"] for x in corridas].count(c["etiqueta"]) == 1
                 else f'{c["etiqueta"]} ({i + 1})' for i, c in enumerate(corridas)]
    pos = next((i for i, c in enumerate(corridas) if str(c["ruta"]) == st.session_state.get("corrida_ruta")), 0)
    i = etiquetas.index(st.sidebar.selectbox("Corrida de datos", etiquetas, index=pos,
                                             help="Cada carga queda guardada con su prestador y versión; elija cuál ver (por defecto, la más reciente)."))
    corrida = corridas[i]
    st.session_state["corrida_ruta"] = str(corrida["ruta"])
    llave = st.session_state.get("llave_datos") or (seguridad.llave_de_entorno() if seguridad.hay_cifrado() else None)
    if str(corrida["ruta"]) in cifradas and llave is None:
        pantalla_clave()
        st.stop()
    try:
        mart, meta = _datos(str(corrida["ruta"]), (corrida["ruta"] / "metadata.json").stat().st_mtime, llave)
    except (FileNotFoundError, OSError, ValueError) as e:
        st.error(f"No se pudo leer la corrida seleccionada: {e}")
        st.stop()
    return corrida, mart, meta, llave


# ============================================================================ filtros comunes
# Mismas claves en todas las páginas: lo que se elige en el Tablero sigue elegido en Análisis de adherencia y viceversa.
FILTROS = ("f-dx", "f-med", "f-sede", "f-eapb")


def conservar_filtros() -> None:
    """Streamlit borra el valor de un widget cuando la página que se muestra no lo dibuja; reasignarlo en cada
    ejecución (lo llama app.py antes de abrir la página) lo conserva al pasar de una página a otra."""
    for k in FILTROS:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]


def _multiselect(etiqueta: str, opciones: List[str], clave: str, por_defecto: List[str]) -> List[str]:
    """Multiselect de la barra lateral cuyo valor guardado se limpia si la corrida nueva no trae alguna opción."""
    if clave in st.session_state:
        st.session_state[clave] = [o for o in st.session_state[clave] if o in opciones]
        return st.sidebar.multiselect(etiqueta, opciones, key=clave)
    return st.sidebar.multiselect(etiqueta, opciones, default=por_defecto, key=clave)


def filtros_comunes(mart: pd.DataFrame) -> pd.Series:
    """Diagnóstico, medicamento, sede y EAPB en la barra lateral. Devuelve la máscara de filas que cumplen."""
    dx_all = mart["diagnostico"].value_counts().index.tolist()
    dx_def = [d for d in ("DMREn", "EMD") if d in dx_all]
    if len(dx_def) < 2:   # p. ej. un prestador escribe "DMREh": no esconder datos por defecto; se parte de todos los diagnósticos
        dx_def = dx_all
    mascara = mart["diagnostico"].isin(_multiselect("Diagnóstico", dx_all, "f-dx", dx_def))
    med_all = sorted(mart["medicamento_label"].unique())
    mascara &= mart["medicamento_label"].isin(_multiselect("Medicamento", med_all, "f-med", med_all))
    # Sede y EAPB vienen de la hoja de pacientes; una corrida que no las trae no muestra el filtro
    for col, nombre in (("sede", "Sede"), ("eapb", "EAPB")):
        if col in mart and L.con_dato(mart[col]).any():
            valores = mart[col].where(L.con_dato(mart[col]), "Sin dato").astype(str)
            todas = sorted(valores.unique())
            mascara &= valores.isin(_multiselect(nombre, todas, f"f-{col}", todas))
    return mascara


# ============================================================================ números y tablas con formato del PBI
TINTA = "#1B2430"


def miles(x) -> str:
    return f"{int(x):,}".replace(",", ".")


def dec(x, d=1) -> str:
    """Número con coma decimal, redondeado como el PBI (la mitad hacia arriba: 2,125 -> 2,13; Python daría 2,12)."""
    if pd.isna(x):
        return "—"
    r = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return f"{r:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


TABLA_CSS = (f"<style>.tpbi{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums;color:{TINTA}}}"
             ".tpbi th,.tpbi td{padding:5px 10px;white-space:nowrap}.tpbi th{font-weight:600;text-align:left;vertical-align:bottom}"
             ".tpbi td.n{text-align:right}.tpbi tr.total td{font-weight:700;border-top:1px solid #9AA4B2}"
             ".tpbi tbody tr:nth-child(even) td{background:#F4F6F9}.tpbi td.sep,.tpbi th.sep{border-left:1px solid #9AA4B2}"
             ".tpbi thead tr:last-child th{border-bottom:1px solid #9AA4B2}.tpbi-wrap{overflow-x:auto;margin-bottom:.8rem}"
             ".tpbi.compacta{font-size:12.5px}.tpbi.compacta th,.tpbi.compacta td{padding:5px 6px}</style>")


def tabla_pbi(t: pd.DataFrame, grupos, medidas, titulo_filas: str, encabezado: str) -> str:
    """Tabla dinámica con grupos de columnas (como la matriz del PBI): fila 1 = grupos, fila 2 = medidas."""
    h1 = f"<tr><th>{encabezado}</th>" + "".join(f"<th colspan='{len(medidas)}' class='sep'>{etq}</th>" for _, etq in grupos) + "</tr>"
    h2 = f"<tr><th>{titulo_filas}</th>" + "".join(f"<th class='{'sep' if i == 0 else ''}' style='text-align:right'>{m[1]}</th>"
                                                   for _ in grupos for i, m in enumerate(medidas)) + "</tr>"
    filas = ""
    for fila in t.index:
        celdas = "".join(f"<td class='n{' sep' if i == 0 else ''}'>{'' if pd.isna(t.loc[fila, (g, m)]) else f(t.loc[fila, (g, m)])}</td>"
                         for g, _ in grupos for i, (m, _, f) in enumerate(medidas))
        filas += f"<tr class='{'total' if fila == 'Total' else ''}'><td>{fila}</td>{celdas}</tr>"
    return f"{TABLA_CSS}<div class='tpbi-wrap'><table class='tpbi'><thead>{h1}{h2}</thead><tbody>{filas}</tbody></table></div>"


def tabla_simple(t: pd.DataFrame, titulo_filas: str) -> str:
    """Tabla de conteos (filas × columnas) con fila y columna Total; las celdas en cero quedan vacías, como en el PBI."""
    h = f"<tr><th>{titulo_filas}</th>" + "".join(f"<th style='text-align:right'>{c}</th>" for c in t.columns) + "</tr>"
    filas = ""
    for fila in t.index:
        celdas = "".join(f"<td class='n'{' style=font-weight:700' if c == 'Total' else ''}>{miles(v) if v else ''}</td>" for c, v in t.loc[fila].items())
        filas += f"<tr class='{'total' if fila == 'Total' else ''}'><td>{fila}</td>{celdas}</tr>"
    return f"{TABLA_CSS}<div class='tpbi-wrap'><table class='tpbi compacta'><thead>{h}</thead><tbody>{filas}</tbody></table></div>"


# ============================================================================ datos de identificación
def identificacion_visible(meta: Dict, clave_widget: str = "ver-identificacion") -> bool:
    """Por defecto solo se ve el código paciente-ojo. La casilla «Mostrar nombres y documento» los muestra: en una corrida
    con datos sintéticos, sin más; con datos reales, solo con la clave VLM_PIN_IDENTIFICACION (sin clave configurada, no)."""
    from pipeline import config
    sintetico = bool(meta.get("sintetico") or meta.get("es_demo"))
    if not st.sidebar.checkbox("Mostrar nombres y documento", key=clave_widget,
                               help="Por defecto solo se muestra el código paciente-ojo reingreso."):
        return False
    if sintetico:
        st.sidebar.caption("Datos sintéticos: nombres de ejemplo, sin personas reales.")
        return True
    if not config.PIN_IDENTIFICACION:
        st.sidebar.warning("Para ver nombres y documentos con datos reales hay que configurar la clave VLM_PIN_IDENTIFICACION.")
        return False
    if st.session_state.get("_pin_id_ok"):
        return True
    pin = st.sidebar.text_input("Clave para ver identificación", type="password", key="pin-identificacion")
    if pin and pin == config.PIN_IDENTIFICACION:
        st.session_state["_pin_id_ok"] = True
        return True
    if pin:
        st.sidebar.error("Clave incorrecta.")
    return False
