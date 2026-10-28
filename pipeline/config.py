"""Configuración central: rutas (vía variables de entorno / .env) y constantes de negocio.

Todo valor "mágico" que estaba embebido en los notebooks vive aquí.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _ruta(nombre_env: str, defecto: Optional[Path]) -> Optional[Path]:
    """Ruta desde el entorno; las relativas se resuelven contra la raíz del proyecto."""
    valor = os.getenv(nombre_env)
    if not valor:
        return defecto
    ruta = Path(valor)
    return ruta if ruta.is_absolute() else ROOT / ruta


# --------------------------------------------------------------------------- rutas
# data/raw guarda una carpeta por prestador y versión (ver data/raw/README.md); nunca se
# adivina cuál está activa -- con más de un prestador sería peligroso equivocarse en silencio.
XLSM_PATH: Optional[Path] = _ruta("VLM_XLSM_PATH", None)
# Prestador de la corrida activa (p1, p2, ...). Se guarda en metadata.json; hoy el pipeline
# procesa un prestador a la vez (ver "Por qué no se consolidan..." en data/raw/README.md).
PRESTADOR: str = os.getenv("VLM_PRESTADOR", "sin_definir")
# Tabla de costos alterna con el formato del notebook original
# (columnas 'Grupo','Describe','Costo promedio unitario','GrupoAjustado Valor en Salud',
#  'Medicamento_anonimizado'). Si no se define, se usa la hoja 'maestra_costos' del .xlsm.
COSTOS_MAESTRA_PATH: Optional[Path] = _ruta("VLM_COSTOS_MAESTRA_PATH", None)
# Output existente del notebook de ECV (promedios por dimensión y encuesta). Solo existe para P1
# (otros prestadores lo aportan al cargar el insumo; si no, los indicadores de calidad de vida quedan vacíos).
ECV_PATH: Optional[Path] = _ruta("VLM_ECV_PATH", None)
# Carpeta raíz de datos (raw/ y processed/). Puede ser una ruta de red (\\servidor\carpeta): todos los
# usuarios comparten así las mismas cargas y los mismos resultados.
DATA_ROOT: Path = _ruta("VLM_DATA_ROOT", ROOT / "data")
RAW_DIR: Path = DATA_ROOT / "raw"
OUTPUT_DIR: Path = _ruta("VLM_OUTPUT_DIR", DATA_ROOT / "processed")
# Tabla de costos DUMMY (viaja con el proyecto, no con la carpeta de datos)
DUMMY_COSTOS_PATH: Path = ROOT / "data" / "reference" / "maestra_costos_por_anio_DUMMY.xlsx"
# Si se define, quien cargue un insumo debe escribirlo (control mínimo, no es seguridad fuerte)
UPLOAD_PIN: str = os.getenv("VLM_UPLOAD_PIN", "")
# Orden en que el tablero ofrece los prestadores: el primero es la base (la que se abre por defecto). Los demás, en este orden;
# los que no estén en la lista van después, de la carga más reciente a la más antigua.
PRESTADORES_ORDEN = [x.strip().lower() for x in os.getenv("VLM_PRESTADORES_ORDEN", "p1,p2").split(",") if x.strip()]
# Nota discreta de "modo demostración" en la barra lateral (costos de referencia / datos sintéticos). Apagada por defecto.
MOSTRAR_AVISOS_DEMO: bool = os.getenv("VLM_MOSTRAR_AVISOS_DEMO", "0").strip().lower() in ("1", "true", "si", "sí")
LOG_LEVEL: str = os.getenv("VLM_LOG_LEVEL", "INFO")

# --------------------------------------------------------------------------- hojas
HOJAS_REQUERIDAS: List[str] = [
    "pacientes", "lineabase", "aplicaciones", "consultas", "ayudas", "maestra_costos", "calidadvida",
]

# Columnas sin las cuales el pipeline no puede calcular nada (se validan al cargar un insumo)
COLUMNAS_REQUERIDAS: Dict[str, List[str]] = {
    "pacientes": ["numero_doc", "edad"],
    "lineabase": ["numero_doc", "pacienteojoreingreso", "ojo", "reingreso", "dx_fecha", "dx_ppal", "av_num"],
    "aplicaciones": ["pacienteojoreingreso", "pacienteojo", "numero_doc", "ojo", "reingreso", "fecha_aplicacion",
                     "fecha_programacion", "molecula", "dx_ppal_desc", "con_dosis", "tipo_tto"],
    "consultas": ["pacienteojoreingreso", "numero_doc", "ojo", "reingreso", "fecha_consulta", "agu_vis",
                  "endoftalmitis", "tipo_consulta"],
    "ayudas": ["pacienteojoreingreso", "numero_doc", "ojo", "reingreso", "fecha_ayuda", "oct", "oct_irf", "oct_srf", "tipo_ayuda"],
    "calidadvida": ["numero_doc", "nro_encuesta", "fechaencuesta"],
}

# Columnas a tipar al leer el .xlsm (en Excel llegan mezcladas con texto/'' ; en los CSV originales no)
FECHAS: Dict[str, List[str]] = {
    "pacientes": ["fecha_dilig", "fecha_nac", "fecha_dx_dm"],
    "lineabase": ["dx_fecha", "fecha_registro", "egreso_fecha"],
    "aplicaciones": ["fecha_aplicacion", "fecha_programacion", "fecha_registro"],
    "consultas": ["fecha_consulta", "fecha_registro"],
    "ayudas": ["fecha_ayuda", "fecha_registro"],
    "calidadvida": ["fechaencuesta", "fecharegistro"],
}
NUMERICAS: Dict[str, List[str]] = {
    "pacientes": ["edad", "peso", "talla", "imc", "años_dm", "hba1c", "numero_doc"],
    "lineabase": ["numero_doc", "av_num", "av_con_num", "medicamento"],
    "aplicaciones": ["con_dosis", "molecula", "numero_doc"],
    "consultas": ["agu_vis", "agu_vis_num", "endoftalmitis", "com_ambliopia", "com_maculopatia",
                  "com_opa_med", "com_glau_neu", "com_evr", "numero_doc"],
    "ayudas": ["oct", "oct_dep", "oct_irf", "oct_srf", "oct_hemorragia", "oct_quistes",
               "oct_hrfs", "oct_atrofia", "oct_fibrosis", "numero_doc"],
    "calidadvida": ["numero_doc", "nro_encuesta"],
}

# --------------------------------------------------------------------------- reglas clínicas
# Semanas de seguimiento -> días desde la primera inyección
SEMANAS_ACUMULADAS: Dict[int, int] = {12: 84, 16: 112, 20: 140, 52: 364, 104: 728}
TOLERANCIA_VISITA_DIAS = 28        # ventana ±4 semanas alrededor de la semana objetivo
TOLERANCIA_EXACTA_DIAS = 3         # "visita exacta" ±3 días
# Ventana de cumplimiento de la fecha programada: se unificó en ±10 días con el reporte de aplicaciones
# (reporte_aplicaciones_v4_501_2, medida "Pct Dentro Ventana"). El notebook original usaba ±8: con
# VLM_TOL_PROG=8 se reproducen sus Excel.
TOLERANCIA_PROGRAMACION_DIAS = int(os.getenv("VLM_TOL_PROG", "10"))
RETRASO_GRAVE_DIAS = 30            # > 30 días de retraso = "retraso grave" (misma clasificación del reporte)
# Celda 53 del notebook pretendía completar la AV que no está en la tabla ETDRS con 85 - 50*logMAR, pero
# `df['AV_letras'].fillna(..., inplace=True)` no surte efecto con pandas moderno (Copy-on-Write), por lo que
# los Excel legados quedaron SIN esa imputación. True = lógica pretendida; False = reproduce los Excel legados.
RELLENAR_AV_POR_LOGMAR = os.getenv("VLM_RELLENAR_AV", "1").strip().lower() not in ("0", "false", "no")
UMBRAL_OCT_MICRAS = 300
UMBRAL_CLASE_AV_LETRAS = 5         # empeora < -5, mejora > 5

# Adherencia: >2 aplicaciones acumuladas (OVR: >5)
ADHERENCIA_MIN_APL = 2
ADHERENCIA_MIN_APL_OVR = 5

# Pérdida de letras que define "criterio AV" del respondedor, por diagnóstico
UMBRAL_PERDIDA_AV = {"DMREn": -5, "EMD": -10}
UMBRAL_PERDIDA_AV_DEFECTO = -5

# Agudeza visual no numérica (cuenta dedos, movimiento de manos, percepción/no percepción de luz):
# el formulario debería auto-convertirlas al código numérico de abajo (NotasVersión, v4.0.1), pero
# algunos registros llegan con la sigla sin convertir (visto en un prestador: 19/442 consultas, 4,3 %).
MAPA_AV_TEXTO = {"CD": 2000, "MM": 20000, "PL": 200000, "NPL": 2000000}
# Agudeza visual: códigos especiales -> valor Snellen
MAPA_AV_ESPECIAL = {20000.0: 4000, 200000.0: 10000, 2000000.0: 20000}  # HBW, LP, NLP
SNELLEN_A_ETDRS = {
    10.0: 100, 12.5: 95, 16.0: 90, 20.0: 85, 25.0: 80, 32.0: 75, 40.0: 70, 50.0: 65, 63.0: 60,
    80.0: 55, 100.0: 50, 125.0: 45, 160.0: 40, 200.0: 35, 250.0: 30, 320.0: 25, 400.0: 20,
    500.0: 15, 630.0: 10, 800.0: 5, 2000.0: 2, 20000.0: 0, 200000.0: 0, 2000000.0: 0,
}

GRUPOS_EDAD_CORTES = [(50, "< 50"), (60, "50-59"), (70, "60-69"), (80, "70-79"), (90, "80-89")]
GRUPO_EDAD_MAYOR = ">= 90"

# --------------------------------------------------------------------------- costos
TRIMESTRES_MAX = 12          # 3 años
MIN_TRIMESTRES_CON_COSTO = 2  # regla "≥ 2 periodos" para contar un costo anual

# Abreviaturas usadas por el notebook para nombrar el grupo de cada medicamento
ABREV_MEDICAMENTO = {
    "Aflibercept": "AFL", "Ranibizumab": "RNB", "Bevacizumab": "BEVA", "Brolucizumab": "BROLU",
    "Faricimab": "FARI", "Dexametasona": "DEXA", "Aflibercept 8": "AFL8",
}
# (Grupo de la maestra, Describe) -> GrupoAjustado. Lo no listado toma el prefijo del Grupo.
GRUPO_AJUSTADO_EXPLICITO = {
    ("Tipo de tratamiento", "Aplicación intravítrea"): "TipoTto_InyIV",
    ("Consultas", "Retina"): "Cons_Retina",
    ("Consultas", "Oftalmología"): "Cons_Oftalmo",
    ("Tipo de ayuda", "OCT"): "TipoAyuda_OCT",
}
PREFIJO_GRUPO = {"Tipo de tratamiento": "TipoTto", "Consultas": "Cons", "Tipo de ayuda": "TipoAyuda"}

# --------------------------------------------------------------------------- mart / tablero
OPORTUNIDAD_INICIO_MAX_DIAS = 15   # Meta del experto (revisión 28-oct-2026): inicio oportuno si primera inyección <= 15 d del diagnóstico
MEDICAMENTO_LABEL = "MED{codigo}"  # la propuesta muestra los medicamentos anonimizados (MED1, MED2...)


# Dimensiones del NEI VFQ-25 que reporta el experto (columnas *_prom del archivo de ECV), agrupadas como
# en la propuesta: percepción de la visión / funcionamiento / bienestar. (clave, etiqueta, grupo)
ECV_DIMENSIONES = [
    ("Vision_General", "Visión general", "Percepción de la visión"),
    ("Vision_Cercana", "Visión cercana", "Percepción de la visión"),
    ("Vision_Lejana", "Visión lejana", "Percepción de la visión"),
    ("Vision_periferica", "Visión periférica", "Percepción de la visión"),
    ("Vision_Color", "Visión de color", "Percepción de la visión"),
    ("Funcion_Social", "Función social", "Funcionamiento"),
    ("Limitaciones_Rol", "Limitaciones de rol", "Funcionamiento"),
    ("Dependencia", "Dependencia", "Funcionamiento"),
    ("Conducir", "Conducción", "Funcionamiento"),
    ("Bienestar_Sufrimiento", "Bienestar y sufrimiento", "Bienestar"),
    ("Dolor_Ocular", "Dolor ocular", "Bienestar"),
]

# Lectura de la ECV según la diapositiva del experto: cambio > 5 puntos = evolución favorable; meta del puntaje total en el año 2.
ECV_DELTA_FAVORABLE = 5.0
ECV_META_TOTAL = 70.0

# Solo para pruebas con el equipo experto: si se define (p. ej. VLM_RESPONDEDOR_PRUEBA=75), el tablero muestra ese
# valor fijo en "% respondedores" y lo rotula como valor de prueba. Vacío = se usa el cálculo real.
_rp = os.getenv("VLM_RESPONDEDOR_PRUEBA", "").strip()
RESPONDEDOR_PRUEBA = float(_rp) if _rp else None

# Despliegues de solo consulta (p. ej. demostración en la nube): VLM_CARGA_HABILITADA=0 oculta "Cargar insumo".
CARGA_HABILITADA: bool = os.getenv("VLM_CARGA_HABILITADA", "1").strip().lower() not in ("0", "false", "no")
