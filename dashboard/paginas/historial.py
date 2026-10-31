"""Página «Historial de ejecuciones»: cada corrida del pipeline (exitosa o no) con su detalle.

Fuente: la bitácora (pipeline/registro.py). Las corridas que existían antes de la bitácora no tienen registro:
se muestran a partir de su metadata.json, marcadas como «sin bitácora».
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import comun
import logic as L
from pipeline import registro

st.title("Historial de ejecuciones")
st.markdown("Cada vez que se procesa un formulario queda un registro: quién lo cargó, cuándo, cuánto tardó y si terminó bien. "
            "Si falló, el mensaje explica por qué; la versión anterior de los datos sigue intacta.")

ejecuciones = registro.leer()
con_registro = {str(Path(r.get("resultados") or r.get("destino")).resolve()) for r in ejecuciones if r.get("resultados") or r.get("destino")}
filas = [{"id": r["id"], "Inicio": comun.fecha(r.get("inicio")), "_orden": r.get("inicio", ""), "Estado": "✅ Éxito" if r.get("estado") == "éxito" else "❌ Falla",
          "Origen": r.get("origen", "—"), "Prestador": str(r.get("prestador") or "—").upper(), "Versión": r.get("version") or "—",
          "Cargado por": r.get("usuario") or "—", "Duración (s)": r.get("duracion_s"), "Filas resultado": r.get("filas_mart"),
          "Avisos": r.get("avisos", 0), "Mensaje": r.get("mensaje", "")} for r in ejecuciones]
for c in L.listar_corridas():
    if str(Path(c["ruta"]).resolve()) in con_registro:
        continue
    m = c["meta"]
    filas.append({"id": None, "Inicio": comun.fecha(c["generado"]), "_orden": c["generado"], "Estado": "✅ Éxito", "Origen": "Sin bitácora (desde la metadata)",
                  "Prestador": str(m.get("prestador", "—")).upper(), "Versión": m.get("version") or "—", "Cargado por": m.get("cargado_por") or "—",
                  "Duración (s)": None, "Filas resultado": m.get("filas_mart"), "Avisos": None, "Mensaje": ""})

if not filas:
    st.info("Todavía no hay ejecuciones registradas.")
    st.stop()

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
st.caption("«Avisos» cuenta las advertencias del proceso (p. ej. campos insuficientes para un indicador); se leen en el detalle.")

st.markdown("##### Detalle de una ejecución")
con_log = tabla[tabla["id"].notna()]
if con_log.empty:
    st.caption("Las ejecuciones anteriores a la bitácora no tienen detalle. Las nuevas cargas sí lo guardan.")
else:
    etiquetas = {f'{f["Inicio"]} · {f["Prestador"]} · {f["Estado"]}': f["id"] for _, f in con_log.iterrows()}
    elegida = st.selectbox("Ejecución", list(etiquetas))
    texto = registro.detalle(etiquetas[elegida])
    st.code(texto or "Sin detalle guardado.", language="log")
