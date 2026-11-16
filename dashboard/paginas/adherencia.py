"""Página «Análisis de adherencia»: migración del Power BI 01-reporte-adherencia_v4 (plan aprobado el 14-nov-2026).

Cinco pestañas organizadas por la pregunta que responden (alternativa A del plan), en vez de las 12 hojas del PBI:
  1 · Población · 2 · Inicio y adherencia · 3 · Resultados · 4 · Adherencia y resultados · 5 · Carga de tratamiento.
La completitud y la calidad de vida no se repiten: ya están en sus páginas. Los cálculos viven en logic_adherencia.py
y se comparan con las medidas DAX en tests/test_adherencia.py.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import comun
import logic as L
import logic_adherencia as A

CAT, GRIS = comun.CAT, comun.GRIS
TINTA, TINTA2, VACIO = "#1B2430", "#5B6675", "#D9DEE5"
VERDE, AMBAR, ROJO = "#4C9A2A", "#E0A100", "#C0392B"
COLOR_SEXO = {"Femenino": CAT[3], "Masculino": CAT[0], "Sin dato": VACIO}
COLOR_AV = {"Mejora": VERDE, "Se mantiene": GRIS, "Empeora": ROJO, A.SIN_EVALUAR: VACIO}
COLOR_OCT = {"Entra al rango normal": VERDE, "Se mantiene ≤ 300": CAT[2], "Se mantiene > 300": AMBAR,
             "Sale del rango normal": ROJO, A.SIN_EVALUAR: VACIO}
COLOR_RESP = {"Respondedor": VERDE, "Respondedor parcial": AMBAR, "No respondedor": ROJO, A.SIN_EVALUAR: VACIO}
COLOR_ADH = {"Adherente": CAT[0], "No adherente": GRIS}
CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}
PESTANAS = {
    "1 · Población": "¿A quién tratamos?",
    "2 · Inicio y adherencia": "¿Empiezan a tiempo y completan la dosis de carga?",
    "3 · Resultados": "¿Mejoran la visión y la retina?",
    "4 · Adherencia y resultados": "¿Los pacientes adherentes logran mejores resultados?",
    "5 · Carga de tratamiento": "¿Cuánto tratamiento necesitan?",
}


def miles(x) -> str:
    return f"{int(x):,}".replace(",", ".")


def dec(x, d=1) -> str:
    return "—" if pd.isna(x) else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def layout(fig, titulo: str, subtitulo: str, alto: int, **kw) -> None:
    """Formato del Tablero (comun.base_layout) más una línea de contexto debajo del título: el n y de dónde sale."""
    comun.base_layout(fig, titulo, alto, **kw)
    lineas = textwrap.wrap(subtitulo, 62) or [subtitulo]   # svg no ajusta el texto: se parte a mano (celular y columnas angostas)
    extra = 18 * len(lineas) + 2
    fig.layout.title.text += "".join(f"<br><span style='font-size:12px;color:{TINTA2}'>{l}</span>" for l in lineas)
    fig.update_layout(height=fig.layout.height + extra, margin_t=fig.layout.margin.t + extra, legend_traceorder="normal")
    if fig.layout.legend and fig.layout.showlegend:
        fig.update_layout(legend_y=fig.layout.legend.y - extra / fig.layout.height)


def paso_redondo(x: float) -> float:
    """1, 2 o 5 × 10^k más cercano por arriba (marcas de eje parejas: 0, 100, 200…)."""
    if x <= 0:
        return 1.0
    base = 10 ** np.floor(np.log10(x))
    return float(next(m * base for m in (1, 2, 5, 10) if m * base >= x))


def mostrar(fig) -> None:
    st.plotly_chart(fig, width="stretch", config=CONFIG)


def sin_datos(que: str) -> None:
    st.info(f"Sin datos para {que} con los filtros actuales.")


def etiqueta_dx(t: pd.DataFrame, col: str = "fila", n: str = "total") -> list:
    return [f"{d} (n = {miles(k)})" for d, k in zip(t[col], t[n])]


def barras_100(t: pd.DataFrame, colores: dict, titulo: str, subtitulo: str) -> None:
    """Barras horizontales 100% apiladas por diagnóstico (salida de A.reparto); el % se escribe en los tramos ≥ 7%."""
    if t.empty:
        return sin_datos(titulo.lower())
    filas = list(dict.fromkeys(t["fila"]))
    totales = t.groupby("fila")["total"].first().reindex(filas)
    ylab = {f: f"{f} (n = {miles(k)})" for f, k in totales.items()}
    fig = go.Figure()
    for cat in t["categoria"].cat.categories:
        x = t[t["categoria"] == cat].set_index("fila").reindex(filas)
        fig.add_bar(y=[ylab[f] for f in filas], x=x["pct"].fillna(0), name=str(cat), orientation="h",
                    marker=dict(color=colores.get(str(cat), GRIS), line=dict(color="#fff", width=2)),
                    text=[f"{dec(p, 0)} %" if p >= 7 else "" for p in x["pct"].fillna(0)], textposition="inside",
                    insidetextanchor="middle", textfont=dict(color="#fff" if str(cat) not in (A.SIN_EVALUAR, "Se mantiene") else TINTA, size=11),
                    customdata=np.c_[x["n"].fillna(0)], hovertemplate="%{y}<br>" + str(cat) + ": %{x:.1f} % (%{customdata[0]:,.0f})<extra></extra>")
    layout(fig, titulo, subtitulo, 70 + 46 * len(filas), barmode="stack", xaxis=dict(range=[0, 100], ticksuffix=" %", title=None),
           yaxis=dict(autorange="reversed", title=None), bargap=0.3)
    mostrar(fig)


def histograma(serie: pd.Series, ancho: float, titulo: str, eje: str, color: str = CAT[0]) -> None:
    h = A.intervalos(serie, ancho)
    if h.empty:
        return sin_datos(titulo.lower())
    fig = go.Figure(go.Bar(x=h["centro"], y=h["n"], width=ancho * 0.92, marker=dict(color=color, cornerradius=3),
                           customdata=np.c_[h["centro"] - ancho / 2, h["centro"] + ancho / 2, h["pct"]],
                           hovertemplate="De %{customdata[0]:g} a %{customdata[1]:g}: %{y:,} POR (%{customdata[2]:.1f} %)<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=TINTA, width=1.5, dash="dot"))
    v = pd.to_numeric(serie, errors="coerce").dropna()
    layout(fig, titulo, f"n = {miles(len(v))} POR · intervalos de {dec(ancho, 0)} · mediana {dec(v.median())} · línea punteada = sin cambio", 300,
           xaxis=dict(title=eje), yaxis=dict(title="POR"), bargap=0.05)
    mostrar(fig)


def violin(df: pd.DataFrame, col: str, titulo: str, eje: str, recorte: float = 0.99) -> None:
    """Violín con su caja y bigotes por diagnóstico (el mismo formato de la Metodología)."""
    v = df[["diagnostico", col]].assign(**{col: pd.to_numeric(df[col], errors="coerce")}).dropna()
    if v.empty:
        return sin_datos(titulo.lower())
    fig = go.Figure()
    for i, dx in enumerate(A.orden_dx(v)):
        x = v.loc[v["diagnostico"] == dx, col]
        fig.add_violin(y=x, name=f"{dx}<br>n = {miles(len(x))}", line=dict(color=CAT[i % len(CAT)], width=1.5),
                       fillcolor=comun.rgba(CAT[i % len(CAT)], .18), box=dict(visible=True, width=.25, fillcolor="#fff", line=dict(color=TINTA, width=1)),
                       meanline=dict(visible=False), points=False, spanmode="hard", showlegend=False,
                       hoverinfo="y")
    tope = float(v[col].quantile(recorte))
    layout(fig, titulo, f"n = {miles(len(v))} POR · la caja va del cuartil 1 al 3; la línea es la mediana · eje recortado en el percentil {int(recorte * 100)} ({dec(tope, 0)})",
           340, yaxis=dict(title=eje, range=[min(0, float(v[col].min())), tope * 1.05]), xaxis=dict(title=None))
    mostrar(fig)


def tabla_resumen(t: pd.DataFrame, unidad: str) -> None:
    t = t.copy()
    num = [c for c in t.columns if c != "diagnostico"]
    for c in num:
        t[c] = t[c].map(lambda x, c=c: miles(x) if c.startswith("n") and pd.notna(x) else dec(x))
    t = t.rename(columns=lambda c: c.replace("diagnostico", "Diagnóstico").replace("promedio", "Promedio").replace("mediana", "Mediana"))
    st.dataframe(t, hide_index=True, width="stretch")
    st.caption(f"Valores en {unidad}. n = paciente-ojo reingreso con dato.")


VENN_NOMBRES = [(0.08, 0.13, "left"), (0.14, 0.86, "left"), (0.86, 0.86, "right"), (0.92, 0.13, "right")]


def _elipse(cx, cy, w, h, ang, n=120) -> str:
    t, a = np.linspace(0, 2 * np.pi, n), np.radians(ang)
    x, y = w / 2 * np.cos(t), h / 2 * np.sin(t)
    xs, ys = cx + x * np.cos(a) - y * np.sin(a), cy + x * np.sin(a) + y * np.cos(a)
    return "M " + " L ".join(f"{u:.4f},{v:.4f}" for u, v in zip(xs, ys)) + " Z"


def venn_antecedentes(df: pd.DataFrame) -> None:
    zonas, totales, ninguno = A.venn_antecedentes(df)
    nombres, total = list(A.ANTECEDENTES.values()), len(df)
    colores = [CAT[0], CAT[1], CAT[2], CAT[3]]
    fig = go.Figure()
    for (cx, cy, w, h, ang), color in zip(A.VENN_ELIPSES, colores):
        fig.add_shape(type="path", path=_elipse(cx, cy, w, h, ang), fillcolor=comun.rgba(color, .16), line=dict(color=color, width=2))
    for clave, (x, y) in A.VENN_ZONAS.items():
        n = zonas[clave]
        cuales = " + ".join(nm for nm, b in zip(nombres, clave) if b == "1")
        fig.add_scatter(x=[x], y=[y], mode="text", text=[f"<b>{miles(n)}</b><br>{dec(100 * n / total, 1)} %" if total else "0"],
                        textfont=dict(size=11, color=TINTA), showlegend=False,
                        hovertemplate=f"{cuales}<br>{miles(n)} POR ({dec(100 * n / total if total else 0, 1)} %)<extra></extra>")
    for (x, y, lado), nm, color in zip(VENN_NOMBRES, nombres, colores):
        fig.add_annotation(x=x, y=y, text=f"<b>{nm}</b><br>{miles(totales[nm])} ({dec(100 * totales[nm] / total if total else 0, 0)} %)",
                           showarrow=False, xanchor=lado, font=dict(size=12, color=color), align=lado)
    layout(fig, "Antecedentes clínicos: diabetes, HTA, dislipidemia e insulina",
           f"n = {miles(total)} POR · cada zona cuenta los POR con exactamente esa combinación · {miles(ninguno)} sin ninguno de los cuatro", 420,
           xaxis=dict(visible=False, range=[0, 1]), yaxis=dict(visible=False, range=[0.02, 0.98], scaleanchor="x", scaleratio=1))
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")
    mostrar(fig)


# ============================================================================ datos
@st.cache_data(show_spinner="Preparando el análisis de adherencia…")
def _datos(ruta: str, marca: float, llave: bytes | None = None) -> pd.DataFrame:
    mart, _ = L.cargar(Path(ruta), llave)
    return A.cargar(Path(ruta), mart, llave)


CORRIDA, MART, META, LLAVE = comun.elegir_corrida()
st.sidebar.markdown("---")
st.sidebar.markdown("### Filtros")
MASCARA = comun.filtros_comunes(MART)
TODO = _datos(str(CORRIDA["ruta"]), (CORRIDA["ruta"] / "metadata.json").stat().st_mtime, LLAVE)
df = TODO[MASCARA.values].reset_index(drop=True)
st.sidebar.markdown("---")
st.sidebar.metric("Paciente-ojo reingreso en el filtro", miles(len(df)))
st.sidebar.caption(f"Prestador: **{str(META.get('prestador', '')).upper()}** · corrida {comun.fecha(META.get('generado'))}")

st.title("Análisis de adherencia")
st.caption("Adherencia al tratamiento y resultados clínicos por diagnóstico. Cada cifra cuenta paciente-ojo reingreso (POR).")
if df.empty:
    st.warning("Los filtros no dejan ningún paciente-ojo reingreso.")
    st.stop()

VISTA = st.segmented_control("Pestaña", list(PESTANAS), default=list(PESTANAS)[0], key="vista-adh", label_visibility="collapsed") or list(PESTANAS)[0]
st.markdown(f'<div class="nivel" style="--c:{CAT[0]}"><h3>{VISTA.split(" · ")[1]}</h3><p>{PESTANAS[VISTA]}</p></div>', unsafe_allow_html=True)


def selector_semana(clave: str, opciones=A.SEMANAS_RESULTADO, texto="Semana") -> int:
    v = st.segmented_control(texto, opciones, default=opciones[0], key=clave, format_func=lambda s: f"Semana {s}") or opciones[0]
    return int(v)


# ============================================================================ 1 · Población
if VISTA == "1 · Población":
    c = A.conteos(df)
    k1, k2, k3 = st.columns(3)
    k1.metric(L.N_PAC, miles(c["pacientes"]))
    k2.metric(L.N_PO, miles(c["po"]))
    k3.metric(L.N_POR, miles(c["por"]))
    crudo = A.conteos_formulario(CORRIDA["ruta"])
    if crudo and crudo.get("lineabase"):
        st.caption(f"En el formulario llegaron {miles(crudo['pacientes'])} pacientes y {miles(crudo['lineabase'])} registros de línea de base; "
                   f"después de la limpieza quedan {miles(len(MART))} POR, y {miles(c['por'])} cumplen los filtros.")

    col1, col2 = st.columns(2)
    with col1:   # (2) diagnóstico y sexo
        t = A.por_dx_sexo(df)
        filas = A.orden_dx(df)
        fig = go.Figure()
        for sexo in t["categoria"].cat.categories:
            x = t[t["categoria"] == sexo].set_index("fila").reindex(filas)
            fig.add_bar(y=filas, x=x["n"].fillna(0), name=str(sexo), orientation="h",
                        marker=dict(color=COLOR_SEXO.get(str(sexo), GRIS), line=dict(color="#fff", width=2)),
                        text=[f"{miles(n)} ({dec(p, 0)} %)" if n else "" for n, p in zip(x["n"].fillna(0), x["pct"].fillna(0))],
                        textposition="inside", insidetextanchor="middle", textfont=dict(color="#fff", size=11),
                        hovertemplate="%{y} · " + str(sexo) + ": %{x:,} POR<extra></extra>")
        layout(fig, "Paciente-ojo reingreso por diagnóstico y sexo", f"n = {miles(len(df))} POR · etiqueta: número (% dentro del diagnóstico)",
               70 + 46 * len(filas), barmode="stack", yaxis=dict(autorange="reversed"), xaxis=dict(title="POR"), bargap=0.3)
        mostrar(fig)
    with col2:   # (3) pirámide de edad y sexo
        p = A.piramide(df)
        edades = list(p["Grupo_edad"].cat.categories)
        fig = go.Figure()
        for sexo, signo in (("Masculino", -1), ("Femenino", 1)):
            x = p[p["sexo"] == sexo].set_index("Grupo_edad").reindex(edades)["n"].fillna(0)
            fig.add_bar(y=edades, x=signo * x, name=sexo, orientation="h", marker=dict(color=COLOR_SEXO[sexo], line=dict(color="#fff", width=1)),
                        text=[miles(v) if v else "" for v in x], textposition="outside", textfont=dict(color=TINTA, size=11),
                        customdata=x, hovertemplate="%{y} · " + sexo + ": %{customdata:,} POR<extra></extra>")
        tope = float(p["n"].max()) * 1.25 if len(p) else 1
        paso = paso_redondo(tope / 3)
        ticks = [v for v in np.arange(-np.floor(tope / paso) * paso, tope + 1e-9, paso)]
        layout(fig, "Pirámide de edad: paciente-ojo reingreso por grupo de edad y sexo", "Hombres a la izquierda, mujeres a la derecha · grupos de edad del proceso",
               320, barmode="relative", bargap=0.15, yaxis=dict(title="Edad (años)"),
               xaxis=dict(range=[-tope, tope], tickvals=ticks, ticktext=[miles(abs(v)) for v in ticks], title="POR"))
        mostrar(fig)

    st.markdown("##### Hábitos")
    h = A.habitos(df)
    cols = st.columns(2)
    for col, habito in zip(cols, ("Tabaquismo", "Actividad física")):
        with col:
            t = h[h["habito"] == habito]
            cats = [str(c) for c in t["categoria"].cat.categories if (t["categoria"].astype(str) == str(c)).any()]
            fig = go.Figure()
            for sexo in ("Femenino", "Masculino"):
                x = t[t["sexo"] == sexo].assign(categoria=lambda d: d["categoria"].astype(str)).set_index("categoria").reindex(cats)
                fig.add_bar(y=cats, x=x["pct"].fillna(0), name=sexo, orientation="h", marker=dict(color=COLOR_SEXO[sexo], cornerradius=3),
                            text=[f"{dec(v, 0)} %" for v in x["pct"].fillna(0)], textposition="outside", textfont=dict(color=TINTA, size=11),
                            customdata=x["n"].fillna(0), hovertemplate="%{y} · " + sexo + ": %{x:.1f} % (%{customdata:,.0f} POR)<extra></extra>")
            layout(fig, habito, "% de paciente-ojo reingreso dentro de cada sexo", 60 + 50 * len(cats), barmode="group",
                   yaxis=dict(autorange="reversed"), xaxis=dict(range=[0, 105], ticksuffix=" %"), bargap=0.25, bargroupgap=0.08)
            mostrar(fig)

    col1, col2 = st.columns(2)
    with col1:   # (5) antecedentes clínicos: diagrama de Venn de 4 conjuntos (como la hoja 2b del PBI)
        venn_antecedentes(df)
    with col2:   # (6) medicamento en línea de base
        barras_100(A.medicamento_por_dx(df), {m: CAT[i % len(CAT)] for i, m in enumerate(sorted(df["medicamento_label"].astype(str).unique()))},
                   "Medicamento en línea de base por diagnóstico", "% de paciente-ojo reingreso dentro de cada diagnóstico")

    # (7) tratamiento previo
    por_med, alguno = A.tratamiento_previo(df)
    if por_med.empty:
        st.info("La corrida no trae tratamiento previo (columnas tp_* de la línea de base vacías).")
    else:
        filas = [d for d in A.orden_dx(df) if d in set(alguno["diagnostico"])]
        al = alguno.set_index("diagnostico").reindex(filas)
        ylab = [f"{d} · {dec(al.loc[d, 'pct'], 0)} % con previo" for d in filas]
        fig = go.Figure()
        for i, med in enumerate(A.TRATAMIENTOS_PREVIOS.values()):
            x = por_med[por_med["medicamento"] == med].set_index("diagnostico").reindex(filas)["n"].fillna(0)
            if x.sum():
                fig.add_bar(y=ylab, x=x, name=med, orientation="h", marker=dict(color=CAT[i % len(CAT)], line=dict(color="#fff", width=2)),
                            hovertemplate="%{y}<br>" + med + ": %{x:,} POR<extra></extra>")
        layout(fig, "Tratamiento previo por diagnóstico y medicamento",
               f"POR que recibieron cada medicamento antes de entrar al programa; un POR puede tener varios · {miles(int(alguno['con_previo'].sum()))} de {miles(len(df))} con algún tratamiento previo",
               70 + 46 * len(filas), barmode="stack", yaxis=dict(autorange="reversed"), xaxis=dict(title="POR"), bargap=0.3)
        mostrar(fig)


# ============================================================================ 2 · Inicio y adherencia
if VISTA == "2 · Inicio y adherencia":
    adh = A.adherencia_semanas(df)
    cols = st.columns(3)
    for col, (s, (pct, si, n)) in zip(cols, adh.items()):
        col.metric(f"{L.N_ADH} · semana {s}", f"{dec(pct)} %", help=f"{miles(si)} adherentes de {miles(n)} POR evaluados")
    st.caption("Adherente: recibió al menos 3 aplicaciones hasta la semana indicada (al menos 6 en OVR), la misma regla del proceso.")

    s = selector_semana("sem-adh", A.SEMANAS_ADHERENCIA, "Semana de adherencia")
    t = A.adherencia_por_dx(df, s)
    if t.empty:
        sin_datos("la adherencia")
    else:
        fig = go.Figure(go.Bar(y=etiqueta_dx(t, "diagnostico", "n"), x=t["pct"], orientation="h", marker=dict(color=CAT[0], cornerradius=3),
                               text=[f"{dec(p)} %" + (f" · {dec(d)} dosis en promedio" if pd.notna(d) else "") for p, d in zip(t["pct"], t["dosis"])],
                               textposition="inside", insidetextanchor="end", textfont=dict(color="#fff", size=11),
                               customdata=np.c_[t["adherentes"], t["n"]],
                               hovertemplate="%{y}: %{x:.1f} % (%{customdata[0]:,.0f} de %{customdata[1]:,.0f})<extra></extra>"))
        total = adh[s]
        fig.add_vline(x=total[0], line=dict(color=TINTA, width=1.2, dash="dot"))
        layout(fig, f"{L.N_ADH} a la semana {s} por diagnóstico",
               f"% de POR adherentes y dosis promedio aplicadas hasta esa semana · línea punteada = total ({dec(total[0])} %)",
               80 + 46 * len(t), yaxis=dict(autorange="reversed"), xaxis=dict(range=[0, 100], ticksuffix=" %"), bargap=0.35)
        mostrar(fig)

    st.markdown("##### Oportunidad de inicio del tratamiento")
    col1, col2 = st.columns([3, 2])
    with col1:
        violin(df, "Oportunidad_inicio_tto", "Días del diagnóstico a la primera inyección", "Días")
    with col2:
        tabla_resumen(A.resumen_numerico(df, "Oportunidad_inicio_tto"), "días")


# ============================================================================ 3 · Resultados
if VISTA == "3 · Resultados":
    s = selector_semana("sem-res")
    col1, col2 = st.columns(2)
    with col1:
        barras_100(A.clase_av_por_dx(df, s), COLOR_AV, f"Cambio de agudeza visual a la semana {s}",
                   "Mejora: gana más de 5 letras · Empeora: pierde más de 5 · % dentro de cada diagnóstico")
    with col2:
        histograma(df[f"dif_lts_sem{s}"], 5, f"Diferencia en letras ETDRS a la semana {s}", "Cambio frente a la línea base (letras)")
    col1, col2 = st.columns(2)
    with col1:
        barras_100(A.clase_oct_por_dx(df, s), COLOR_OCT, f"Cambio en el grosor de la retina (OCT) a la semana {s}",
                   "Rango normal: ≤ 300 µm · % dentro de cada diagnóstico")
    with col2:
        histograma(df[f"dif_micras_sem{s}"], 25, f"Diferencia en micras a la semana {s}", "Cambio frente a la línea base (µm)", CAT[2])
    col1, col2 = st.columns(2)
    with col1:   # (14) retina seca
        t = A.retina_seca_por_dx(df, s)
        t = t[t["evaluados"] > 0]
        if t.empty:
            sin_datos(L.N_SECA.lower())
        else:
            fig = go.Figure(go.Bar(y=etiqueta_dx(t, "diagnostico", "evaluados"), x=t["pct"], orientation="h", marker=dict(color=CAT[2], cornerradius=3),
                                   text=[f"{dec(p)} %" for p in t["pct"]], textposition="outside", textfont=dict(color=TINTA, size=11), cliponaxis=False,
                                   customdata=np.c_[t["secos"], t["evaluados"]],
                                   hovertemplate="%{y}: %{x:.1f} % (%{customdata[0]:,.0f} de %{customdata[1]:,.0f})<extra></extra>"))
            layout(fig, f"{L.N_SECA} a la semana {s}", f"% entre los POR con OCT evaluada · {miles(int(t['sin_evaluar'].sum()))} POR sin evaluar no entran",
                   80 + 46 * len(t), yaxis=dict(autorange="reversed"), xaxis=dict(range=[0, 115], ticksuffix=" %"), bargap=0.35)
            mostrar(fig)
    with col2:
        barras_100(A.respondedor_por_dx(df), COLOR_RESP, "Respuesta al tratamiento un mes después de la 3ª dosis",
                   "Se mide a la semana 16; no cambia con el selector · % dentro de cada diagnóstico")


# ============================================================================ 4 · Adherencia y resultados
if VISTA == "4 · Adherencia y resultados":
    s = selector_semana("sem-cruce")
    t_todo, pct_sin = A.cruce_av_oct(df, s)
    t = t_todo.drop(index=A.SIN_EVALUAR, columns=A.SIN_EVALUAR, errors="ignore")
    fuera = int(t_todo.values.sum() - t.values.sum())
    if t.empty or t.values.sum() == 0:
        sin_datos("el cruce de agudeza visual y OCT")
    else:
        z = t.values
        fig = go.Figure(go.Heatmap(z=z, x=list(t.columns), y=list(t.index), colorscale=[[0, "#F3F6FA"], [1, CAT[0]]], showscale=False,
                                   text=[[miles(v) for v in fila] for fila in z], texttemplate="%{text}", textfont=dict(size=12),
                                   hovertemplate="AV: %{y}<br>OCT: %{x}<br>%{z:,} POR<extra></extra>", xgap=2, ygap=2))
        layout(fig, f"Cambio de agudeza visual × cambio en OCT a la semana {s}",
               f"POR con AV y OCT evaluadas ({miles(int(t.values.sum()))}) · quedan fuera {miles(fuera)} sin alguna de las dos; {dec(pct_sin)} % no tiene AV evaluada",
               80 + 56 * len(t), xaxis=dict(title="Cambio en OCT", side="bottom"), yaxis=dict(title="Cambio de AV", autorange="reversed"))
        mostrar(fig)

    st.markdown("##### Resultados según la adherencia a la dosis de carga (semana 16)")
    r = A.resultados_por_adherencia(df, s)
    if r.empty:
        sin_datos("la comparación por adherencia")
    else:
        cols = st.columns(3)
        for col, (met, titulo, eje, sufijo) in zip(cols, (("pct_mejora", f"% que mejora la AV a la semana {s}", "%", " %"),
                                                         ("pct_seca", f"% con {L.N_SECA[0].lower() + L.N_SECA[1:]} a la semana {s}", "%", " %"),
                                                         ("letras", f"Cambio promedio de letras a la semana {s}", "Letras", ""))):
            with col:
                fig = go.Figure()
                dxs = list(r["diagnostico"].cat.categories)
                for grupo in ("Adherente", "No adherente"):
                    x = r[r["grupo"] == grupo].set_index("diagnostico").reindex(dxs)
                    nn = x["n_oct"] if met == "pct_seca" else x["n_av"] if met == "pct_mejora" else x["n"]
                    fig.add_bar(y=dxs, x=x[met], name=grupo, orientation="h", marker=dict(color=COLOR_ADH[grupo], cornerradius=3),
                                text=[dec(v) + sufijo if pd.notna(v) else "" for v in x[met]], textposition="outside", textfont=dict(color=TINTA, size=11),
                                cliponaxis=False, customdata=nn.fillna(0),
                                hovertemplate="%{y} · " + grupo + ": %{x:.1f}" + sufijo + " (n = %{customdata:,.0f})<extra></extra>")
                vals = r[met].dropna()
                rango = [min(0, float(vals.min()) * 1.3), max(0, float(vals.max())) * 1.3] if len(vals) else None
                layout(fig, titulo, "Adherente: completó la carga a la semana 16", 90 + 52 * len(dxs), barmode="group",
                       yaxis=dict(autorange="reversed"), xaxis=dict(title=eje, range=rango, zeroline=True, zerolinecolor="#C9CFD8"), bargap=0.25)
                mostrar(fig)
        st.caption("Muestra asociación, no causalidad: adherentes y no adherentes pueden diferir en otras características.")


# ============================================================================ 5 · Carga de tratamiento
if VISTA == "5 · Carga de tratamiento":
    s = selector_semana("sem-ext", [52, 104])
    col1, col2 = st.columns([3, 2])
    with col1:
        violin(df, f"extension_sem{s}", f"Extensión del tratamiento a la semana {s}", "Semanas entre las dos últimas dosis")
    with col2:
        tabla_resumen(A.resumen_numerico(df, f"extension_sem{s}"), "semanas")

    st.markdown("##### Inyecciones por año de tratamiento")
    d = A.distribucion_inyecciones(df)
    col1, col2 = st.columns([3, 2])
    with col1:
        if d.empty or d["n"].sum() == 0:
            sin_datos("las inyecciones por año")
        else:
            fig = go.Figure()
            for i, anio in enumerate(("Año 1", "Año 2")):
                x = d[d["anio"] == anio]
                fig.add_bar(x=x["inyecciones"], y=x["pct"], name=f"{anio} (n = {miles(x['n'].sum())})", marker=dict(color=(CAT[0], CAT[1])[i], cornerradius=3),
                            customdata=x["n"], hovertemplate="%{x} inyecciones: %{y:.1f} % (%{customdata:,} POR)<extra></extra>")
            layout(fig, "Número de inyecciones en el año 1 y en el año 2", "% de POR con 2 años de seguimiento posible (mismo universo del Tablero)", 320,
                   barmode="group", xaxis=dict(title="Inyecciones en el año", dtick=1), yaxis=dict(title="% de POR", ticksuffix=" %"), bargap=0.2)
            mostrar(fig)
    with col2:
        r = A.resumen_inyecciones(df)
        t = pd.DataFrame({"Diagnóstico": r["diagnostico"], "n": r["n año 1"].map(lambda x: miles(x) if pd.notna(x) else "—"),
                          "Año 1": [f"{dec(a)} / {dec(b)}" for a, b in zip(r["promedio año 1"], r["mediana año 1"])],
                          "Año 2": [f"{dec(a)} / {dec(b)}" for a, b in zip(r["promedio año 2"], r["mediana año 2"])]})
        st.dataframe(t, hide_index=True, width="stretch")
        st.caption("Inyecciones por paciente-ojo reingreso: promedio / mediana. n = POR con 2 años de seguimiento posible.")
