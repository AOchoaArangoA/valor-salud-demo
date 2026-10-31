"""Valor en Salud (retina) — punto de entrada de la aplicación.

Enruta las páginas con st.navigation:
  - Tablero                      -> dashboard/tablero.py  (los 7 niveles de gestión)
  - Cargar y procesar            -> dashboard/paginas/carga.py  (corre el pipeline desde la app)
  - Historial de ejecuciones     -> dashboard/paginas/historial.py  (bitácora del pipeline)
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
from pipeline import config  # noqa: E402  (la ruta del proyecto la agrega logic)

# Streamlit conserva los módulos importados en memoria entre ejecuciones (y en Google Drive no siempre detecta los cambios):
# se recargan, en orden de dependencia, para que la app nunca use una versión vieja de logic.py ni de pipeline/.
for _modulo in ("pipeline.config", "pipeline.parametros", "pipeline.seguridad", "pipeline.utils", "pipeline.extract", "pipeline.transform_bev",
                "pipeline.transform_costos", "pipeline.transform_ecv", "pipeline.mart", "pipeline.load", "pipeline.completitud", "pipeline.registro",
                "pipeline.main", "pipeline.ingest", "logic", "comun"):
    if _modulo in sys.modules:
        importlib.reload(sys.modules[_modulo])

st.set_page_config(page_title="Valor en Salud · Retina", page_icon="👁️", layout="wide")
comun.estilos()

tablero = st.Page("tablero.py", title="Tablero", icon=":material/dashboard:", default=True)
carga = st.Page("paginas/carga.py", title="Cargar y procesar", icon=":material/upload_file:", url_path="cargar")
historial = st.Page("paginas/historial.py", title="Historial de ejecuciones", icon=":material/history:", url_path="historial")
completitud = st.Page("paginas/completitud.py", title="Completitud de datos", icon=":material/fact_check:", url_path="completitud")
comun.PAGINAS.update({"tablero": tablero, "carga": carga, "historial": historial, "completitud": completitud})

# Despliegue de solo consulta (VLM_CARGA_HABILITADA=0, p. ej. la demostración en la nube): sin la página de carga
procesos = ([carga] if config.CARGA_HABILITADA else []) + [historial, completitud]
pagina = st.navigation({"": [tablero], "Datos y procesos": procesos})
comun.aviso_actualizacion()
pagina.run()
comun.pie()
