"""Página «Seguimiento de aplicaciones»: une el Power BI «reporte_aplicaciones_v4» y el Excel «tablero_alertas_aplicaciones».

Pestañas:
  1 · Dosis aplicadas    (hoja 1 del PBI)
  2 · Dosis programadas  (hoja 2 del PBI + hoja «Programación» del Excel, con quién ya asistió)
  3 · Cumplimiento       (hoja 3 del PBI)
  4 · Alertas y gestión  (hojas «Cumplen» / «No cumplen» del Excel + registro de la gestión, que reemplaza «TablaGestion»)
  5 · Reporte de alertas (hoja «Reportes» del Excel)
  6 · Visor de pacientes (hoja «Visor de Pacientes» del PBI)
Los cálculos viven en logic_aplicaciones.py (pruebas en tests/test_aplicaciones.py) y la gestión en pipeline/gestion.py.
"""
from __future__ import annotations

import io
import textwrap
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import comun
import logic as L
import logic_aplicaciones as LA
from pipeline import gestion

CAT, GRIS = comun.CAT, comun.GRIS
TINTA, TINTA2 = "#1B2430", "#5B6675"
CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}
miles, dec = comun.miles, comun.dec
COLOR_CLASE = {"1. Muy adelantado": "#8E6CC0", "2. Adelantado": "#7FA9EC", "3. Exacto": "#4C9A2A", "4. Retraso leve": "#E0A100",
               "5. Retraso moderado": "#D26E00", "6. Retraso grave": "#C0392B"}
COLOR_ESTADO = {LA.EN_RANGO: "#4C9A2A", LA.RETRASO: "#C0392B", LA.FUTURA: "#1F5FBF", LA.SIN_FECHA: GRIS}
PESTANAS = {
    "1 · Dosis aplicadas": "¿Cuántas inyecciones se aplicaron en el período?",
    "2 · Dosis programadas": "¿Cuántas citas se programaron y quién no ha asistido?",
    "3 · Cumplimiento": "¿Los pacientes llegan en la fecha que se les programó?",
    "4 · Alertas y gestión": "¿Quién está retrasado a la fecha de corte y qué se hizo?",
    "5 · Reporte de alertas": "¿Dónde se concentran los retrasos?",
    "6 · Visor de pacientes": "¿Cómo va un paciente-ojo en particular?",
}


def fecha(x) -> str:
    return "" if pd.isna(x) else pd.Timestamp(x).strftime("%d/%m/%Y")


def a_excel(hojas: dict) -> bytes:
    """Libro de Excel para descargar (una hoja por tabla)."""
    salida = io.BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as w:
        for nombre, df in hojas.items():
            df.to_excel(w, sheet_name=nombre[:31], index=False)
    return salida.getvalue()


def descarga(nombre: str, df: pd.DataFrame, clave: str) -> None:
    if not df.empty:
        st.download_button(f"Descargar en Excel ({miles(len(df))} filas)", a_excel({nombre: df}), file_name=f"{nombre}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=clave)


def layout(fig, titulo: str, subtitulo: str, alto: int, **kw) -> None:
    comun.base_layout(fig, titulo, alto, **kw)
    if subtitulo:
        lineas = textwrap.wrap(subtitulo, 62) or [subtitulo]     # svg no ajusta el texto: se parte a mano
        extra = 18 * len(lineas) + 2
        fig.layout.title.text += "".join(f"<br><span style='font-size:12px;color:{TINTA2}'>{l}</span>" for l in lineas)
        fig.update_layout(height=fig.layout.height + extra, margin_t=fig.layout.margin.t + extra)
        if fig.layout.showlegend:
            fig.update_layout(legend_y=fig.layout.legend.y - extra / fig.layout.height)
    fig.update_layout(legend_traceorder="normal")


def mostrar(fig) -> None:
    st.plotly_chart(fig, width="stretch", config=CONFIG)


def barras(c: pd.DataFrame, col: str, titulo: str, eje: str) -> None:
    """Columnas con el número sobre cada barra, de mayor a menor (las «Distribución por …» del PBI)."""
    if c.empty:
        st.info(f"Sin datos para «{titulo}» con los filtros actuales.")
        return
    fig = go.Figure(go.Bar(x=c[col], y=c["n"], marker=dict(color=CAT[0], cornerradius=3), text=[miles(n) for n in c["n"]],
                           textposition="outside", textfont=dict(color=TINTA, size=11), cliponaxis=False,
                           customdata=c["pct"], hovertemplate="%{x}: %{y:,} (%{customdata:.1f} %)<extra></extra>"))
    layout(fig, titulo, "", 300, xaxis=dict(title=None, type="category", tickangle=-30 if len(c) > 4 else 0),
           yaxis=dict(title=eje, range=[0, float(c["n"].max()) * 1.18]), bargap=0.3)
    mostrar(fig)


def treemap(serie: pd.Series, titulo: str, sufijo: str = " sem") -> None:
    v = serie.dropna().astype(int).value_counts()
    if v.empty:
        st.info(f"Sin datos para «{titulo}».")
        return
    tot = v.sum()
    fig = go.Figure(go.Treemap(labels=[f"{k}{sufijo}" for k in v.index], parents=[""] * len(v), values=v.values,
                               texttemplate="<b>%{label}</b><br>%{value:,} (%{percentRoot:.1%})", hovertemplate="%{label}: %{value:,}<extra></extra>",
                               marker=dict(colors=[comun.rgba(CAT[0], 0.35 + 0.65 * n / v.max()) for n in v.values], line=dict(color="#fff", width=2))))
    layout(fig, titulo, f"n = {miles(tot)} · el tamaño de cada bloque es el número de dosis", 330)
    fig.update_layout(margin=dict(l=4, r=4, b=4))
    mostrar(fig)


def lista_pacientes(x: pd.DataFrame, ver_id: bool, extra: list) -> pd.DataFrame:
    """Lista de paciente-ojo reingreso del PBI (nombres, apellidos y código), con la cantidad de filas del período."""
    if x.empty:
        return pd.DataFrame()
    g = x.groupby("pacienteojoreingreso").agg(n=("pacienteojoreingreso", "size"), **{e: (e, "max") for e in extra}).reset_index()
    if ver_id:
        nom = x.groupby("pacienteojoreingreso")[["nombres", "apellidos", "numero_doc"]].first().reset_index()
        g = nom.merge(g, on="pacienteojoreingreso").rename(columns={"nombres": "Nombres", "apellidos": "Apellidos", "numero_doc": "Documento"})
    return g.rename(columns={"pacienteojoreingreso": "Paciente-ojo reingreso"})


# ============================================================================ datos y filtros
@st.cache_data(show_spinner="Preparando el seguimiento de aplicaciones…")
def _aplicaciones(ruta: str, marca: float, llave: bytes | None = None):
    return LA.cargar(Path(ruta), llave)


CORRIDA, MART, META, LLAVE = comun.elegir_corrida()
APL = _aplicaciones(str(CORRIDA["ruta"]), (CORRIDA["ruta"] / "metadata.json").stat().st_mtime, LLAVE)
PRESTADOR = str(META.get("prestador", "sin_definir"))
st.title("Seguimiento de aplicaciones")
if APL is None or APL.empty:
    st.info("Esta corrida no trae el detalle de aplicaciones. Vuelva a procesar el formulario desde «Pipeline de datos».")
    st.stop()
if APL["fecha_programacion"].notna().mean() < 0.5:
    st.warning(f"El formulario trae la fecha programada en solo {dec(100 * APL['fecha_programacion'].notna().mean(), 0)} % de las aplicaciones: "
               "las dosis programadas, el cumplimiento y las alertas se calculan con ese subconjunto.")

st.sidebar.markdown("---")
st.sidebar.markdown("### Período")
FMIN, FMAX = APL["fecha_aplicacion"].min().date(), APL["fecha_aplicacion"].max().date()
FMAX_PROG = max(FMAX, APL["fecha_programacion"].max().date()) if APL["fecha_programacion"].notna().any() else FMAX
_defecto = (max(FMIN, (pd.Timestamp(FMAX) - pd.Timedelta(days=364)).date()), FMAX)
periodo = st.sidebar.date_input("Desde / hasta", value=st.session_state.get("ap-periodo", _defecto), min_value=FMIN, max_value=FMAX_PROG,
                                format="DD/MM/YYYY", key="ap-periodo-w",
                                help="Aplicadas y cumplimiento: por fecha de aplicación. Programadas: por fecha programada (como el PBI).")
DESDE, HASTA = (periodo if isinstance(periodo, (list, tuple)) and len(periodo) == 2 else _defecto)
st.session_state["ap-periodo"] = (DESDE, HASTA)
st.sidebar.markdown("### Alertas")
CORTE = st.sidebar.date_input("Fecha de corte", value=min(FMAX, date.today()), min_value=FMIN, max_value=FMAX_PROG, format="DD/MM/YYYY",
                              key="ap-corte", help="Se mira la última cita programada de cada paciente-ojo con lo aplicado hasta esta fecha.")
VENTANA = int(st.sidebar.number_input("Ventana (± días)", min_value=1, max_value=60, value=LA.tolerancia(), step=1, key="ap-ventana"))

st.sidebar.markdown("### Filtros")
dx_op = sorted(APL["diagnostico_apl"].unique(), key=str.lower)
dx_sel = st.sidebar.multiselect("Diagnóstico (de la aplicación)", dx_op, default=dx_op, key="ap-dx")
mol_op = sorted(APL["molecula_label"].unique())
mol_sel = st.sidebar.multiselect("Molécula aplicada", mol_op, default=mol_op, key="ap-mol")
MASCARA = pd.Series(True, index=MART.index)
for col, nombre in (("sede", "Sede"), ("eapb", "EAPB")):     # mismas claves que el Tablero: el filtro se comparte
    if col in MART and L.con_dato(MART[col]).any():
        valores = MART[col].where(L.con_dato(MART[col]), "Sin dato").astype(str)
        MASCARA &= valores.isin(comun._multiselect(nombre, sorted(valores.unique()), f"f-{col}", sorted(valores.unique())))
VER_ID = comun.identificacion_visible(META)
POR_OK = set(MART.loc[MASCARA, "pacienteojoreingreso"])
A = APL[APL["diagnostico_apl"].isin(dx_sel) & APL["molecula_label"].isin(mol_sel) & APL["pacienteojoreingreso"].isin(POR_OK)]
st.sidebar.markdown("---")
st.sidebar.metric("Aplicaciones en el filtro", miles(len(A)))
st.sidebar.caption(f"Prestador: **{PRESTADOR.upper()}** · corrida {comun.fecha(META.get('generado'))}")

G_TODO = gestion.leer(PRESTADOR, llave=LLAVE)
G_VIG = gestion.vigentes(G_TODO)
GESTIONADAS = {(r.pacienteojoreingreso, pd.Timestamp(r.fecha_programada)) for r in G_VIG.itertuples() if pd.notna(r.fecha_programada)}

st.caption("Inyecciones aplicadas, citas programadas y cumplimiento de la fecha programada (Power BI de aplicaciones), con las alertas "
           "y la gestión de incumplimientos (Excel de alertas). Cada fila cuenta una aplicación o una cita.")
VISTA = st.segmented_control("Pestaña", list(PESTANAS), default=list(PESTANAS)[0], key="vista-apl", label_visibility="collapsed") or list(PESTANAS)[0]
st.markdown(f'<div class="nivel" style="--c:{CAT[0]}"><h3>{VISTA.split(" · ")[1]}</h3><p>{PESTANAS[VISTA]}</p></div>', unsafe_allow_html=True)
if VISTA in ("1 · Dosis aplicadas", "2 · Dosis programadas", "3 · Cumplimiento"):
    st.markdown(f"<div style='background:{TINTA};color:#fff;border-radius:8px;padding:6px 14px;display:inline-block;font-weight:600'>"
                f"Reporte filtrado del {fecha(DESDE)} al {fecha(HASTA)}</div>", unsafe_allow_html=True)


# ============================================================================ 1 · Dosis aplicadas
if VISTA == "1 · Dosis aplicadas":
    x = LA.dosis_aplicadas(A, DESDE, HASTA)
    k1, k2 = st.columns([1, 3])
    k1.metric("Dosis aplicadas", miles(len(x)))
    k2.caption("Total de inyecciones anti-VEGF aplicadas en el período (por fecha de aplicación), por diagnóstico, medicamento y EAPB; "
               "distribución por número de dosis acumuladas e intervalo real entre dosis consecutivas. Permite ver si los pacientes reciben "
               "el tratamiento con la frecuencia indicada.")
    c1, c2, c3 = st.columns(3)
    with c1:
        barras(LA.conteo(x, "diagnostico_apl"), "diagnostico_apl", "Distribución por diagnóstico", "Dosis aplicadas")
    with c2:
        barras(LA.conteo(x, "eapb_label"), "eapb_label", "Distribución por EAPB", "Dosis aplicadas")
    with c3:
        barras(LA.conteo(x, "molecula_label"), "molecula_label", "Distribución por medicamento", "Dosis aplicadas")
    c1, c2 = st.columns([2, 3])
    with c1:
        treemap(x["Semanas_Entre_Dosis"], "Intervalo real entre dosis (semanas)")
    with c2:
        st.markdown("**Distribución por consecutivo de dosis** · filas: número de dosis; columnas: semanas desde la dosis anterior")
        m = LA.matriz(x, "con_dosis", "Semanas_Entre_Dosis")
        st.markdown(comun.tabla_simple(m, "con_dosis") if not m.empty else "<i>Sin datos.</i>", unsafe_allow_html=True)
    st.markdown("**Pacientes con dosis aplicadas en el período**")
    lp = lista_pacientes(x, VER_ID, ["fecha_aplicacion", "con_dosis"]).rename(columns={"n": "dosis en el período", "fecha_aplicacion": "última aplicación",
                                                                                         "con_dosis": "última dosis (consecutivo)"})
    if not lp.empty:
        lp["última aplicación"] = lp["última aplicación"].map(fecha)
        st.dataframe(lp, hide_index=True, width="stretch", height=280)
        descarga("dosis_aplicadas", lp, "dl-apl")


# ============================================================================ 2 · Dosis programadas
if VISTA == "2 · Dosis programadas":
    x = LA.dosis_programadas(A, DESDE, HASTA)
    k1, k2 = st.columns([1, 3])
    k1.metric("Dosis programadas", miles(len(x)))
    k2.caption("Citas de aplicación programadas en el período (por fecha programada), por diagnóstico, medicamento y EAPB; intervalo entre la "
               "aplicación y la fecha programada siguiente (si el esquema asignado es coherente con la evolución) y quién aún no ha asistido. "
               "La lista de abajo es la hoja «Programación» del Excel.")
    c1, c2, c3 = st.columns(3)
    with c1:
        barras(LA.conteo(x, "diagnostico_apl"), "diagnostico_apl", "Distribución por diagnóstico", "Dosis programadas")
    with c2:
        barras(LA.conteo(x, "eapb_label"), "eapb_label", "Distribución por EAPB", "Dosis programadas")
    with c3:
        barras(LA.conteo(x, "molecula_label"), "molecula_label", "Distribución por medicamento", "Dosis programadas")
    c1, c2 = st.columns([2, 3])
    with c1:
        treemap(x["Semanas_Apl_a_Prog"], "Intervalo aplicación → programación siguiente (semanas)")
    with c2:
        st.markdown("**Distribución del intervalo por consecutivo de dosis** · filas: dosis en que se programó; columnas: semanas hasta la cita")
        m = LA.matriz(x, "con_dosis", "Semanas_Apl_a_Prog")
        st.markdown(comun.tabla_simple(m, "con_dosis") if not m.empty else "<i>Sin datos.</i>", unsafe_allow_html=True)
    st.markdown("**Programación: citas con fecha programada en el período**")
    if x.empty:
        st.info("No hay citas programadas en el período.")
    else:
        x = x.sort_values(["fecha_programacion", "pacienteojoreingreso"])      # por fecha real (no por el texto dd/mm/aaaa)
        sig = x["fecha_aplicacion_siguiente"]
        asistio = np.where(sig.notna(), "Sí · " + sig.dt.strftime("%d/%m/%Y").fillna(""),
                           np.where(x["fecha_programacion"] > pd.Timestamp(FMAX), "Cita futura", "Pendiente"))
        prog = pd.DataFrame({"Paciente-ojo reingreso": x["pacienteojoreingreso"], "Molécula": x["molecula_label"], "Médico tratante": x["medico"],
                             "Fecha aplicación": x["fecha_aplicacion"].map(fecha), "Consecutivo dosis": x["con_dosis"],
                             "Semana extensión": x["semana_extension"], "Fecha programada": x["fecha_programacion"].map(fecha),
                             "Cod Dx": x["dx_ppal"], "Dx": x["diagnostico_apl"], "EAPB": x["eapb_label"], "¿Ya asistió?": asistio})
        if VER_ID:
            prog.insert(0, "Apellidos", x["apellidos"].values)
            prog.insert(0, "Nombres", x["nombres"].values)
            prog.insert(0, "Documento", x["numero_doc"].values)
        pend = int((prog["¿Ya asistió?"] == "Pendiente").sum())
        st.caption(f"{miles(len(prog))} citas · {miles(pend)} pendientes: la fecha ya pasó y no hay una aplicación posterior registrada.")
        st.dataframe(prog, hide_index=True, width="stretch", height=320)
        descarga("programacion", prog, "dl-prog")


# ============================================================================ 3 · Cumplimiento
if VISTA == "3 · Cumplimiento":
    x = LA.cumplimiento(A, DESDE, HASTA)
    k1, k2, k3 = st.columns([1, 1, 2])
    k1.metric("Cumplimiento aplicaciones", miles(len(x)), help="Aplicaciones del período con una fecha programada en la dosis anterior.")
    k2.metric("Porcentaje cumplimiento", f"{dec(LA.pct_dentro_ventana(x), 2)} %" if len(x) else "—",
              help=f"Aplicaciones que llegaron entre {LA.tolerancia()} días antes y {LA.tolerancia()} días después de la fecha programada.")
    k3.caption("Días de anticipación o retraso de cada aplicación frente a la fecha que se le programó en la dosis anterior (como el PBI): "
               f"días = fecha de aplicación − fecha programada; cumple si está entre −{LA.tolerancia()} y +{LA.tolerancia()}. Por diagnóstico, "
               "medicamento, EAPB y número de dosis. El indicador «Cumplimiento de aplicaciones» del Tablero usa la misma ventana, pero "
               "cuenta cada cita en la dosis que la programó y por año de tratamiento.")
    c1, c2, c3 = st.columns(3)
    with c1:
        barras(LA.conteo(x, "diagnostico_apl"), "diagnostico_apl", "Distribución por diagnóstico", "Total cumplimiento")
    with c2:
        barras(LA.conteo(x, "molecula_label"), "molecula_label", "Distribución por medicamento", "Total cumplimiento")
    with c3:
        barras(LA.conteo(x, "eapb_label"), "eapb_label", "Distribución por EAPB", "Total cumplimiento")
    st.markdown("**Distribución de días por consecutivo de dosis** · filas: número de dosis; columnas: clasificación del cumplimiento")
    m = LA.matriz(x, "con_dosis", "Clasificacion_Cumplimiento", LA.orden_clasificacion())
    st.markdown(comun.tabla_simple(m, "con_dosis") if not m.empty else "<i>Sin datos.</i>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if len(x):
            d = x["Dias_Cumplimiento"].astype(int)
            lo, hi = int(max(d.min(), d.quantile(0.01))), int(min(d.max(), d.quantile(0.99)))
            v = d.clip(lo, hi).value_counts().sort_index()
            fig = go.Figure(go.Bar(x=v.index, y=v.values, marker=dict(color=[COLOR_CLASE["3. Exacto"] if abs(k) <= LA.tolerancia() else GRIS for k in v.index]),
                                   hovertemplate="%{x} días: %{y:,} aplicaciones<extra></extra>"))
            fig.add_vrect(x0=-LA.tolerancia() - 0.5, x1=LA.tolerancia() + 0.5, fillcolor=comun.rgba("#4C9A2A", 0.08), line_width=0)
            layout(fig, "Distribución de días", f"Aplicaciones por días frente a la fecha programada · verde = dentro de ±{LA.tolerancia()} · "
                   f"extremos agrupados en {lo} y {hi}", 300, xaxis=dict(title="Días (negativo = antes de la fecha)"), yaxis=dict(title="Aplicaciones"), bargap=0.1)
            mostrar(fig)
    with c2:
        cl = x["Clasificacion_Cumplimiento"].value_counts().reindex(LA.orden_clasificacion(), fill_value=0)
        fig = go.Figure(go.Bar(x=cl.index, y=cl.values, marker=dict(color=[COLOR_CLASE.get(k.split(" (")[0], GRIS) for k in cl.index], cornerradius=3),
                               text=[miles(n) for n in cl.values], textposition="outside", cliponaxis=False, textfont=dict(color=TINTA, size=11)))
        layout(fig, "Clasificación de cumplimiento", f"n = {miles(int(cl.sum()))} aplicaciones", 300,
               xaxis=dict(title=None, tickangle=-25), yaxis=dict(title="Total cumplimiento", range=[0, max(1, float(cl.max())) * 1.2]))
        mostrar(fig)
    st.markdown("**Pacientes con cumplimiento evaluado en el período**")
    lp = lista_pacientes(x, VER_ID, ["Dias_Cumplimiento"]).rename(columns={"n": "aplicaciones evaluadas", "Dias_Cumplimiento": "máximo de días"})
    if not lp.empty:
        st.dataframe(lp, hide_index=True, width="stretch", height=260)
        descarga("cumplimiento", lp, "dl-cumpl")


# ============================================================================ 4 · Alertas y gestión
def tabla_alertas(al: pd.DataFrame) -> pd.DataFrame:
    g = G_VIG.copy()
    if not g.empty:
        g["fecha_programada"] = pd.to_datetime(g["fecha_programada"])
        al = al.merge(g.rename(columns={"fecha_programada": "ultima_programada"})[["pacienteojoreingreso", "ultima_programada", "causa", "observacion",
                                                                                  "gestionado_por", "registrado_en"]],
                      on=["pacienteojoreingreso", "ultima_programada"], how="left")
    else:
        for c in ("causa", "observacion", "gestionado_por", "registrado_en"):
            al[c] = np.nan
    t = pd.DataFrame({"Paciente-ojo reingreso": al["pacienteojoreingreso"], "Molécula": al["molecula_label"], "Médico": al["medico"],
                      "Última aplicación": al["ultima_aplicacion"].map(fecha), "Dosis": al["con_dosis"],
                      "Última fecha programada": al["ultima_programada"].map(fecha), "Días a la fecha de corte": al["dias"],
                      "Dx": al["diagnostico_apl"], "EAPB": al["eapb_label"], "Egreso registrado": al["egreso_causa"].fillna(""),
                      "Causa (gestión)": al["causa"].fillna(""), "Observación": al["observacion"].fillna(""),
                      "Gestionado por": al["gestionado_por"].fillna(""), "Fecha gestión": al["registrado_en"].fillna("").astype(str).str[:16].str.replace("T", " ")})
    if VER_ID:
        t.insert(0, "Apellidos", al["apellidos"].values)
        t.insert(0, "Nombres", al["nombres"].values)
        t.insert(0, "Documento", al["numero_doc"].values)
    return t


def calcular_alertas(incluir_egreso: bool = True) -> pd.DataFrame:
    al = LA.alertas(A, CORTE, VENTANA)
    if not incluir_egreso and not al.empty:
        al = al[al["egreso_causa"].isna() | (al["egreso_fecha"] > pd.Timestamp(CORTE))]
    return al


if VISTA == "4 · Alertas y gestión":
    incluir = st.toggle("Incluir paciente-ojo con egreso registrado en el formulario", value=True, key="ap-egreso",
                        help="Con egreso (por ejemplo «Seis meses última inyección») el paciente ya salió del programa; apáguelo para ver solo activos.")
    al = calcular_alertas(incluir)
    k = LA.kpis_alertas(pd.DataFrame(columns=["pacienteojoreingreso"]), al, GESTIONADAS)
    c = st.columns(6)
    c[0].metric(f"En rango (±{VENTANA} d)", miles(k["en_rango"]))
    c[1].metric(f"Retraso > {VENTANA} d", miles(k["retraso"]))
    c[2].metric("Retraso con gestión", miles(k["con_gestion"]))
    c[3].metric("Retraso sin gestión", miles(k["sin_gestion"]))
    c[4].metric("Cita futura", miles(k["futura"]))
    c[5].metric("Sin fecha programada", miles(k["sin_fecha"]))
    st.caption(f"Para cada paciente-ojo, la última cita programada con lo aplicado hasta el {fecha(CORTE)}; días = fecha de corte − cita. "
               f"En rango: entre −{VENTANA} y +{VENTANA}; retraso: la cita pasó hace más de {VENTANA} días sin una aplicación nueva; cita futura: "
               f"faltan más de {VENTANA} días. % en rango sobre evaluados: {dec(k['pct_en_rango'], 1)} %.")
    estados = [LA.RETRASO, LA.EN_RANGO, LA.FUTURA, LA.SIN_FECHA]
    est = st.segmented_control("Lista", estados, default=LA.RETRASO, key="ap-estado", format_func=lambda e: LA.etiqueta_estado(e, VENTANA)) or LA.RETRASO
    sub = al[al["estado"] == est].sort_values("dias", ascending=False)
    t = tabla_alertas(sub)
    st.dataframe(t, hide_index=True, width="stretch", height=330)
    descarga(f"alertas_{est.lower().replace(' ', '_')}", t, "dl-alertas")

    st.markdown("##### Registrar gestión de un incumplimiento")
    retraso = al[al["estado"] == LA.RETRASO].sort_values("dias", ascending=False)
    if retraso.empty:
        st.info("No hay paciente-ojo con retraso para gestionar con los filtros actuales.")
    else:
        opciones = {f"{r.pacienteojoreingreso} · cita {fecha(r.ultima_programada)} · {int(r.dias)} días"
                    + (" · ya gestionado" if (r.pacienteojoreingreso, r.ultima_programada) in GESTIONADAS else ""): (r.pacienteojoreingreso, r.ultima_programada)
                    for r in retraso.itertuples()}
        with st.form("form-gestion", clear_on_submit=True):
            elegido = st.selectbox("Paciente-ojo con retraso", list(opciones), key="g-por")
            c1, c2 = st.columns(2)
            causa = c1.selectbox("Causa del incumplimiento", gestion.CAUSAS, index=None, placeholder="Elija una causa", key="g-causa")
            quien = c2.text_input("Registrado por", value=st.session_state.get("g-quien-ultimo", ""), key="g-quien")
            obs = st.text_area("Observación", placeholder="Ej.: se llamó al paciente; reprograma para la próxima semana", key="g-obs")
            if st.form_submit_button("Guardar gestión", type="primary"):
                por, fprog = opciones[elegido]
                try:
                    gestion.registrar(PRESTADOR, por, fprog, causa, obs, quien, llave=LLAVE)
                    st.session_state["g-quien-ultimo"] = quien
                    st.session_state["_aviso_gestion"] = f"Gestión guardada para {por} (cita del {fecha(fprog)})."
                    st.rerun()
                except ValueError as e:
                    st.error(str(e) if causa else "Elija la causa del incumplimiento.")
        if st.session_state.get("_aviso_gestion"):
            st.success(st.session_state.pop("_aviso_gestion"))
        st.caption("Cada gestión queda con quién la registró y cuándo, ligada a esa cita. No se borra: una corrección es un registro nuevo y "
                   "vale el más reciente. Una carga nueva del formulario no la afecta."
                   + (" En esta demostración los registros se guardan en el servidor de prueba y pueden perderse cuando se reinicia."
                      if META.get("sintetico") or META.get("es_demo") else ""))
    with st.expander(f"Historial de gestiones ({miles(len(G_TODO))} registros)"):
        if G_TODO.empty:
            st.caption("Aún no hay gestiones registradas.")
        else:
            h = G_TODO.sort_values("registrado_en", ascending=False).assign(fecha_programada=lambda d: d["fecha_programada"].map(fecha))
            h = h.rename(columns={"registrado_en": "Registrado en", "pacienteojoreingreso": "Paciente-ojo reingreso", "fecha_programada": "Cita",
                                  "causa": "Causa", "observacion": "Observación", "gestionado_por": "Gestionado por"}).drop(columns="id")
            st.dataframe(h, hide_index=True, width="stretch")
            descarga("historial_gestion", h, "dl-hist")


# ============================================================================ 5 · Reporte de alertas
if VISTA == "5 · Reporte de alertas":
    al = calcular_alertas(st.session_state.get("ap-egreso", True))
    prog = LA.dosis_programadas(A, DESDE, HASTA)
    k = LA.kpis_alertas(prog, al, GESTIONADAS)
    st.markdown(f"**Período (programación):** {fecha(DESDE)} → {fecha(HASTA)} · **Fecha de corte:** {fecha(CORTE)} · **Ventana:** ±{VENTANA} días")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Programación**")
        st.metric("Total registros", miles(k["prog_registros"]))
        st.caption(f"Pacientes-ojo únicos: {miles(k['prog_por'])} · Sin fecha programada (en alertas): {miles(k['sin_fecha'])}")
    with c2:
        st.markdown("**Cumplen (en rango)**")
        st.metric("Total cumplen", miles(k["en_rango"]))
        st.caption(f"% sobre total evaluados (en rango + retraso): {dec(k['pct_en_rango'], 1)} %")
    with c3:
        st.markdown("**No cumplen (retraso)**")
        st.metric("Total no cumplen", miles(k["retraso"]))
        st.caption(f"Con gestión registrada: {miles(k['con_gestion'])} · Sin gestión: {miles(k['sin_gestion'])}")
    medidas = [("n", "N", miles), ("pct", "%", lambda v: f"{dec(v, 1)}%")]
    grupos = [("prog", "Programación"), ("cumplen", "Cumplen"), ("retraso", "No cumplen")]
    for titulo, ca, cp in (("Reporte 1 — Por diagnóstico", "diagnostico_apl", "diagnostico_apl"), ("Reporte 2 — Por medicamento", "molecula_label", "molecula_label"),
                           ("Reporte 3 — Por EAPB", "eapb_label", "eapb_label"), ("Reporte 4 — Por médico tratante", "medico", "medico")):
        r = LA.reporte_por(al, prog, ca, cp)
        r.columns = pd.MultiIndex.from_tuples([tuple(c.split("_")) for c in r.columns])
        st.markdown(f"**{titulo}**")
        st.markdown(comun.tabla_pbi(r, grupos=grupos, medidas=medidas, titulo_filas="Categoría", encabezado=""), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Reporte 5 — Últimas dosis** · citas programadas en el período por consecutivo de dosis")
        d = LA.reporte_dosis(prog)
        d.columns = pd.MultiIndex.from_tuples([("Programación", "n"), ("Programación", "pct")])
        st.markdown(comun.tabla_pbi(d, grupos=[("Programación", "Programación")], medidas=medidas, titulo_filas="Categoría", encabezado=""), unsafe_allow_html=True)
    with c2:
        st.markdown("**Reporte 6 — Causa de incumplimiento** · gestión vigente de los paciente-ojo con retraso")
        ret = al[al["estado"] == LA.RETRASO][["pacienteojoreingreso", "ultima_programada"]]
        g = G_VIG.copy()
        if not g.empty and not ret.empty:
            g["fecha_programada"] = pd.to_datetime(g["fecha_programada"])
            g = g.merge(ret, left_on=["pacienteojoreingreso", "fecha_programada"], right_on=["pacienteojoreingreso", "ultima_programada"])
        if g.empty or ret.empty:
            st.caption("Ningún paciente-ojo con retraso tiene gestión registrada todavía.")
        else:
            cc = g["causa"].value_counts().reindex(gestion.CAUSAS, fill_value=0)
            cc = cc[cc > 0].rename("n").to_frame()
            cc["pct"] = 100 * cc["n"] / cc["n"].sum()
            cc.loc["Total"] = [cc["n"].sum(), 100.0]
            cc.columns = pd.MultiIndex.from_tuples([("Gestión", "n"), ("Gestión", "pct")])
            st.markdown(comun.tabla_pbi(cc, grupos=[("Gestión", "Gestiones")], medidas=medidas, titulo_filas="Causa", encabezado=""), unsafe_allow_html=True)
    st.caption("Cumplen / no cumplen se cuentan por paciente-ojo (su última cita a la fecha de corte); programación, por cita. Los nombres de EAPB "
               "y médicos salen de los datos, así que una EAPB o un médico nuevo aparece solo (en el Excel había que agregarlo a mano).")


# ============================================================================ 6 · Visor de pacientes
if VISTA == "6 · Visor de pacientes":
    pors = sorted(A["pacienteojoreingreso"].dropna().astype(str).unique())
    if not pors:
        st.info("No hay paciente-ojo con los filtros actuales.")
        st.stop()
    buscar = st.text_input("Buscar paciente-ojo reingreso" + (" o documento" if VER_ID else ""), key="ap-buscar", placeholder="Ej.: 9000123OD0")
    if buscar:
        b = buscar.strip().lower()
        cand = A[A["pacienteojoreingreso"].astype(str).str.lower().str.contains(b, regex=False)
                 | (A["numero_doc"].astype(str).str.contains(b, regex=False) if VER_ID else False)]["pacienteojoreingreso"].astype(str).unique()
        pors = sorted(cand)
    if not pors:
        st.warning("Ningún paciente-ojo coincide con la búsqueda.")
        st.stop()
    por = st.selectbox(f"Paciente-ojo reingreso ({miles(len(pors))})", pors, key="ap-por")
    x = APL[APL["pacienteojoreingreso"] == por].sort_values(["fecha_aplicacion", "con_dosis"])
    p = x.iloc[0]
    datos = [("Diagnóstico", p["diagnostico_apl"]), ("EAPB", p["eapb_label"]), ("Sexo", p.get("sexo", "")), ("Sede", p.get("sede", "")),
             ("Aplicaciones", miles(len(x))), ("Egreso", p.get("egreso_causa") if pd.notna(p.get("egreso_causa")) else "—")]
    if VER_ID:
        datos = [("Nombre", f"{p.get('nombres', '')} {p.get('apellidos', '')}"), ("Documento", p.get("numero_doc", ""))] + datos
    st.markdown(" · ".join(f"**{k}:** {v}" for k, v in datos))
    t = pd.DataFrame({"Dosis": x["con_dosis"], "Fecha aplicación": x["fecha_aplicacion"].map(fecha), "Molécula": x["molecula_label"],
                      "Fecha programada (siguiente)": x["fecha_programacion"].map(fecha), "Programada en la dosis anterior": x["FechaProg_Anterior"].map(fecha),
                      "Días frente a lo programado": x["Dias_Cumplimiento"].map(lambda v: "" if pd.isna(v) else int(v)), "Clasificación": x["Clasificacion_Cumplimiento"].replace("Sin dato", ""),
                      "Semanas desde la dosis anterior": x["Semanas_Entre_Dosis"].map(lambda v: "" if pd.isna(v) else int(v)), "Médico": x["medico"], "Dx": x["diagnostico_apl"]})
    st.dataframe(t, hide_index=True, width="stretch")
    g = G_TODO[G_TODO["pacienteojoreingreso"] == por]
    if not g.empty:
        st.markdown("**Gestiones registradas**")
        st.dataframe(g.assign(fecha_programada=g["fecha_programada"].map(fecha)).drop(columns=["id", "pacienteojoreingreso"]), hide_index=True, width="stretch")
