"""Página «Pipeline de datos»: ejecutar el proceso que lleva el formulario a las tablas del tablero, ver su log
mientras corre y consultar el historial de ejecuciones.

Dos formas de ejecutar:
  - Reprocesar una entrega guardada (data/raw/<prestador>/<versión>/): pipeline.ingest.reprocesar.
    Se habilita con VLM_EJECUCION_HABILITADA (por defecto, sí).
  - Cargar un formulario nuevo: pipeline.ingest.registrar_entrega (valida, guarda la entrega versionada y procesa).
    Se habilita con VLM_CARGA_HABILITADA (en la demostración pública está apagada: nadie puede subir archivos).
Cada ejecución, exitosa o no, queda en la bitácora (pipeline/registro.py). Las corridas anteriores a la bitácora
se muestran a partir de su metadata.json, marcadas como «sin bitácora».
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

import comun
import logic as L
from pipeline import config, ingest, registro


def correr(titulo: str, proceso: Callable[[Callable[[str], None]], Path]) -> None:
    """Ejecuta `proceso(en_vivo)` mostrando el log línea por línea; al terminar guarda el resultado en la sesión y recarga."""
    lineas: list = []
    with st.status(titulo, expanded=True) as estado:
        caja = st.empty()

        def en_vivo(linea: str) -> None:
            lineas.append(linea)
            caja.code("\n".join(lineas[-300:]), language="log")

        try:
            destino = proceso(en_vivo)
            estado.update(label="Proceso terminado", state="complete")
            st.session_state["ultima_ejecucion"] = {"ok": True, "log": "\n".join(lineas), "corrida": str(destino),
                                                    "mensaje": f"Proceso terminado: {destino.parent.name.upper()} · {destino.name}. "
                                                               "El tablero ya muestra estos datos."}
            st.session_state["corrida_ruta"] = str(destino)
        except ingest.CargaError as e:
            estado.update(label="El proceso no terminó", state="error")
            st.session_state["ultima_ejecucion"] = {"ok": False, "log": "\n".join(lineas), "mensaje": str(e)}
        except Exception as e:  # noqa: BLE001 -- se muestra completo para poder reportarlo
            estado.update(label="Error inesperado", state="error")
            st.session_state["ultima_ejecucion"] = {"ok": False, "log": "\n".join(lineas),
                                                    "mensaje": f"Error inesperado (avise al equipo técnico): {type(e).__name__}: {e}"}
    st.cache_data.clear()
    st.rerun()


def ejecutar_entrega_guardada() -> None:
    entregas = ingest.listar_entregas()
    if not entregas:
        st.info("No hay entregas guardadas en la carpeta de datos (`raw`). Cargue un formulario nuevo para crear la primera.")
        return
    nombres = [f'{e["prestador"].upper()} · {e["carpeta"]} · cargada por {e["manifest"].get("cargado_por", "—")}' for e in entregas]
    e = entregas[nombres.index(st.selectbox("Entrega", nombres, key="pl-entrega"))]
    man = e["manifest"]
    archivos = man.get("archivos", {})
    st.caption(f"Recibida el {comun.fecha(man.get('cargado_en') or man.get('fecha_recepcion'), hora=bool(man.get('cargado_en')))} · "
               f"versión del formulario {man.get('version_formulario', '—')} · archivos: " + (", ".join(archivos) or "—"))
    if man.get("filas_por_hoja"):
        st.caption("Filas por hoja: " + " · ".join(f"{h} {n:,}".replace(",", ".") for h, n in man["filas_por_hoja"].items()))
    if man.get("notas"):
        st.caption("Notas de la entrega: " + " · ".join(map(str, man["notas"])))
    previas = [c for c in L.listar_corridas() if str(c["meta"].get("prestador", "")).lower() == e["prestador"]
               and (c["meta"].get("entrega") or c["meta"].get("carpeta")) == e["carpeta"]]
    if previas:
        st.caption(f"Esta entrega ya se ha ejecutado {len(previas)} {'vez' if len(previas) == 1 else 'veces'} (la última, el "
                   f"{comun.fecha(max(c['generado'] for c in previas))}). Cada ejecución nueva se guarda como otra versión; las anteriores se conservan.")
    quien = st.text_input("Quién ejecuta", key="pl-quien", help="Queda en el historial de ejecuciones.")
    st.caption("Se recalcula todo a partir del formulario guardado. El resultado queda como una versión nueva, que aparece en el "
               "tablero solo si el proceso termina bien.")
    if st.button("Ejecutar pipeline", type="primary", key="pl-ejecutar", disabled=not quien.strip()):
        correr("Ejecutando el pipeline…", lambda en_vivo: ingest.reprocesar(e["ruta"], usuario=quien.strip(), en_vivo=en_vivo))


def cargar_formulario_nuevo() -> None:
    st.markdown("Suba el libro del formulario de un prestador. Se **valida**, se **guarda** como una entrega nueva en la carpeta "
                f"de datos (`{config.DATA_ROOT}`) y se **procesa**. Si algo falla, no se pierde ni se modifica ninguna carga anterior.")
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
    if st.button("Validar, guardar y ejecutar", type="primary", disabled=libro is None, key="up_boton"):
        if config.UPLOAD_PIN and pin != config.UPLOAD_PIN:
            st.error("Clave de carga incorrecta.")
            return
        correr("Validando y procesando el formulario…", lambda en_vivo: ingest.registrar_entrega(
            prestador=prestador or "", version=version, usuario=usuario, libro=libro.getvalue(), libro_nombre=libro.name,
            ecv=ecv.getvalue() if ecv else None, ecv_nombre=ecv.name if ecv else "ecv.xlsx", costos_modo=modo,
            costos=costos.getvalue() if costos else None, costos_nombre=costos.name if costos else "costos.xlsx",
            en_vivo=en_vivo)["processed"])


def historial() -> None:
    ejecuciones = registro.leer()
    con_registro = {str(Path(r.get("resultados") or r.get("destino")).resolve()) for r in ejecuciones if r.get("resultados") or r.get("destino")}
    filas = [{"id": r["id"], "Inicio": comun.fecha(r.get("inicio")), "_orden": r.get("inicio", ""), "Estado": "✅ Éxito" if r.get("estado") == "éxito" else "❌ Falla",
              "Origen": r.get("origen", "—"), "Prestador": str(r.get("prestador") or "—").upper(), "Versión": r.get("version") or "—",
              "Ejecutado por": r.get("usuario") or "—", "Duración (s)": r.get("duracion_s"), "Filas resultado": r.get("filas_mart"),
              "Avisos": r.get("avisos", 0), "Mensaje": r.get("mensaje", "")} for r in ejecuciones]
    for c in L.listar_corridas():
        if str(Path(c["ruta"]).resolve()) in con_registro:
            continue
        m = c["meta"]
        filas.append({"id": None, "Inicio": comun.fecha(c["generado"]), "_orden": c["generado"], "Estado": "✅ Éxito", "Origen": "Sin bitácora (desde la metadata)",
                      "Prestador": str(m.get("prestador", "—")).upper(), "Versión": m.get("version") or "—", "Ejecutado por": m.get("cargado_por") or "—",
                      "Duración (s)": None, "Filas resultado": m.get("filas_mart"), "Avisos": None, "Mensaje": ""})
    if not filas:
        st.info("Todavía no hay ejecuciones registradas.")
        return
    tabla = pd.DataFrame(filas).sort_values("_orden", ascending=False).reset_index(drop=True)
    for col, fmt in (("Duración (s)", "{:.1f}"), ("Filas resultado", "{:,.0f}"), ("Avisos", "{:.0f}")):
        tabla[col] = [fmt.format(v).replace(",", ".") if pd.notna(v) else "—" for v in pd.to_numeric(tabla[col], errors="coerce")]
    exitos = tabla[tabla["Estado"].str.contains("Éxito")]
    a, b, c = st.columns(3)
    a.metric("Ejecuciones registradas", len(tabla))
    b.metric("Última ejecución exitosa", exitos["Inicio"].iloc[0] if len(exitos) else "—")
    c.metric("Ejecuciones con falla", int((~tabla["Estado"].str.contains("Éxito")).sum()))
    st.dataframe(tabla.drop(columns=["id", "_orden"]), hide_index=True, use_container_width=True,
                 column_config={"Mensaje": st.column_config.TextColumn(width="large")})
    st.caption("«Avisos» cuenta las advertencias del proceso (p. ej. campos insuficientes para un indicador); se leen en el log.")
    st.markdown("##### Log de una ejecución")
    con_log = tabla[tabla["id"].notna()]
    if con_log.empty:
        st.caption("Las ejecuciones anteriores a la bitácora no tienen log. Las nuevas sí lo guardan.")
        return
    etiquetas = {f'{f["Inicio"]} · {f["Prestador"]} · {f["Estado"]}': f["id"] for _, f in con_log.iterrows()}
    elegida = st.selectbox("Ejecución", list(etiquetas), key="pl-log")
    st.code(registro.detalle(etiquetas[elegida]) or "Sin log guardado.", language="log")


st.title("Pipeline de datos")
st.markdown("El pipeline toma el **formulario** del prestador y lo convierte en las **tablas que alimentan el tablero**: valida las hojas, "
            "calcula adherencia, agudeza visual, OCT, costos y calidad de vida, mide la completitud y publica una corrida nueva. "
            "Cada ejecución, exitosa o no, queda en el historial con su log.")

ultima = st.session_state.pop("ultima_ejecucion", None)
if ultima:
    (st.success if ultima["ok"] else st.error)(ultima["mensaje"])
    with st.expander("Log de la ejecución", expanded=not ultima["ok"]):
        st.code(ultima["log"] or "Sin mensajes.", language="log")
    if ultima["ok"]:
        st.page_link(comun.PAGINAS["tablero"], label="Ver el tablero con estos datos", icon=":material/dashboard:")

st.subheader("Ejecutar")
opciones = ([("Reprocesar una entrega guardada", ejecutar_entrega_guardada)] if config.EJECUCION_HABILITADA else []) + \
           ([("Cargar un formulario nuevo", cargar_formulario_nuevo)] if config.CARGA_HABILITADA else [])
if not opciones:
    st.info("Esta instalación es de solo consulta: la ejecución del pipeline está deshabilitada.")
else:
    for pestana, (_, funcion) in zip(st.tabs([n for n, _ in opciones]), opciones):
        with pestana:
            funcion()

st.subheader("Historial de ejecuciones")
historial()
