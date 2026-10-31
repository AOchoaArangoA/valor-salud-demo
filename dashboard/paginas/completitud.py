"""Página «Completitud de datos», en dos partes:
  1. Formulario (datos de entrada): completitud por hoja y columna, y cruces entre hojas, tal como llegó el libro.
     Lo calcula el pipeline al procesar (pipeline/completitud.py) y queda en completitud_insumo.json.
  2. Resultados del proceso: qué tan completas quedaron las variables que usa el tablero (logic.completitud_resultados).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import comun
import logic as L
from pipeline import completitud, seguridad


@st.cache_data(show_spinner="Cargando datos…")
def _mart(ruta: str, marca: float, llave: bytes | None = None) -> pd.DataFrame:
    return L.cargar(Path(ruta), llave)[0]


def barra(titulo: str, ayuda: str = "") -> st.column_config.ProgressColumn:
    return st.column_config.ProgressColumn(titulo, min_value=0, max_value=100, format="%.1f %%", help=ayuda or None)




def _resultados(corrida: dict, llave) -> None:
    mart = _mart(str(corrida["ruta"]), (corrida["ruta"] / "metadata.json").stat().st_mtime, llave)
    res = L.completitud_resultados(mart)
    a, b, c = st.columns(3)
    a.metric("Paciente-ojo reingreso", f"{len(mart):,}".replace(",", "."))
    b.metric("Variables revisadas", len(res))
    c.metric("Variables completas (100 %)", int((res["% de quienes podían tenerlo"].round(1) >= 100).sum()))
    st.dataframe(res, hide_index=True, use_container_width=True,
                 column_config={"% del total": barra("% del total"),
                                "% de quienes podían tenerlo": barra("% de quienes podían tenerlo",
                                                                     "Para S52, S104 y año 2: solo cuenta a quienes ya llevan el tiempo de seguimiento necesario.")})
    st.caption("«% del total» usa a todos los paciente-ojo reingreso. «% de quienes podían tenerlo» descuenta a quienes todavía no cumplen "
               "el tiempo de seguimiento: un dato de S104 no puede faltar en alguien que lleva seis meses de tratamiento.")
    dq = corrida["meta"].get("calidad_insumo", {})
    if dq:
        st.markdown("##### Indicadores que dependen de campos opcionales")
        st.dataframe(pd.DataFrame([
            {"Indicador": "Anatomía sin líquido (retina seca) y respondedor", "Evaluable": "Sí" if dq.get("retina_seca_evaluable") else "No",
             "Dato que lo sostiene": f"OCT con líquido subretiniano: {dq.get('oct_srf_completo_pct', '—')} % con dato"},
            {"Indicador": "Cumplimiento de la fecha programada", "Evaluable": "Sí" if dq.get("cumplimiento_programacion_evaluable") else "No",
             "Dato que lo sostiene": f"Fecha programada: {dq.get('fecha_programacion_completa_pct', '—')} % con dato"},
        ]), hide_index=True, use_container_width=True)


st.title("Completitud de datos")
st.markdown("Qué tan completa llega la información del prestador y qué tan completa queda después del proceso. "
            "Sirve para saber, antes de leer un indicador, si el dato que lo sostiene está.")

CORRIDAS = L.listar_corridas()
if not CORRIDAS:
    st.info("Todavía no hay datos procesados.")
    st.stop()
etiquetas = [c["etiqueta"] for c in CORRIDAS]
pos = next((i for i, c in enumerate(CORRIDAS) if str(c["ruta"]) == st.session_state.get("corrida_ruta")), 0)
corrida = CORRIDAS[etiquetas.index(st.selectbox("Corrida de datos", etiquetas, index=pos))]
st.caption(f"Procesada el {comun.fecha(corrida['generado'])} · insumo: {corrida['meta'].get('insumo', '—')}")

t_form, t_res = st.tabs(["1 · Formulario (datos de entrada)", "2 · Resultados del proceso"])

with t_form:
    rep = completitud.leer(corrida["ruta"])
    if rep is None:
        st.info("Esta corrida se procesó antes de que existiera el reporte del formulario, así que no lo trae. Se genera "
                "automáticamente en cada ejecución nueva del pipeline: elija, por ejemplo, una corrida del prestador PRUEBA.")
    else:
        resumen, detalle = [], []
        for h in rep["hojas"]:
            oblig = [c for c in h["columnas"] if c["obligatoria"]]
            pct_oblig = sum(c["pct"] or 0 for c in oblig) / len(oblig) if oblig else None
            resumen.append({"Hoja": h["hoja"], "Filas": h["filas"], "Columnas": len(h["columnas"]),
                            "Completitud de columnas obligatorias": pct_oblig,
                            "Obligatorias incompletas": sum(1 for c in oblig if (c["pct"] or 0) < 100),
                            "Obligatorias ausentes": ", ".join(h["faltan_obligatorias"]) or "—"})
            detalle += [{"Hoja": h["hoja"], "Columna": c["columna"], "Obligatoria": "Sí" if c["obligatoria"] else "",
                         "Celdas con dato": c["con_dato"], "Completitud": c["pct"]} for c in h["columnas"]]
        resumen, detalle = pd.DataFrame(resumen), pd.DataFrame(detalle)
        a, b, c = st.columns(3)
        a.metric("Hojas revisadas", len(resumen))
        b.metric("Filas en total", f"{int(resumen['Filas'].sum()):,}".replace(",", "."))
        c.metric("Columnas obligatorias incompletas", int(resumen["Obligatorias incompletas"].sum()))
        st.dataframe(resumen, hide_index=True, use_container_width=True,
                     column_config={"Completitud de columnas obligatorias": barra("Completitud de columnas obligatorias",
                                                                                 "Promedio del % de celdas con dato en las columnas que el proceso exige.")})
        st.markdown("##### Cruces entre hojas")
        st.caption("«Registros que encuentran su llave»: p. ej. cada aplicación debe pertenecer a un paciente-ojo de la línea base. "
                   "«Cobertura»: p. ej. qué parte de los paciente-ojo de la línea base tiene al menos una aplicación.")
        if rep["cruces"]:
            cr = pd.DataFrame(rep["cruces"]).rename(columns={"tipo": "Tipo", "cruce": "Cruce", "llave": "Llave", "total": "Total",
                                                              "cumplen": "Cumplen", "no_cumplen": "No cumplen", "pct": "% que cumple"})
            st.dataframe(cr, hide_index=True, use_container_width=True, column_config={"% que cumple": barra("% que cumple")})
        st.markdown("##### Detalle por columna")
        hoja = st.selectbox("Hoja", resumen["Hoja"].tolist(), key="comp-hoja")
        solo_oblig = st.toggle("Solo columnas obligatorias", value=False, key="comp-oblig")
        d = detalle[detalle["Hoja"] == hoja]
        if solo_oblig:
            d = d[d["Obligatoria"] == "Sí"]
        st.dataframe(d.drop(columns="Hoja").sort_values("Completitud"), hide_index=True, use_container_width=True,
                     column_config={"Completitud": barra("Completitud")})
        st.caption(f"Reporte calculado el {comun.fecha(rep.get('generado'))}, sobre el libro tal como llegó (antes de cualquier cálculo).")

with t_res:
    llave = st.session_state.get("llave_datos") or (seguridad.llave_de_entorno() if seguridad.hay_cifrado() else None)
    if seguridad.carpeta_cifrada(corrida["ruta"]) and llave is None:
        st.info("Esta corrida está cifrada. Ábrala primero en el **Tablero** con su clave y vuelva a esta página.")
    else:
        _resultados(corrida, llave)
