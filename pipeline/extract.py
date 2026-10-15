"""Extracción: lee las hojas del libro 'Formularios valor en Salud' y las deja tipadas.

Reemplaza a los pd.read_csv de los notebooks (p1_01_pacientes.csv ... p1_05_ayudas.csv).
Diferencia clave: al leer desde Excel las columnas llegan con texto/'' mezclado, así que
se coercionan fechas y numéricos aquí para que el resto del código vea los mismos tipos
que veía con los CSV.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from . import config
from .utils import get_logger

log = get_logger(__name__)


def _tipar(nombre: str, df: pd.DataFrame) -> pd.DataFrame:
    for col in config.FECHAS.get(nombre, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    for col in config.NUMERICAS.get(nombre, []):
        if col not in df.columns:
            continue
        antes = df[col].notna().sum()
        numerico = pd.to_numeric(df[col], errors="coerce")
        despues = numerico.notna().sum()
        # Ej.: 'molecula'/'medicamento' son código numérico en un prestador y texto (nombre del
        # medicamento) en otro. Si coercionar destruye más de la mitad del dato, algo no cuadra
        # con lo esperado: se deja el texto original y se avisa, en vez de convertir todo en NaN.
        if antes > 0 and despues < antes * 0.5:
            log.warning("%s.%s: no se convirtió a número (%d/%d valores se habrían perdido). "
                        "¿Este prestador usa texto en vez de código? Se deja tal cual.", nombre, col, antes - despues, antes)
            continue
        df[col] = numerico
    return df


# Corrección de dígito de más señalada por el experto (correo 2026-09-27, punto 1): algunos
# registros de IRF/hemorragia llegan con "10" en vez de "1". Aplica a lineabase y ayudas.
COLUMNAS_OCT_BOOLEANAS = ["oct_dep", "oct_irf", "oct_srf", "oct_hemorragia", "oct_quistes", "oct_hrfs", "oct_atrofia", "oct_fibrosis"]


def _corregir_oct_booleanas(datos: Dict[str, pd.DataFrame]) -> None:
    for hoja in ("lineabase", "ayudas"):
        df = datos.get(hoja)
        if df is None:
            continue
        for col in COLUMNAS_OCT_BOOLEANAS:
            if col in df.columns:
                malos = int((df[col] == 10).sum())
                if malos:
                    log.warning("%s.%s: %d valores en 10 corregidos a 1 (dígito de más).", hoja, col, malos)
                    df.loc[df[col] == 10, col] = 1


def _reconstruir_pacienteojoreingreso(nombre: str, df: pd.DataFrame) -> None:
    """pacienteojoreingreso debe ser numero_doc+ojo+reingreso; en algún export puede venir con
    otro formato (visto en un prestador: la hoja 'consultas' traía 'numdoc_OJO_reingreso' con guion bajo,
    sin relación con las demás hojas). Si no coincide con el patrón esperado, se reconstruye."""
    cols = {"numero_doc", "ojo", "reingreso", "pacienteojoreingreso"}
    if not cols.issubset(df.columns):
        return
    esperado = (df["numero_doc"].astype("Int64").astype(str) + df["ojo"].astype(str)
                + df["reingreso"].astype("Int64").astype(str))
    distintos = (df["pacienteojoreingreso"].astype(str) != esperado) & df["numero_doc"].notna()
    if distintos.any() and distintos.mean() > 0.5:
        log.warning("%s.pacienteojoreingreso: %d/%d filas no seguían el formato numero_doc+ojo+reingreso; "
                    "se reconstruyó a partir de esas 3 columnas.", nombre, int(distintos.sum()), len(df))
        df["pacienteojoreingreso"] = esperado


def leer_hojas(ruta: Optional[Path] = None, hojas: Iterable[str] = config.HOJAS_REQUERIDAS) -> Dict[str, pd.DataFrame]:
    ruta = Path(ruta or config.XLSM_PATH or "")
    if not ruta.is_file():
        raise FileNotFoundError(
            f"No se encontró el libro de insumos: '{ruta}'. Defina VLM_XLSM_PATH (y VLM_PRESTADOR) en el "
            "archivo .env -- vea data/raw/README.md para las entregas disponibles."
        )
    log.info("Leyendo %s", ruta.name)
    datos = {}
    with pd.ExcelFile(ruta) as libro:   # se cierra al terminar: en Windows un archivo abierto no se puede mover
        faltan = [h for h in hojas if h not in libro.sheet_names]
        if faltan:
            raise KeyError(f"Hojas ausentes en {ruta.name}: {faltan}")
        for hoja in hojas:
            datos[hoja] = _tipar(hoja, libro.parse(hoja))
            _reconstruir_pacienteojoreingreso(hoja, datos[hoja])
            log.info("  hoja %-15s %6d filas x %2d columnas", hoja, *datos[hoja].shape)
    _corregir_oct_booleanas(datos)
    _exigir_con_datos(datos, ruta.name)
    _exigir_columnas_requeridas(datos, ruta.name)
    return datos


# Hojas sin las cuales no se puede calcular AV, OCT, adherencia ni costos
HOJAS_CON_DATOS = ["pacientes", "lineabase", "aplicaciones", "consultas", "ayudas"]


def _exigir_con_datos(datos: Dict[str, pd.DataFrame], nombre: str) -> None:
    vacias = [h for h in HOJAS_CON_DATOS if h in datos and datos[h].empty]
    if vacias:
        raise ValueError(f"'{nombre}' no sirve como insumo: hojas sin filas {vacias}. "
                         "Use una versión completa del formulario (VLM_XLSM_PATH o --xlsm).")
    if datos["calidadvida"].empty:
        log.warning("La hoja 'calidadvida' está vacía: no habrá ECV en el tablero.")


def _exigir_columnas_requeridas(datos: Dict[str, pd.DataFrame], nombre: str) -> None:
    """Falla temprano, con todos los faltantes juntos, si el libro no trae las columnas que el cálculo necesita."""
    faltan = {h: [c for c in cols if c not in datos[h].columns] for h, cols in config.COLUMNAS_REQUERIDAS.items() if h in datos}
    faltan = {h: c for h, c in faltan.items() if c}
    if faltan:
        detalle = "; ".join(f"{h}: {', '.join(c)}" for h, c in faltan.items())
        raise KeyError(f"'{nombre}' no trae columnas requeridas -> {detalle}")


def leer_maestra_costos(datos: Dict[str, pd.DataFrame], modo: str = "auto", ruta: Optional[Path] = None) -> pd.DataFrame:
    """Maestra de costos. `modo`:
    'libro'   -> hoja 'maestra_costos' del propio formulario;
    'archivo' -> el Excel indicado en `ruta` (hoja 'maestra_costos');
    'dummy'   -> tabla ficticia por año (solo pruebas);
    'auto'    -> lo que digan las variables de entorno (comportamiento histórico de la línea de comandos)."""
    if modo == "auto":
        if config.COSTOS_MAESTRA_PATH:
            modo, ruta = "archivo", config.COSTOS_MAESTRA_PATH
        else:
            modo = "libro"
    if modo == "dummy":
        ruta, modo = config.DUMMY_COSTOS_PATH, "archivo"
    if modo == "archivo":
        if ruta is None or not Path(ruta).is_file():
            raise FileNotFoundError(f"No se encontró la tabla de costos: '{ruta}'")
        maestra = pd.read_excel(ruta, sheet_name="maestra_costos")
        if es_maestra_dummy(maestra):
            log.warning("*** COSTOS DUMMY *** usando '%s': valores aleatorios, NO reales.", Path(ruta).name)
        else:
            log.info("Usando tabla de costos externa: %s", ruta)
    else:
        maestra = datos["maestra_costos"].copy()
        log.warning("Se usa la hoja 'maestra_costos' del libro.")
    costos = pd.to_numeric(maestra.get("Costo promedio unitario"), errors="coerce")
    if costos.notna().any() and costos.max() < 1000:
        log.warning("Los costos unitarios son menores a 1.000 (máx. %s): parecen valores de referencia, no pesos.", costos.max())
    return maestra


def es_maestra_dummy(maestra: pd.DataFrame) -> bool:
    return bool(maestra.get("es_dummy", pd.Series(dtype=bool)).any())


def leer_ecv(ruta: Optional[Path] = None) -> pd.DataFrame:
    ruta = ruta or config.ECV_PATH
    if ruta is None or not Path(ruta).is_file():
        raise FileNotFoundError(f"No se encontró el output de ECV: '{ruta}'. Defina VLM_ECV_PATH en .env "
                                "(hoy solo existe para P1; ver data/raw/README.md).")
    return pd.read_excel(ruta)
