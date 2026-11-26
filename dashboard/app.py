"""Valor en Salud (retina) — punto de entrada de la aplicación.

Enruta las páginas con st.navigation:
  - Tablero                      -> dashboard/tablero.py  (los 6 niveles de gestión y la metodología)
  - Seguimiento de aplicaciones  -> dashboard/paginas/aplicaciones.py  (PBI de aplicaciones + Excel de alertas y gestión)
  - Análisis de adherencia       -> dashboard/paginas/adherencia.py  (migración del Power BI de adherencia)
  - Pipeline de datos            -> dashboard/paginas/pipeline.py  (ejecuta el pipeline con su log y muestra el historial)
  - Completitud de datos         -> dashboard/paginas/completitud.py  (formulario y resultados del proceso)
En todas se muestran la última actualización de datos y el pie de página.

Ejecutar:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402

# Streamlit conserva los módulos importados en memoria entre ejecuciones (y en Google Drive no siempre detecta los cambios):
# se recargan, en orden de dependencia, para que la app nunca use una versión vieja de logic.py ni de pipeline/.
for _modulo in ("pipeline.config", "pipeline.parametros", "pipeline.seguridad", "pipeline.utils", "pipeline.extract", "pipeline.transform_bev",
                "pipeline.transform_costos", "pipeline.transform_ecv", "pipeline.mart", "pipeline.load", "pipeline.completitud", "pipeline.registro",
                "pipeline.main", "pipeline.ingest", "pipeline.gestion", "logic", "logic_adherencia", "logic_aplicaciones", "comun"):
    if _modulo in sys.modules:
        importlib.reload(sys.modules[_modulo])

st.set_page_config(page_title="Valor en Salud · Retina", page_icon="👁️", layout="wide")
comun.estilos()

tablero = st.Page("tablero.py", title="Tablero", icon=":material/dashboard:", default=True)
pipeline_pg = st.Page("paginas/pipeline.py", title="Pipeline de datos", icon=":material/play_circle:", url_path="pipeline")
completitud = st.Page("paginas/completitud.py", title="Completitud de datos", icon=":material/fact_check:", url_path="completitud")
aplicaciones = st.Page("paginas/aplicaciones.py", title="Seguimiento de aplicaciones", icon=":material/event_available:", url_path="aplicaciones")
adherencia = st.Page("paginas/adherencia.py", title="Análisis de adherencia", icon=":material/monitoring:", url_path="adherencia")
comun.PAGINAS.update({"tablero": tablero, "aplicaciones": aplicaciones, "adherencia": adherencia, "pipeline": pipeline_pg, "completitud": completitud})

pagina = st.navigation({"": [tablero], "Seguimiento": [aplicaciones, adherencia], "Datos y procesos": [pipeline_pg, completitud]})
comun.conservar_filtros()
comun.aviso_actualizacion()
pagina.run()
comun.pie()
