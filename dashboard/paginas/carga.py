"""Página «Cargar y procesar»: sube el formulario de un prestador y corre el pipeline desde la app.

El trabajo lo hace pipeline.ingest.registrar_entrega (valida, guarda la entrega versionada y procesa);
cada ejecución queda en la bitácora (pipeline/registro.py), que se ve en «Historial de ejecuciones».
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import comun
import logic as L
from pipeline import config, ingest


def pantalla_carga(corridas: list) -> None:
    """Cargar un insumo nuevo (datos reales): se valida, se guarda en la carpeta compartida y se procesa."""
    st.title("Cargar y procesar")
    st.markdown("Suba el libro del formulario de un prestador. Se **valida**, se **guarda** en la carpeta de datos "
                f"compartida (`{config.DATA_ROOT}`) y se **procesa**; al terminar el tablero muestra la nueva carga. "
                "Si algo falla, no se pierde ni se modifica ninguna carga anterior. Cada ejecución, exitosa o no, "
                "queda en el **Historial de ejecuciones**.")
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
                st.session_state["_aviso"] = f"Insumo cargado y procesado: {res['processed'].parent.name.upper()} · {res['processed'].name}."
                st.switch_page(comun.PAGINAS["tablero"])
    if corridas:
        st.markdown("##### Cargas disponibles")
        st.dataframe(pd.DataFrame([{"Prestador": str(c["meta"].get("prestador", "")).upper(), "Versión": c["meta"].get("version", "—"),
                                    "Generada": str(c["generado"])[:16].replace("T", " "), "Cargada por": c["meta"].get("cargado_por", "—"),
                                    "Costos": "Tabla de referencia" if c["meta"].get("costos_es_dummy") else (c["meta"].get("costos_fuente") or "—")} for c in corridas]),
                     hide_index=True)


pantalla_carga(L.listar_corridas())
