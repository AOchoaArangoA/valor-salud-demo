"""Hoja de parámetros del tablero: cada indicador con su meta, su ventana y su definición, en un solo lugar.

Las metas marcadas "provisional" usan el umbral verde vigente del semáforo (85 %) mientras el equipo experto confirma el valor final:
se cambian aquí y se reflejan en las tarjetas de Gestión de la atención y en la pestaña de metodología.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import config

META_PCT_PROVISIONAL = 85.0   # = umbral verde del semáforo (dashboard/logic.py)

# clave -> (nombre, valor/regla vigente, meta, unidad de la meta, estado de la meta, definición)
_FILAS = [
    ("oportunidad", "Oportunidad de inicio", f"1ª inyección ≤ {config.OPORTUNIDAD_INICIO_MAX_DIAS} días del diagnóstico",
     META_PCT_PROVISIONAL, "%", "provisional", "% de paciente-ojo reingreso con la primera inyección dentro del límite desde el diagnóstico."),
    ("carga", "Adherencia a dosis de carga", "3 dosis de carga en las primeras semanas",
     META_PCT_PROVISIONAL, "%", "provisional", "% de paciente-ojo reingreso que completan las dosis de carga (Adherencia_final_12)."),
    ("cumplimiento", "Cumplimiento de aplicaciones", f"fecha real dentro de ±{config.TOLERANCIA_PROGRAMACION_DIAS} días de la programada",
     META_PCT_PROVISIONAL, "%", "provisional",
     "% de aplicaciones a tiempo, contadas por aplicación y por año de exposición al tratamiento (año 1: días 0-364 desde la 1ª inyección; año 2: días 365-728)."),
    ("dosis", "Dosis aplicadas Año 1 / Año 2", "promedio por paciente-ojo reingreso", None, "dosis", "por definir",
     "Inyecciones recibidas en cada año de exposición al tratamiento (año 1 hasta la semana 52; año 2 entre la semana 52 y la 104)."),
    ("extension", "Extensión última dosis", "semanas entre la penúltima y la última dosis (S52 / S104)", None, "semanas", "por definir",
     "Intervalo entre las dos últimas aplicaciones dentro de la ventana de cada semana."),
    ("seca", "Anatomía sin líquido en OCT", "sin líquido intra ni subretiniano en S52 / S104",
     META_PCT_PROVISIONAL, "%", "provisional", "% de paciente-ojo reingreso con OCT sin líquido a la semana indicada."),
    ("av_umbral", "Mejora de agudeza visual", f"> +{config.UMBRAL_CLASE_AV_LETRAS} letras frente a la línea base", None, "letras", "vigente",
     "Cambio de letras ETDRS (85 − 50 × logMAR) respecto a la AV inicial."),
    ("ecv_delta", "Calidad de vida: evolución favorable", f"diferencia > {config.ECV_DELTA_FAVORABLE:g} puntos", None, "puntos", "vigente",
     "Encuesta 2 − encuesta 1 del puntaje total (escala 0-100), solo pacientes con las dos encuestas."),
    ("ecv_meta", "Calidad de vida: puntaje total año 2", f"> {config.ECV_META_TOTAL:g} puntos", config.ECV_META_TOTAL, "puntos", "vigente",
     "Puntaje total de la encuesta 2."),
]

# Reglas de medición que no son una meta pero definen cómo se lee el tablero.
REGLAS: List[Dict[str, str]] = [
    {"Regla": "Paciente-ojo reingreso", "Definición": "Unidad de análisis: un ojo en un episodio de tratamiento (ingreso o reingreso)."},
    {"Regla": "Año de exposición al tratamiento", "Definición": "Año 1 = días 0-364 desde la primera inyección del episodio; año 2 = días 365-728. Es la misma ventana para "
                                                  "inyecciones, costos y cumplimiento (no es el año calendario)."},
    {"Regla": "Semanas de resultado", "Definición": f"S16, S52 y S104 = visita más cercana a la semana objetivo (±{config.TOLERANCIA_VISITA_DIAS} días). "
                                                     "Los resultados de S104 se comparan contra la AV inicial."},
    {"Regla": "Seguimiento a S104", "Definición": "«Con AV a S52 y S104» exige las dos mediciones: un paciente-ojo con S104 sin S52 no entra a esa cohorte."},
    {"Regla": "Año 1 y año 2 completos", "Definición": "Utilización, costos y cumplimiento de los años 1 y 2 solo incluyen paciente-ojo reingreso con 2 años de "
                                                         "seguimiento posible, para no promediar años censurados."},
    {"Regla": "Rangos de AV inicial", "Definición": "Cuartiles de la AV inicial del prestador (toda la corrida): AV baja ≤ Q1 · AV media entre Q1 y Q3 · "
                                                     "AV alta ≥ Q3. Los atípicos quedan en AV baja o AV alta."},
    {"Regla": "Inicio oportuno", "Definición": f"Primera inyección a ≤ {config.OPORTUNIDAD_INICIO_MAX_DIAS} días del diagnóstico."},
    {"Regla": "Costo emparejado con la semana", "Definición": "Δ AV a S52 se cruza con el costo del año 1; Δ AV a S104 con el costo total (año 1 + año 2)."},
    {"Regla": "Calidad de vida", "Definición": "Los puntajes totales de cada encuesta usan a todos los pacientes que la respondieron; la comparación entre "
                                               "encuestas usa solo a quienes tienen las dos."},
]


def tabla() -> List[Dict[str, object]]:
    return [{"clave": k, "Indicador": n, "Regla vigente": v, "Meta": m, "Unidad": u, "Estado de la meta": e, "Definición": d}
            for k, n, v, m, u, e, d in _FILAS]


def meta(clave: str) -> Optional[float]:
    return next((m for k, _, _, m, _, _, _ in _FILAS if k == clave), None)


def texto_meta(clave: str) -> str:
    """Texto corto para las tarjetas: 'Meta ≥ 85 %' o 'Meta por definir'."""
    fila = next((f for f in _FILAS if f[0] == clave), None)
    if fila is None or fila[3] is None:
        return "Meta por definir"
    return f"Meta ≥ {fila[3]:g} {'%' if fila[4] == '%' else fila[4]}"
