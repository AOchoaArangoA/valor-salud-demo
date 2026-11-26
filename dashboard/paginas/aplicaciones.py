"""Página «Seguimiento de aplicaciones», con dos secciones separadas, cada una con sus propios controles:

A · Reporte de aplicaciones (Power BI «reporte_aplicaciones_v4»): período y segmentadores de diagnóstico, molécula y EAPB;
    pestañas Dosis aplicadas, Dosis programadas, Cumplimiento y Visor de pacientes.
B · Alertas de aplicaciones (Excel «tablero_alertas_aplicaciones»): parámetros (fecha inicio y fin, fecha de corte, ventana);
    pestañas Programación, Cumplen, No cumplen y gestión, Reportes, y Gestión y causas (reemplaza «TablaGestion» y «Causas»).
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
import logic_aplicaciones as LA
from pipeline import gestion

CAT, GRIS = comun.CAT, comun.GRIS
TINTA, TINTA2 = "#1B2430", "#5B6675"
CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}
miles, dec = comun.miles, comun.dec
COLOR_CLASE = {"1. Muy adelantado": "#8E6CC0", "2. Adelantado": "#7FA9EC", "3. Exacto": "#4C9A2A", "4. Retraso leve": "#E0A100",
               "5. Retraso moderado": "#D26E00", "6. Retraso grave": "#C0392B"}
COLOR_ESTADO = {LA.EN_RANGO: "#4C9A2A", LA.RETRASO: "#C0392B", LA.FUTURA: "#1F5FBF", LA.SIN_FECHA: GRIS}
SECCIONES = ["A · Reporte de aplicaciones", "B · Alertas de aplicaciones"]
PESTANAS_PBI = {
    "1 · Dosis aplicadas": "¿Cuántas inyecciones se aplicaron en el período?",
    "2 · Dosis programadas": "¿Cuántas citas se programaron en el período?",
    "3 · Cumplimiento": "¿Los pacientes llegan en la fecha que se les programó?",
    "4 · Visor de pacientes": "¿Cómo va un paciente-ojo en particular?",
}
PESTANAS_EXCEL = {
    "1 · Programación": "¿Quién tiene cita programada en el rango de fechas?",
    "2 · Cumplen": "¿Quién tiene su cita dentro de la ventana a la fecha de corte?",
    "3 · No cumplen y gestión": "¿Quién está retrasado y qué se hizo?",
    "4 · Reportes": "¿Dónde se concentran los retrasos?",
    "5 · Gestión y causas": "¿Qué gestiones se han registrado?",
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


def treemap(serie: pd.Series, titulo: str, sufijo: str = " sem", min_pct: float = 1.5, etiqueta_pct: float = 3.0) -> None:
    """Bloques por intervalo. Los intervalos con menos de `min_pct` % se juntan en un bloque «Otras» (el detalle va en la
    ayuda al pasar el cursor) y solo los bloques de al menos `etiqueta_pct` % llevan cifra; los medianos llevan solo el nombre."""
    v = serie.dropna().astype(int).map(banda_semanas).value_counts()      # la cola larga (> 16 semanas) va en bandas
    if v.empty:
        st.info(f"Sin datos para «{titulo}».")
        return
    tot = int(v.sum())
    pct = 100 * v / tot
    grande, chico = v[pct >= min_pct], v[pct < min_pct]
    etiquetas = [f"{k}{sufijo}" for k in grande.index]
    valores = list(grande.values)
    ayuda = [f"{k}{sufijo}: {miles(n)} dosis ({dec(100 * n / tot, 1)} %)" for k, n in grande.items()]
    if len(chico):
        etiquetas.append(f"Otras ({len(chico)})")
        valores.append(int(chico.sum()))
        det = ", ".join(f"{k}{sufijo} ({miles(n)})" for k, n in chico.items())
        ayuda.append(f"Otras: {miles(chico.sum())} dosis ({dec(100 * chico.sum() / tot, 1)} %)<br>"
                     + "<br>".join(textwrap.wrap(det, 60)))
    texto = []
    for e, n in zip(etiquetas, valores):
        p_ = 100 * n / tot
        texto.append(f"<b>{e}</b><br>{miles(n)} ({dec(p_, 1)} %)" if p_ >= etiqueta_pct or e.startswith("Otras") else f"<b>{e}</b>")
    vmax = max(valores)
    colores = [GRIS if e.startswith("Otras") else comun.rgba(CAT[0], 0.35 + 0.65 * n / vmax) for e, n in zip(etiquetas, valores)]
    fig = go.Figure(go.Treemap(labels=etiquetas, parents=[""] * len(etiquetas), values=valores, text=texto, customdata=ayuda,
                               texttemplate="%{text}", hovertemplate="%{customdata}<extra></extra>", textposition="middle center",
                               marker=dict(colors=colores, line=dict(color="#fff", width=2)), sort=True, tiling=dict(pad=2)))
    layout(fig, titulo, f"n = {miles(tot)} · el tamaño de cada bloque es el número de dosis · gris = intervalos con menos de {dec(min_pct, 1)} %", 330)
    fig.update_layout(margin=dict(l=4, r=4, b=4), uniformtext=dict(minsize=9, mode="hide"))
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


def banda_dosis(d) -> str:
    """Consecutivo de dosis -> fila del mapa: 1 a 12 una por una y luego bandas, para que el mapa quepa en pantalla."""
    d = int(d)
    if d <= 12:
        return str(d)
    for lo, hi in ((13, 18), (19, 24), (25, 36)):
        if d <= hi:
            return f"{lo}–{hi}"
    return "37 o más"


def banda_semanas(w) -> str:
    """Semanas -> columna del mapa: 1 a 16 una por una y la cola larga en bandas."""
    w = int(w)
    if w <= 16:
        return str(w)
    for lo, hi in ((17, 20), (21, 26), (27, 39), (40, 52)):
        if w <= hi:
            return f"{lo}–{hi}"
    return "> 52"


def agrupar_semanas(m: pd.DataFrame) -> pd.DataFrame:
    cuerpo = m.drop(columns="Total")
    if not all(isinstance(c, (int, float, np.integer, np.floating)) for c in cuerpo.columns):
        return m
    orden = list(dict.fromkeys(banda_semanas(c) for c in sorted(cuerpo.columns)))
    g = cuerpo.T.groupby([banda_semanas(c) for c in cuerpo.columns]).sum().T[orden]
    return pd.concat([g, m[["Total"]]], axis=1)


def agrupar_dosis(m: pd.DataFrame) -> pd.DataFrame:
    total = m.loc[["Total"]]
    cuerpo = m.drop(index="Total")
    g = cuerpo.groupby([banda_dosis(i) for i in cuerpo.index], sort=False).sum()
    return pd.concat([g, total])


def mapa_calor(m: pd.DataFrame, titulo: str, subtitulo: str, eje_x: str, sufijo_x: str = "") -> None:
    """Tabla dinámica del PBI (consecutivo de dosis × categoría) como mapa de calor: cabe completa y se lee de un vistazo.
    Los totales van en las etiquetas de los ejes."""
    if m.empty:
        st.info(f"Sin datos para «{titulo}».")
        return
    m = agrupar_semanas(agrupar_dosis(m))
    z = m.drop(index="Total", columns="Total")
    ylab = [f"Dosis {i} ({miles(m.loc[i, 'Total'])})" for i in z.index]
    xlab = [f"{c}{sufijo_x}<br><span style='font-size:10px;color:{TINTA2}'>{miles(m.loc['Total', c])}</span>" for c in z.columns]
    texto = [[miles(v) if v else "" for v in fila] for fila in z.values]
    fig = go.Figure(go.Heatmap(z=z.values, x=xlab, y=ylab, colorscale=[[0, "#FFFFFF"], [0.0001, "#EEF3FB"], [1, CAT[0]]], showscale=False,
                               text=texto, texttemplate="%{text}", textfont=dict(size=10), xgap=1, ygap=1,
                               hovertemplate="%{y}<br>" + eje_x + ": %{x}<br>%{z:,}<extra></extra>"))
    layout(fig, titulo, subtitulo + f" · total {miles(m.loc['Total', 'Total'])}", 70 + 24 * len(z),
           xaxis=dict(title=eje_x, side="bottom", type="category", tickangle=0, tickfont=dict(size=10)), yaxis=dict(autorange="reversed", title=None, type="category"))
    fig.update_layout(plot_bgcolor="#FFFFFF")
    mostrar(fig)


def lista_en_desplegable(titulo: str, df: pd.DataFrame, nombre: str, clave: str) -> None:
    with st.expander(f"{titulo} ({miles(len(df))})"):
        if df.empty:
            st.caption("Sin registros con los filtros actuales.")
        else:
            st.dataframe(df, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(df)))
            descarga(nombre, df, clave)


def tarjetas(valores: list) -> None:
    cols = st.columns(len(valores))
    for c, (etq, val, ayuda) in zip(cols, valores):
        c.metric(etq, val, help=ayuda or None)


def con_identificacion(t: pd.DataFrame, x: pd.DataFrame) -> pd.DataFrame:
    if VER_ID:
        t.insert(0, "Apellidos", x["apellidos"].values)
        t.insert(0, "Nombres", x["nombres"].values)
        t.insert(0, "Documento", x["numero_doc"].values)
    return t


def encabezado(titulo: str, pregunta: str, color: str) -> None:
    st.markdown(f'<div class="nivel" style="--c:{color}"><h3>{titulo}</h3><p>{pregunta}</p></div>', unsafe_allow_html=True)


# ============================================================================ datos
@st.cache_data(show_spinner="Preparando el seguimiento de aplicaciones…")
def _aplicaciones(ruta: str, marca: float, llave: bytes | None = None):
    return LA.cargar(Path(ruta), llave)


CORRIDA, MART, META, LLAVE = comun.elegir_corrida()
APL = _aplicaciones(str(CORRIDA["ruta"]), (CORRIDA["ruta"] / "metadata.json").stat().st_mtime, LLAVE)
PRESTADOR = str(META.get("prestador", "sin_definir"))
st.sidebar.markdown("---")
VER_ID = comun.identificacion_visible(META)
st.sidebar.caption(f"Prestador: **{PRESTADOR.upper()}** · corrida {comun.fecha(META.get('generado'))}")

st.title("Seguimiento de aplicaciones")
if APL is None or APL.empty:
    st.info("Esta corrida no trae el detalle de aplicaciones. Vuelva a procesar el formulario desde «Pipeline de datos».")
    st.stop()
if APL["fecha_programacion"].notna().mean() < 0.5:
    st.warning(f"El formulario trae la fecha programada en solo {dec(100 * APL['fecha_programacion'].notna().mean(), 0)} % de las aplicaciones: "
               "las dosis programadas, el cumplimiento y las alertas se calculan con ese subconjunto.")
FMIN, FMAX = APL["fecha_aplicacion"].min().date(), APL["fecha_aplicacion"].max().date()
FMAX_PROG = max(FMAX, APL["fecha_programacion"].max().date()) if APL["fecha_programacion"].notna().any() else FMAX

SECCION = st.segmented_control("Sección", SECCIONES, default=SECCIONES[0], key="apl-seccion", label_visibility="collapsed") or SECCIONES[0]
st.caption("Dos reportes separados: **A** reproduce el Power BI de aplicaciones (lo ocurrido en un período) y **B** el Excel de alertas "
           "(la situación de cada paciente-ojo a una fecha de corte, con su gestión). Cada uno tiene sus propios controles.")


# ############################################################################ A · REPORTE DE APLICACIONES (POWER BI)
if SECCION == SECCIONES[0]:
    with st.container(border=True):
        c0, c1, c2, c3 = st.columns([1.3, 1, 1, 1])
        _defecto = (max(FMIN, (pd.Timestamp(FMAX) - pd.Timedelta(days=364)).date()), FMAX)
        periodo = c0.date_input("Período", value=st.session_state.get("ap-periodo", _defecto), min_value=FMIN, max_value=FMAX_PROG,
                                format="DD/MM/YYYY", key="ap-periodo-w",
                                help="Aplicadas y cumplimiento: por fecha de aplicación. Programadas: por fecha programada (como el PBI).")
        DESDE, HASTA = (periodo if isinstance(periodo, (list, tuple)) and len(periodo) == 2 else _defecto)
        st.session_state["ap-periodo"] = (DESDE, HASTA)
        dx_op = sorted(APL["diagnostico_apl"].unique(), key=str.lower)
        dx_sel = c1.multiselect("Diagnóstico", dx_op, default=[], key="ap-dx", placeholder="Todos")
        mol_op = sorted(APL["molecula_label"].unique())
        mol_sel = c2.multiselect("Molécula", mol_op, default=[], key="ap-mol", placeholder="Todas")
        eapb_op = sorted(APL["eapb_label"].unique(), key=str.lower)
        eapb_sel = c3.multiselect("EAPB", eapb_op, default=[], key="ap-eapb", placeholder="Todas")
    A = APL[APL["diagnostico_apl"].isin(dx_sel or dx_op) & APL["molecula_label"].isin(mol_sel or mol_op) & APL["eapb_label"].isin(eapb_sel or eapb_op)]
    st.markdown(f"<div style='background:{TINTA};color:#fff;border-radius:8px;padding:6px 14px;display:inline-block;font-weight:600;margin:.2rem 0 .6rem'>"
                f"Reporte filtrado del {fecha(DESDE)} al {fecha(HASTA)}</div>", unsafe_allow_html=True)
    VISTA = st.segmented_control("Pestaña", list(PESTANAS_PBI), default=list(PESTANAS_PBI)[0], key="vista-apl", label_visibility="collapsed") or list(PESTANAS_PBI)[0]
    encabezado(VISTA.split(" · ")[1], PESTANAS_PBI[VISTA], CAT[0])

    # ------------------------------------------------------------------------ 1 · Dosis aplicadas
    if VISTA == "1 · Dosis aplicadas":
        x = LA.dosis_aplicadas(A, DESDE, HASTA)
        sem = x["Semanas_Entre_Dosis"].dropna()
        tarjetas([("Dosis aplicadas", miles(len(x)), "Inyecciones con fecha de aplicación en el período."),
                  ("Paciente-ojo atendidos", miles(x["pacienteojoreingreso"].nunique()), ""),
                  ("Mediana de semanas entre dosis", dec(sem.median(), 0) if len(sem) else "—", "Semanas desde la dosis anterior del mismo paciente-ojo."),
                  ("Inicios de tratamiento (dosis 1)", miles(int((x["con_dosis"] == 1).sum())), "Inyecciones del período que fueron la dosis número 1 de un paciente-ojo. Se cuenta por ojo (si empieza en los dos ojos, suma 2) y un reingreso cuenta otra vez, porque su tratamiento arranca de nuevo en la dosis 1. Cambia con el período y los filtros.")])
        st.caption("Inyecciones anti-VEGF aplicadas en el período, por diagnóstico, medicamento y EAPB; distribución por número de dosis acumuladas "
                   "e intervalo real entre dosis consecutivas, para ver si los pacientes reciben el tratamiento con la frecuencia indicada.")
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
            mapa_calor(LA.matriz(x, "con_dosis", "Semanas_Entre_Dosis"), "Distribución por consecutivo de dosis",
                       "Filas: número de dosis · columnas: semanas desde la dosis anterior", "Semanas entre dosis")
        lp = lista_pacientes(x, VER_ID, ["fecha_aplicacion", "con_dosis"]).rename(columns={"n": "Dosis en el período", "fecha_aplicacion": "Última aplicación",
                                                                                             "con_dosis": "Última dosis (consecutivo)"})
        if not lp.empty:
            lp["Última aplicación"] = lp["Última aplicación"].map(fecha)
        lista_en_desplegable("Pacientes con dosis aplicadas en el período", lp, "dosis_aplicadas", "dl-apl")

    # ------------------------------------------------------------------------ 2 · Dosis programadas
    if VISTA == "2 · Dosis programadas":
        x = LA.dosis_programadas(A, DESDE, HASTA)
        pend = x[x["fecha_aplicacion_siguiente"].isna() & (x["fecha_programacion"] <= pd.Timestamp(FMAX))]
        tarjetas([("Dosis programadas", miles(len(x)), "Citas con fecha programada en el período."),
                  ("Paciente-ojo con cita", miles(x["pacienteojoreingreso"].nunique()), ""),
                  ("Aún sin asistir", miles(len(pend)), "La fecha programada ya pasó y no hay una aplicación posterior registrada."),
                  ("Mediana de semanas a la cita", dec(x["Semanas_Apl_a_Prog"].median(), 0) if len(x) else "—", "Semanas entre la aplicación y la fecha programada siguiente.")])
        st.caption("Citas de aplicación programadas en el período, por diagnóstico, medicamento y EAPB, e intervalo entre la última aplicación y la "
                   "fecha programada siguiente, para evaluar si el esquema asignado es coherente con la evolución clínica.")
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
            mapa_calor(LA.matriz(x, "con_dosis", "Semanas_Apl_a_Prog"), "Distribución del intervalo por consecutivo de dosis",
                       "Filas: dosis en que se programó · columnas: semanas hasta la cita", "Semanas hasta la cita")
        lp = lista_pacientes(x, VER_ID, ["fecha_programacion"]).rename(columns={"n": "Citas en el período", "fecha_programacion": "Última fecha programada"})
        if not lp.empty:
            lp["Última fecha programada"] = lp["Última fecha programada"].map(fecha)
        lista_en_desplegable("Pacientes con citas programadas en el período", lp, "dosis_programadas", "dl-prog-pbi")

    # ------------------------------------------------------------------------ 3 · Cumplimiento
    if VISTA == "3 · Cumplimiento":
        x = LA.cumplimiento(A, DESDE, HASTA)
        tol = LA.tolerancia()
        tarjetas([("Cumplimiento aplicaciones", miles(len(x)), "Aplicaciones del período con una fecha programada en la dosis anterior."),
                  ("Porcentaje cumplimiento", f"{dec(LA.pct_dentro_ventana(x), 2)} %" if len(x) else "—", f"Llegaron entre {tol} días antes y {tol} días después."),
                  ("Mediana de días", dec(x["Dias_Cumplimiento"].median(), 0) if len(x) else "—", "Negativo = antes de la fecha programada."),
                  (f"Retraso > {LA.config.RETRASO_GRAVE_DIAS} días", miles(int((x["Dias_Cumplimiento"] > LA.config.RETRASO_GRAVE_DIAS).sum())), "")])
        st.caption(f"Días de anticipación o retraso de cada aplicación frente a la fecha que se le programó en la dosis anterior, como el PBI: "
                   f"días = fecha de aplicación − fecha programada; cumple entre −{tol} y +{tol}. El indicador del Tablero usa la misma ventana, "
                   "pero cuenta cada cita en la dosis que la programó y por año de tratamiento.")
        c1, c2, c3 = st.columns(3)
        with c1:
            barras(LA.conteo(x, "diagnostico_apl"), "diagnostico_apl", "Distribución por diagnóstico", "Total cumplimiento")
        with c2:
            barras(LA.conteo(x, "molecula_label"), "molecula_label", "Distribución por medicamento", "Total cumplimiento")
        with c3:
            barras(LA.conteo(x, "eapb_label"), "eapb_label", "Distribución por EAPB", "Total cumplimiento")
        c1, c2 = st.columns(2)
        with c1:
            cl = x["Clasificacion_Cumplimiento"].value_counts().reindex(LA.orden_clasificacion(), fill_value=0)
            fig = go.Figure(go.Bar(y=cl.index, x=cl.values, orientation="h", marker=dict(color=[COLOR_CLASE.get(k.split(" (")[0], GRIS) for k in cl.index], cornerradius=3),
                                   text=[f"{miles(n)} · {dec(100 * n / max(1, cl.sum()), 0)} %" for n in cl.values], textposition="outside", cliponaxis=False,
                                   textfont=dict(color=TINTA, size=11), hovertemplate="%{y}: %{x:,}<extra></extra>"))
            layout(fig, "Clasificación de cumplimiento", f"n = {miles(int(cl.sum()))} aplicaciones", 290,
                   yaxis=dict(autorange="reversed", title=None), xaxis=dict(title="Total cumplimiento", range=[0, max(1, float(cl.max())) * 1.35]), bargap=0.3)
            mostrar(fig)
        with c2:
            if len(x):
                d = x["Dias_Cumplimiento"].astype(int)
                lo, hi = int(max(d.min(), d.quantile(0.01))), int(min(d.max(), d.quantile(0.99)))
                v = d.clip(lo, hi).value_counts().sort_index()
                fig = go.Figure(go.Bar(x=v.index, y=v.values, marker=dict(color=[COLOR_CLASE["3. Exacto"] if abs(k) <= tol else GRIS for k in v.index]),
                                       hovertemplate="%{x} días: %{y:,} aplicaciones<extra></extra>"))
                fig.add_vrect(x0=-tol - 0.5, x1=tol + 0.5, fillcolor=comun.rgba("#4C9A2A", 0.08), line_width=0)
                layout(fig, "Distribución de días", f"Verde = dentro de ±{tol} días · extremos agrupados en {lo} y {hi}", 290,
                       xaxis=dict(title="Días frente a la fecha programada (negativo = antes)"), yaxis=dict(title="Aplicaciones"), bargap=0.1)
                mostrar(fig)
        mapa_calor(LA.matriz(x, "con_dosis", "Clasificacion_Cumplimiento", LA.orden_clasificacion()), "Distribución de días por consecutivo de dosis",
                   "Filas: número de dosis · columnas: clasificación del cumplimiento", "Clasificación")
        lp = lista_pacientes(x, VER_ID, ["Dias_Cumplimiento"]).rename(columns={"n": "Aplicaciones evaluadas", "Dias_Cumplimiento": "Máximo de días"})
        lista_en_desplegable("Pacientes con cumplimiento evaluado en el período", lp, "cumplimiento", "dl-cumpl")

    # ------------------------------------------------------------------------ 4 · Visor de pacientes
    if VISTA == "4 · Visor de pacientes":
        pors = sorted(A["pacienteojoreingreso"].dropna().astype(str).unique())
        c1, c2 = st.columns([1, 2])
        buscar = c1.text_input("Buscar paciente-ojo reingreso" + (" o documento" if VER_ID else ""), key="ap-buscar", placeholder="Ej.: 9000123OD0")
        if buscar:
            b = buscar.strip().lower()
            ok = A["pacienteojoreingreso"].astype(str).str.lower().str.contains(b, regex=False)
            if VER_ID:
                ok |= A["numero_doc"].astype(str).str.contains(b, regex=False)
            pors = sorted(A.loc[ok, "pacienteojoreingreso"].astype(str).unique())
        if not pors:
            st.warning("Ningún paciente-ojo coincide con la búsqueda o los filtros.")
            st.stop()
        por = c2.selectbox(f"Paciente-ojo reingreso ({miles(len(pors))})", pors, key="ap-por")
        x = APL[APL["pacienteojoreingreso"] == por].sort_values(["fecha_aplicacion", "con_dosis"])
        p = x.iloc[0]
        datos = [("Diagnóstico", p["diagnostico_apl"]), ("EAPB", p["eapb_label"]), ("Sexo", p.get("sexo", "")), ("Sede", p.get("sede", "")),
                 ("Aplicaciones", miles(len(x))), ("Egreso", p.get("egreso_causa") if pd.notna(p.get("egreso_causa")) else "—")]
        if VER_ID:
            datos = [("Nombre", f"{p.get('nombres', '')} {p.get('apellidos', '')}"), ("Documento", p.get("numero_doc", ""))] + datos
        st.markdown(" · ".join(f"**{k}:** {v}" for k, v in datos))
        t = pd.DataFrame({"Dosis": x["con_dosis"], "Fecha aplicación": x["fecha_aplicacion"].map(fecha), "Molécula": x["molecula_label"],
                          "Fecha programada (siguiente)": x["fecha_programacion"].map(fecha), "Programada en la dosis anterior": x["FechaProg_Anterior"].map(fecha),
                          "Días frente a lo programado": x["Dias_Cumplimiento"].round().astype("Int64"),
                          "Clasificación": x["Clasificacion_Cumplimiento"].replace("Sin dato", ""),
                          "Semanas desde la dosis anterior": x["Semanas_Entre_Dosis"].round().astype("Int64"), "Médico": x["medico"]})
        st.dataframe(t, hide_index=True, width="stretch")


# ############################################################################ B · ALERTAS DE APLICACIONES (EXCEL)
if SECCION == SECCIONES[1]:
    G_TODO = gestion.leer(PRESTADOR, llave=LLAVE)
    G_VIG = gestion.vigentes(G_TODO)
    GESTIONADAS = {(r.pacienteojoreingreso, pd.Timestamp(r.fecha_programada)) for r in G_VIG.itertuples() if pd.notna(r.fecha_programada)}
    with st.container(border=True):
        st.markdown("**⚙️ Parámetros del reporte**")
        c1, c2, c3, c4 = st.columns(4)
        corte_def = min(FMAX, date.today())
        INICIO = c1.date_input("Fecha inicio", value=(pd.Timestamp(corte_def) - pd.Timedelta(days=30)).date(), min_value=FMIN, max_value=FMAX_PROG,
                               format="DD/MM/YYYY", key="al-inicio", help="Filtro 1 · rango de la hoja Programación.")
        FIN = c2.date_input("Fecha fin", value=corte_def, min_value=FMIN, max_value=FMAX_PROG, format="DD/MM/YYYY", key="al-fin",
                            help="Filtro 1 · rango de la hoja Programación.")
        CORTE = c3.date_input("Fecha de corte", value=corte_def, min_value=FMIN, max_value=FMAX_PROG, format="DD/MM/YYYY", key="al-corte",
                              help="Filtro 2 · última cita programada de cada paciente-ojo con lo aplicado hasta esta fecha (Cumplen / No cumplen).")
        VENTANA = int(c4.number_input("Ventana (± días)", min_value=1, max_value=60, value=LA.tolerancia(), step=1, key="al-ventana",
                                      help="Aplica a todas las hojas."))
        incluir = st.toggle("Incluir paciente-ojo con egreso registrado en el formulario", value=True, key="ap-egreso",
                            help="Con egreso (por ejemplo «Seis meses última inyección») el paciente ya salió del programa; apáguelo para ver solo activos.")
    if INICIO > FIN:
        st.warning("La fecha inicio es posterior a la fecha fin.")
    PROG = LA.dosis_programadas(APL, INICIO, FIN)
    AL = LA.alertas(APL, CORTE, VENTANA)
    if not incluir and not AL.empty:
        AL = AL[AL["egreso_causa"].isna() | (AL["egreso_fecha"] > pd.Timestamp(CORTE))]
    K = LA.kpis_alertas(PROG, AL, GESTIONADAS)
    tarjetas([("Programación · registros", miles(K["prog_registros"]), f"Citas con fecha programada del {fecha(INICIO)} al {fecha(FIN)}."),
              (f"Cumplen (±{VENTANA} d)", miles(K["en_rango"]), "Última cita dentro de la ventana a la fecha de corte."),
              (f"No cumplen (> {VENTANA} d)", miles(K["retraso"]), "La última cita pasó hace más de la ventana sin una aplicación nueva."),
              ("No cumplen con gestión", miles(K["con_gestion"]), ""), ("No cumplen sin gestión", miles(K["sin_gestion"]), "")])
    VISTA = st.segmented_control("Hoja", list(PESTANAS_EXCEL), default=list(PESTANAS_EXCEL)[0], key="vista-alertas", label_visibility="collapsed") or list(PESTANAS_EXCEL)[0]
    encabezado(VISTA.split(" · ")[1], PESTANAS_EXCEL[VISTA], "#0A8FA3")

    def tabla_estado(al: pd.DataFrame, gestion_cols: bool) -> pd.DataFrame:
        al = al.copy()
        if gestion_cols:
            g = G_VIG.copy()
            if not g.empty:
                g["ultima_programada"] = pd.to_datetime(g["fecha_programada"])
                al = al.merge(g[["pacienteojoreingreso", "ultima_programada", "causa", "observacion", "gestionado_por", "registrado_en"]],
                              on=["pacienteojoreingreso", "ultima_programada"], how="left")
            for c in ("causa", "observacion", "gestionado_por", "registrado_en"):
                if c not in al:
                    al[c] = np.nan
        t = pd.DataFrame({"Paciente-ojo reingreso": al["pacienteojoreingreso"], "Molécula": al["molecula_label"], "Médico tratante": al["medico"],
                          "Fecha de programación": al["ultima_programada"].map(fecha), "Cod Dx": al["dx_ppal"], "Dx": al["diagnostico_apl"],
                          "EAPB": al["eapb_label"], "Días a la fecha de corte": al["dias"].round().astype("Int64"),
                          "Alerta": al["estado"].map(lambda e: LA.etiqueta_estado(e, VENTANA)), "Última aplicación": al["ultima_aplicacion"].map(fecha),
                          "Egreso registrado": al["egreso_causa"].fillna("")})
        if gestion_cols:
            t["Causa incumplimiento"] = al["causa"].fillna("").values
            t["Observaciones"] = al["observacion"].fillna("").values
            t["Gestionado por"] = al["gestionado_por"].fillna("").values
            t["Fecha gestión"] = al["registrado_en"].fillna("").astype(str).str[:16].str.replace("T", " ").values
        return con_identificacion(t, al)

    # ------------------------------------------------------------------------ 1 · Programación
    if VISTA == "1 · Programación":
        st.caption(f"Citas con fecha programada del {fecha(INICIO)} al {fecha(FIN)} (hoja «Programación» del Excel). «¿Ya asistió?» dice si hay una "
                   "aplicación posterior registrada.")
        if PROG.empty:
            st.info("No hay citas programadas en ese rango.")
        else:
            x = PROG.sort_values(["fecha_programacion", "pacienteojoreingreso"])
            sig = x["fecha_aplicacion_siguiente"]
            asistio = np.where(sig.notna(), "Sí · " + sig.dt.strftime("%d/%m/%Y").fillna(""),
                               np.where(x["fecha_programacion"] > pd.Timestamp(CORTE), "Cita futura", "Pendiente"))
            t = pd.DataFrame({"Paciente-ojo reingreso": x["pacienteojoreingreso"], "Molécula": x["molecula_label"], "Médico tratante": x["medico"],
                              "Fecha aplicación": x["fecha_aplicacion"].map(fecha), "Consecutivo dosis": x["con_dosis"], "Semana extensión": x["semana_extension"],
                              "Fecha programada": x["fecha_programacion"].map(fecha), "Cod Dx": x["dx_ppal"], "Dx": x["diagnostico_apl"],
                              "EAPB": x["eapb_label"], "¿Ya asistió?": asistio})
            t = con_identificacion(t, x)
            n_p = int((t["¿Ya asistió?"] == "Pendiente").sum())
            st.markdown(f"**{miles(len(t))} citas** · {miles(K['prog_por'])} paciente-ojo · **{miles(n_p)} pendientes**")
            st.dataframe(t, hide_index=True, width="stretch", height=480)
            descarga("programacion", t, "dl-prog")

    # ------------------------------------------------------------------------ 2 · Cumplen
    if VISTA == "2 · Cumplen":
        st.caption(f"Paciente-ojo cuya última cita programada está a ±{VENTANA} días de la fecha de corte {fecha(CORTE)} (hoja «Reporte Cumple N días»).")
        sub = AL[AL["estado"] == LA.EN_RANGO].sort_values("dias", key=lambda d: d.abs())
        t = tabla_estado(sub, False)
        st.markdown(f"**{miles(len(t))} paciente-ojo** · {dec(K['pct_en_rango'], 1)} % de los evaluados (cumplen + no cumplen)")
        st.dataframe(t, hide_index=True, width="stretch", height=420)
        descarga("cumplen", t, "dl-cumplen")
        with st.expander(f"Otros estados: cita futura ({miles(K['futura'])}) y sin fecha programada ({miles(K['sin_fecha'])})"):
            otros = AL[AL["estado"].isin([LA.FUTURA, LA.SIN_FECHA])].sort_values("dias", key=lambda d: d.abs())
            st.dataframe(tabla_estado(otros, False), hide_index=True, width="stretch")

    # ------------------------------------------------------------------------ 3 · No cumplen y gestión
    if VISTA == "3 · No cumplen y gestión":
        st.caption(f"Paciente-ojo cuya última cita programada pasó hace más de {VENTANA} días a la fecha de corte {fecha(CORTE)} sin una aplicación nueva "
                   "(hoja «Reporte No Cumple N días»), con la gestión registrada. Ordenado de lo más reciente a lo más antiguo.")
        sub = AL[AL["estado"] == LA.RETRASO].sort_values("dias")
        t = tabla_estado(sub, True)
        st.dataframe(t, hide_index=True, width="stretch", height=380)
        descarga("no_cumplen", t, "dl-nocumplen")
        st.markdown("##### Registrar gestión")
        if sub.empty:
            st.info("No hay paciente-ojo con retraso para gestionar.")
        else:
            opciones = {f"{r.pacienteojoreingreso} · cita {fecha(r.ultima_programada)} · {int(r.dias)} días"
                        + (" · ya gestionado" if (r.pacienteojoreingreso, r.ultima_programada) in GESTIONADAS else ""): (r.pacienteojoreingreso, r.ultima_programada)
                        for r in sub.itertuples()}
            with st.form("form-gestion", clear_on_submit=True):
                elegido = st.selectbox("Paciente-ojo con retraso", list(opciones), key="g-por")
                c1, c2 = st.columns(2)
                causa = c1.selectbox("Causa del incumplimiento", gestion.CAUSAS, index=None, placeholder="Elija una causa", key="g-causa")
                quien = c2.text_input("Gestionado por", value=st.session_state.get("g-quien-ultimo", ""), key="g-quien")
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
            st.caption("Cada gestión queda con quién la registró y cuándo, ligada a esa cita. No se borra: una corrección es un registro nuevo y vale el "
                       "más reciente. Una carga nueva del formulario no la afecta."
                       + (" En esta demostración los registros se guardan en el servidor de prueba y pueden perderse cuando se reinicia."
                          if META.get("sintetico") or META.get("es_demo") else ""))

    # ------------------------------------------------------------------------ 4 · Reportes
    if VISTA == "4 · Reportes":
        st.caption(f"Programación: citas del {fecha(INICIO)} al {fecha(FIN)} · Cumplen / No cumplen: paciente-ojo a la fecha de corte {fecha(CORTE)}, "
                   f"ventana ±{VENTANA} días (hoja «Reportes» del Excel). EAPB y médicos salen de los datos: uno nuevo aparece solo.")
        medidas = [("n", "N", miles), ("pct", "%", lambda v: f"{dec(v, 1)}%")]
        grupos = [("prog", "Programación"), ("cumplen", "Cumplen"), ("retraso", "No cumplen")]
        bloques = (("Reporte 1 — Por diagnóstico", "diagnostico_apl"), ("Reporte 2 — Por medicamento", "molecula_label"),
                   ("Reporte 3 — Por EAPB", "eapb_label"), ("Reporte 4 — Por médico tratante", "medico"))
        for fila in (bloques[:2], bloques[2:]):
            cols = st.columns(2)
            for col, (titulo, c) in zip(cols, fila):
                r = LA.reporte_por(AL, PROG, c, c)
                r.columns = pd.MultiIndex.from_tuples([tuple(k.split("_")) for k in r.columns])
                with col:
                    st.markdown(f"**{titulo}**")
                    st.markdown(comun.tabla_pbi(r, grupos=grupos, medidas=medidas, titulo_filas="Categoría", encabezado=""), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Reporte 5 — Últimas dosis** · citas programadas por consecutivo de dosis")
            d = LA.reporte_dosis(PROG)
            d.columns = pd.MultiIndex.from_tuples([("Programación", "n"), ("Programación", "pct")])
            st.markdown(comun.tabla_pbi(d, grupos=[("Programación", "Programación")], medidas=medidas, titulo_filas="Categoría", encabezado=""), unsafe_allow_html=True)
        with c2:
            st.markdown("**Reporte 6 — Causa de incumplimiento** · gestión vigente de los paciente-ojo que no cumplen")
            ret = AL[AL["estado"] == LA.RETRASO][["pacienteojoreingreso", "ultima_programada"]]
            g = G_VIG.copy()
            if not g.empty and not ret.empty:
                g["fecha_programada"] = pd.to_datetime(g["fecha_programada"])
                g = g.merge(ret, left_on=["pacienteojoreingreso", "fecha_programada"], right_on=["pacienteojoreingreso", "ultima_programada"])
            if g.empty or ret.empty:
                st.caption("Ningún paciente-ojo que no cumple tiene gestión registrada todavía.")
            else:
                cc = g["causa"].value_counts().reindex(gestion.CAUSAS, fill_value=0)
                cc = cc[cc > 0].rename("n").to_frame()
                cc["pct"] = 100 * cc["n"] / cc["n"].sum()
                cc.loc["Total"] = [cc["n"].sum(), 100.0]
                cc.columns = pd.MultiIndex.from_tuples([("Gestión", "n"), ("Gestión", "pct")])
                st.markdown(comun.tabla_pbi(cc, grupos=[("Gestión", "Gestiones")], medidas=medidas, titulo_filas="Causa", encabezado=""), unsafe_allow_html=True)

    # ------------------------------------------------------------------------ 5 · Gestión y causas
    if VISTA == "5 · Gestión y causas":
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(f"**Historial de gestiones** ({miles(len(G_TODO))} registros, del más reciente al más antiguo)")
            if G_TODO.empty:
                st.caption("Aún no hay gestiones registradas. Se registran en la hoja «No cumplen y gestión».")
            else:
                h = G_TODO.sort_values("registrado_en", ascending=False).assign(fecha_programada=lambda d: d["fecha_programada"].map(fecha))
                h = h.rename(columns={"registrado_en": "Registrado en", "pacienteojoreingreso": "Paciente-ojo reingreso", "fecha_programada": "Cita",
                                      "causa": "Causa", "observacion": "Observación", "gestionado_por": "Gestionado por"}).drop(columns="id")
                st.dataframe(h, hide_index=True, width="stretch", height=420)
                descarga("historial_gestion", h, "dl-hist")
        with c2:
            st.markdown("**Catálogo de causas**")
            st.dataframe(pd.DataFrame({"Causa": [gestion.principal(c) for c in gestion.CAUSAS],
                                       "Detalle": [c.split(" · ")[1] if " · " in c else "" for c in gestion.CAUSAS]}), hide_index=True, width="stretch")
