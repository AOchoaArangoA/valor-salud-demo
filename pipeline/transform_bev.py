"""Transformaciones de CONSOLIDAR_BASE.ipynb (línea base, aplicaciones, consultas, ayudas).

La lógica replica el notebook celda a celda; los comentarios "CELDA n" apuntan al original.
Salidas (equivalen a los Excel que producía el notebook):
    pacientes        -> Base_pacientes.xlsx
    adherencia       -> Adherencia_aplicaciones.xlsx
    oportunidad_apl  -> Oportunidad_apl_tto.xlsx
    evolucion        -> Base_evol_OCT_AV_Respondedor.xlsx
    complicaciones   -> Complicaciones_endoftalmitis.xlsx
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from . import config
from .utils import (clasificar_cambio_av, exigir_columnas, get_logger, reemplazar_av_especial,
                    snellen_a_logmar)

log = get_logger(__name__)
CLAVE_OJO = ["pacienteojo", "pacienteojoreingreso"]


# =========================================================================== pacientes
def preparar_pacientes(df_ptes: pd.DataFrame, df_lb: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 4-17: línea base + datos del paciente, grupo de edad y AV especial."""
    exigir_columnas(df_lb, ["numero_doc", "pacienteojoreingreso", "dx_fecha", "dx_ppal", "av_num"], "lineabase")
    exigir_columnas(df_ptes, ["numero_doc", "edad"], "pacientes")

    dup = int(df_lb["pacienteojoreingreso"].duplicated().sum())
    if dup:
        log.warning("lineabase: %d pacienteojoreingreso repetidos (se conservan, igual que el notebook)", dup)

    df_lb = df_lb.drop(columns=["tipo_doc"], errors="ignore")
    df_pt1 = df_lb.merge(df_ptes, on="numero_doc", how="left")

    edad = df_pt1["edad"]
    condiciones = [edad < c for c, _ in config.GRUPOS_EDAD_CORTES] + [edad >= 90]
    etiquetas = [e for _, e in config.GRUPOS_EDAD_CORTES] + [config.GRUPO_EDAD_MAYOR]
    # Cada condición del notebook es un intervalo cerrado-abierto; np.select toma la primera verdadera
    df_pt1["Grupo_edad"] = np.select(condiciones, etiquetas, default="sin dato")

    for col in ["ant_diabetes", "ant_dislipidemia", "ant_hta", "actividad_fisica"]:
        df_pt1[col] = df_pt1[col].fillna(0)

    df_pt1["av_num"] = reemplazar_av_especial(df_pt1["av_num"])
    return df_pt1


# =========================================================================== aplicaciones
def _acumulados(grupo: pd.DataFrame) -> pd.Series:
    """CELDA 21: aplicaciones y moléculas acumuladas hasta cada semana."""
    d = grupo["dias_desde_primera"]
    ventanas = {sem: grupo[d <= dias] for sem, dias in config.SEMANAS_ACUMULADAS.items()}
    salida = {f"apl_acum_sem{s}": len(ventanas[s]) for s in (12, 16, 20, 52, 104)}
    for s in (16, 20, 52, 104):
        salida[f"molecula_sem{s}"] = ", ".join(map(str, ventanas[s]["molecula"].dropna().unique()))
    return pd.Series(salida)


def _por_anio(grupo: pd.DataFrame) -> pd.Series:
    """CELDA 22: aplicaciones y moléculas por año (no acumulado)."""
    d = grupo["dias_desde_primera"]
    a1 = grupo[(d >= 0) & (d <= 364)]
    a2 = grupo[(d > 364) & (d <= 728)]
    return pd.Series({
        "apl_anio1": len(a1), "molecula_anio1": ", ".join(map(str, a1["molecula"].dropna().unique())),
        "apl_anio2": len(a2), "molecula_anio2": ", ".join(map(str, a2["molecula"].dropna().unique())),
    })


def _extension_ultimas_dos(grupo: pd.DataFrame, corte: int, minimo: int = 0):
    """CELDA 29: semanas entre las dos últimas aplicaciones dentro de la ventana."""
    g = grupo[(grupo["dias_desde_primera"] > minimo) & (grupo["dias_desde_primera"] <= corte)]
    ultimas = g.sort_values("fecha_aplicacion").tail(2)["fecha_aplicacion"]
    if len(ultimas) == 2:
        return (ultimas.iloc[1] - ultimas.iloc[0]).days / 7
    return np.nan


def _dif_ultima(grupo: pd.DataFrame, corte: int, minimo: int = 0):
    """CELDA 29: semanas entre la última aplicación de la ventana y el corte."""
    g = grupo[(grupo["dias_desde_primera"] > minimo) & (grupo["dias_desde_primera"] <= corte)]
    if len(g) > 0:
        fecha_corte = grupo["fecha_aplicacion"].min() + pd.Timedelta(days=corte)
        return (fecha_corte - g["fecha_aplicacion"].max()).days / 7
    return np.nan


def _extensiones(grupo: pd.DataFrame) -> pd.Series:
    return pd.Series({
        "extension_sem52": _extension_ultimas_dos(grupo, 364),
        "extension_sem104": _extension_ultimas_dos(grupo, 728, minimo=364),
        "dif_ultima_sem52": _dif_ultima(grupo, 364),
        "dif_ultima_sem104": _dif_ultima(grupo, 728, minimo=364),
    })


def consolidar_adherencia(df_apl: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """CELDAS 21-31. Devuelve (adherencia_final, df_apl con fecha_primera y dias_desde_primera)."""
    exigir_columnas(df_apl, CLAVE_OJO + ["fecha_aplicacion", "molecula", "dx_ppal_desc"], "aplicaciones")
    df_apl = df_apl.copy()

    primeras = df_apl.groupby(CLAVE_OJO)["fecha_aplicacion"].min().reset_index(name="fecha_primera")
    ultimas = df_apl.groupby(CLAVE_OJO)["fecha_aplicacion"].max().reset_index(name="fecha_ultima")
    diag_primera = (
        df_apl.sort_values(CLAVE_OJO + ["fecha_aplicacion"]).groupby(CLAVE_OJO).first().reset_index()
        [CLAVE_OJO + ["dx_ppal_desc"]]
    )
    base = primeras.merge(ultimas, on=CLAVE_OJO).merge(diag_primera, on=CLAVE_OJO)

    df_apl = df_apl.merge(primeras, on=CLAVE_OJO, how="left")
    df_apl["dias_desde_primera"] = (df_apl["fecha_aplicacion"] - df_apl["fecha_primera"]).dt.days

    acumulados = df_apl.groupby(CLAVE_OJO).apply(_acumulados).reset_index()
    adh = base.merge(acumulados, on=CLAVE_OJO)
    adh = adh.merge(df_apl.groupby(CLAVE_OJO).apply(_por_anio).reset_index(), on=CLAVE_OJO, how="left")

    # CELDA 28: adherencia final por semana (OVR exige > 5 aplicaciones; el resto > 2)
    for sem in (12, 16, 20):
        acum = adh[f"apl_acum_sem{sem}"]
        adh[f"Adherencia_final_{sem}"] = np.where(
            (adh["dx_ppal_desc"] == "OVR") & (acum > config.ADHERENCIA_MIN_APL_OVR), 1,
            np.where(acum > config.ADHERENCIA_MIN_APL, 1, 0),
        )

    adh = adh.merge(df_apl.groupby(CLAVE_OJO).apply(_extensiones).reset_index(), on=CLAVE_OJO, how="left")
    adh["fecha_primera_dma"] = adh["fecha_primera"].dt.strftime("%d-%m-%Y")
    adh["fecha_ultima_dma"] = adh["fecha_ultima"].dt.strftime("%d-%m-%Y")
    return adh, df_apl


def calcular_oportunidad_aplicacion(df_apl: pd.DataFrame) -> pd.DataFrame:
    """CELDA 96: oportunidad = (fecha real de la siguiente aplicación) - (fecha programada), ventana ±config.TOLERANCIA_PROGRAMACION_DIAS d (hoy ±10)."""
    exigir_columnas(df_apl, ["pacienteojoreingreso", "con_dosis", "fecha_aplicacion", "fecha_programacion"], "aplicaciones")
    df = df_apl.sort_values(["pacienteojoreingreso", "con_dosis"]).copy()
    df["fecha_aplicacion_siguiente"] = df.groupby("pacienteojoreingreso")["fecha_aplicacion"].shift(-1)
    df["Oportunidad_aplicacion_dias"] = (df["fecha_aplicacion_siguiente"] - df["fecha_programacion"]).dt.days
    tol = config.TOLERANCIA_PROGRAMACION_DIAS
    df["Oportunidad_aplicacion_cat"] = np.where(
        df["Oportunidad_aplicacion_dias"].between(-tol, tol), "Cumple",
        np.where(df["Oportunidad_aplicacion_dias"].isna(), pd.NA, "No cumple"),
    )
    df["Oportunidad_aplicacion_cat"] = df["Oportunidad_aplicacion_cat"].astype("string")

    # --- detalle del reporte de aplicaciones (reporte_aplicaciones_v4_501_2) ---------------------------
    t, g = tol, config.RETRASO_GRAVE_DIAS
    d = df["Oportunidad_aplicacion_dias"]
    df["Clasificacion_cumplimiento"] = np.select(
        [d.isna(), d < -t, d < 0, d == 0, d <= t, d <= g],
        ["Sin dato", f"1. Muy adelantado (>{t}d)", f"2. Adelantado (1-{t}d)", "3. Exacto",
         f"4. Retraso leve (1-{t}d)", f"5. Retraso moderado ({t + 1}-{g}d)"],
        default=f"6. Retraso grave (>{g}d)")
    # extensión programada: semanas de esta aplicación a su fecha programada siguiente
    df["Semanas_Apl_a_Prog"] = ((df["fecha_programacion"] - df["fecha_aplicacion"]).dt.days / 7).round()
    # extensión real: semanas desde la aplicación anterior (por consecutivo de dosis)
    df["Semanas_Entre_Dosis"] = ((df["fecha_aplicacion"] - df.groupby("pacienteojoreingreso")["fecha_aplicacion"].shift(1)).dt.days / 7).round()
    return df


# =========================================================================== consultas / AV
def _normalizar_av_texto(serie: pd.Series, nombre: str) -> pd.Series:
    """La columna puede llegar como texto (p. ej. si trae CD/MM/PL/NPL mezclado con números que
    Excel leyó como texto). Primero intenta el número tal cual; si no es número, CD/MM/PL/NPL ->
    código Snellen (NotasVersión 4.0.1: el formulario debería convertirlas solo, pero algunos
    registros llegan con la sigla sin convertir, visto en un prestador)."""
    if serie.dtype != object:
        return serie
    numerica = pd.to_numeric(serie, errors="coerce")
    aun_texto = serie.notna() & numerica.isna()
    if not aun_texto.any():
        return numerica
    siglas = serie[aun_texto].map(config.MAPA_AV_TEXTO)
    numerica = numerica.where(~aun_texto, siglas)
    sin_mapeo = aun_texto & numerica.isna()
    if sin_mapeo.any():
        log.warning("%s: %d valores sin mapeo conocido (se dejan como vacío): %s",
                    nombre, int(sin_mapeo.sum()), sorted(serie[sin_mapeo].unique()))
    mapeadas = aun_texto & ~sin_mapeo
    if mapeadas.any():
        log.warning("%s: %d valores (%s) convertidos de sigla a código Snellen.",
                    nombre, int(mapeadas.sum()), sorted(serie[mapeadas].unique()))
    return numerica


def _fechas_importantes(df_apl: pd.DataFrame, df_lb: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 36-39: primera inyección y fecha de línea base por paciente-ojo."""
    primera = (df_apl.groupby("pacienteojoreingreso", as_index=False)["fecha_aplicacion"].min()
               .rename(columns={"fecha_aplicacion": "fecha_primera_iny"}))
    fecha_lb = df_lb[["pacienteojoreingreso", "dx_fecha"]].copy()
    fecha_lb["Fecha_LB"] = pd.to_datetime(fecha_lb["dx_fecha"], errors="coerce")
    return primera.merge(fecha_lb, on="pacienteojoreingreso", how="left").drop(columns="dx_fecha")


def preparar_consultas(df_cons: pd.DataFrame, fechas: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 41-54: agudeza visual en letras ETDRS, Snellen y logMAR."""
    exigir_columnas(df_cons, ["pacienteojoreingreso", "fecha_consulta", "agu_vis", "endoftalmitis"], "consultas")
    df = df_cons.merge(fechas, on="pacienteojoreingreso", how="left")
    df["agu_vis"] = _normalizar_av_texto(df["agu_vis"], "consultas.agu_vis")
    df["AV_letras"] = df["agu_vis"].map(config.SNELLEN_A_ETDRS)
    df["agu_vis"] = reemplazar_av_especial(df["agu_vis"])
    df["AV_snellen"] = df["agu_vis"].apply(lambda x: f"20/{int(x)}" if pd.notnull(x) else np.nan)
    df["AV_logMAR"] = df["AV_snellen"].apply(snellen_a_logmar)
    # AV que no está en la tabla ETDRS: fórmula 85 - 50*logMAR (ver config.RELLENAR_AV_POR_LOGMAR)
    if config.RELLENAR_AV_POR_LOGMAR:
        df["AV_letras"] = df["AV_letras"].fillna(85 - 50 * df["AV_logMAR"])
    df["dias_desde_iny"] = (df["fecha_consulta"] - df["fecha_primera_iny"]).dt.days
    return df


def _visita_por_semana(grupo: pd.DataFrame, dias: int) -> pd.Series:
    """Visita más cercana a la semana objetivo (ventana ±28 d; 'exacta' ±3 d), o None."""
    d = grupo["dias_desde_iny"]
    tol = config.TOLERANCIA_VISITA_DIAS
    rango = grupo[(d >= dias - tol) & (d <= dias + tol)]
    if rango.empty:
        return None
    exacto = rango[(rango["dias_desde_iny"] >= dias - config.TOLERANCIA_EXACTA_DIAS)
                   & (rango["dias_desde_iny"] <= dias + config.TOLERANCIA_EXACTA_DIAS)]
    if not exacto.empty:
        return exacto.iloc[0]
    return rango.loc[(rango["dias_desde_iny"] - dias).abs().idxmin()]


def _valores_av(grupo: pd.DataFrame) -> pd.Series:
    """CELDA 59: AV en letras en semanas 12/16/20/52/104 (se omiten las comorbilidades por semana:
    el notebook las calculaba pero nunca las exportaba)."""
    grupo = grupo.sort_values("fecha_consulta")
    res = {}
    for sem, dias in config.SEMANAS_ACUMULADAS.items():
        fila = _visita_por_semana(grupo, dias)
        res[f"AV_letras_sem{sem}"] = np.nan if fila is None else fila.get("AV_letras", np.nan)
    return pd.Series(res)


def construir_evolucion_av(df_consultas: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 59, 64, 65."""
    valores = df_consultas.groupby("pacienteojoreingreso").apply(_valores_av).reset_index()
    iniciales = (df_consultas.sort_values(["pacienteojoreingreso", "fecha_consulta"])
                 .groupby("pacienteojoreingreso").first().reset_index()
                 [["pacienteojoreingreso", "AV_letras", "fecha_consulta", "fecha_primera_iny"]]
                 .rename(columns={"AV_letras": "AV_letras_inicial", "fecha_consulta": "Fecha_inicial"}))
    ev = iniciales.merge(valores, on="pacienteojoreingreso")
    for sem in config.SEMANAS_ACUMULADAS:
        ev[f"dif_lts_sem{sem}"] = ev[f"AV_letras_sem{sem}"] - ev["AV_letras_inicial"]
    for sem in config.SEMANAS_ACUMULADAS:
        ev[f"clase_AV_sem{sem}"] = ev[f"dif_lts_sem{sem}"].apply(clasificar_cambio_av)
    return ev


# =========================================================================== ayudas / OCT
_OCT_COLS = {  # sufijo de salida -> columna en ayudas
    "": "oct", "_dep": "oct_dep", "_irf": "oct_irf", "_srf": "oct_srf", "_hemo": "oct_hemorragia",
    "_quistes": "oct_quistes", "_hrfs": "oct_hrfs", "_atrofia": "oct_atrofia", "_fibrosis": "oct_fibrosis",
}


def _valores_oct(grupo: pd.DataFrame) -> pd.Series:
    """CELDA 61."""
    grupo = grupo.sort_values("fecha_ayuda")
    res = {}
    for sem, dias in config.SEMANAS_ACUMULADAS.items():
        fila = _visita_por_semana(grupo, dias)
        for suf, col in _OCT_COLS.items():
            res[f"OCT{suf}_sem{sem}"] = np.nan if fila is None else fila.get(col, np.nan)
        res[f"FechaVisita_sem{sem}"] = np.nan if fila is None else fila["fecha_ayuda"]
    return pd.Series(res)


def _clasificar_oct(inicial, actual):
    """CELDA 71."""
    if pd.isna(actual) or pd.isna(inicial):
        return np.nan
    u = config.UMBRAL_OCT_MICRAS
    if inicial <= u and actual <= u:
        return "Se mantiene ≤ 300"
    if inicial > u and actual > u:
        return "Se mantiene > 300"
    if inicial > u and actual <= u:
        return "Entra al rango normal"
    return "Sale del rango normal"


def construir_evolucion_oct(df_ayudas: pd.DataFrame, fechas: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 41, 61, 69-73."""
    exigir_columnas(df_ayudas, ["pacienteojoreingreso", "fecha_ayuda", "oct", "oct_irf", "oct_srf"], "ayudas")
    df = df_ayudas.merge(fechas, on="pacienteojoreingreso", how="left")
    df["dias_desde_iny"] = (df["fecha_ayuda"] - df["fecha_primera_iny"]).dt.days

    valores = df.groupby("pacienteojoreingreso").apply(_valores_oct).reset_index()
    cols_ini = ["pacienteojoreingreso", "fecha_ayuda", "fecha_primera_iny"] + list(_OCT_COLS.values())
    iniciales = (df.sort_values(["pacienteojoreingreso", "fecha_ayuda"]).groupby("pacienteojoreingreso")
                 .first().reset_index()[cols_ini])
    iniciales = iniciales.rename(columns={"fecha_ayuda": "Fecha_inicial",
                                          **{c: f"OCT{s}_inicial" for s, c in _OCT_COLS.items()}})
    ev = iniciales.merge(valores, on="pacienteojoreingreso")

    for sem in config.SEMANAS_ACUMULADAS:
        irf, srf = ev[f"OCT_irf_sem{sem}"], ev[f"OCT_srf_sem{sem}"]
        # Retina seca = sin líquido intra ni subretiniano; NaN si no hay dato
        ev[f"RetinaSeca_sem{sem}"] = np.where(irf.isna(), np.nan, np.where((irf == 0) & (srf == 0), 1, 0))
        ev[f"clase_OCT_sem{sem}"] = ev.apply(lambda r: _clasificar_oct(r["OCT_inicial"], r[f"OCT_sem{sem}"]), axis=1)
        ev[f"dif_micras_sem{sem}"] = ev[f"OCT_sem{sem}"] - ev["OCT_inicial"]
    return ev


# =========================================================================== respondedor
def _clasificar_respuesta(dif_letras, retina_seca, dx) -> object:
    """CELDA 82."""
    if pd.isna(dif_letras) or pd.isna(retina_seca):
        return np.nan
    umbral = config.UMBRAL_PERDIDA_AV.get(dx, config.UMBRAL_PERDIDA_AV_DEFECTO)
    criterio_av = dif_letras <= umbral
    criterio_liquido = retina_seca == 0
    if criterio_av and criterio_liquido:
        return "No respondedor"
    if criterio_av or criterio_liquido:
        return "Respondedor parcial"
    return "Respondedor"


def construir_base_evolucion(ev_av: pd.DataFrame, ev_oct: pd.DataFrame, df_lb: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 75-93: une AV + OCT + diagnóstico; respondedor S16 y oportunidad de inicio de tratamiento."""
    cols_av = (["pacienteojoreingreso", "AV_letras_inicial"]
               + [f"{p}_sem{s}" for p in ("AV_letras", "dif_lts", "clase_AV") for s in config.SEMANAS_ACUMULADAS])
    base = ev_oct.merge(ev_av[cols_av], how="left", on="pacienteojoreingreso")
    base = base.merge(df_lb[["pacienteojoreingreso", "dx_ppal", "dx_fecha"]], on="pacienteojoreingreso", how="left")
    base["Respondedor_sem16"] = base.apply(
        lambda r: _clasificar_respuesta(r["dif_lts_sem16"], r["RetinaSeca_sem16"], r["dx_ppal"]), axis=1)

    base["fecha_primera_iny"] = pd.to_datetime(base["fecha_primera_iny"])
    base["dx_fecha"] = pd.to_datetime(base["dx_fecha"], errors="coerce", dayfirst=True)
    # El notebook termina dejando esta columna como timedelta; aquí se guarda en días (mismo valor)
    base["Oportunidad_inicio_tto"] = (base["fecha_primera_iny"] - base["dx_fecha"]).dt.days
    return base


# =========================================================================== complicaciones
def calcular_complicaciones(df_consultas: pd.DataFrame) -> pd.DataFrame:
    """CELDAS 43 y 88: endoftalmitis hasta la semana 104.

    OJO (heredado del notebook): se calcula solo sobre las consultas de la ventana de 12 a 20
    semanas post primera inyección ('resultado'), no sobre todas las consultas.
    """
    dif_sem = (df_consultas["fecha_consulta"] - df_consultas["fecha_primera_iny"]).dt.days / 7
    resultado = df_consultas[(dif_sem >= 12) & (dif_sem <= 20)].copy()

    def _marcar(grupo: pd.DataFrame) -> pd.Series:
        if grupo.empty:  # pandas prueba la función con un grupo vacío para detectar mutaciones
            return pd.Series({"Complicacion": np.nan})
        f0 = grupo["fecha_primera_iny"].iloc[0]
        if pd.isna(f0):
            return pd.Series({"Complicacion": np.nan})
        rango = grupo[(grupo["fecha_consulta"] >= f0) & (grupo["fecha_consulta"] <= f0 + pd.Timedelta(days=728))]
        return pd.Series({"Complicacion": 1 if (rango["endoftalmitis"] == 1).any() else 0})

    comp = resultado.groupby("pacienteojoreingreso").apply(_marcar).reset_index()
    resultado = resultado.merge(comp, on="pacienteojoreingreso", how="left")
    if "agu_vis_num" in resultado.columns:
        resultado["agu_vis_num"] = reemplazar_av_especial(resultado["agu_vis_num"])
    return resultado


# =========================================================================== orquestación
def transformar_bev(datos: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    df_lb, df_apl = datos["lineabase"], datos["aplicaciones"]

    log.info("Pacientes / línea base")
    pacientes = preparar_pacientes(datos["pacientes"], df_lb)

    log.info("Adherencia y aplicaciones")
    adherencia, df_apl = consolidar_adherencia(df_apl)
    oportunidad = calcular_oportunidad_aplicacion(df_apl)

    log.info("Evolución de AV")
    fechas = _fechas_importantes(df_apl, df_lb)
    consultas = preparar_consultas(datos["consultas"], fechas)
    ev_av = construir_evolucion_av(consultas)

    log.info("Evolución de OCT y respondedor")
    ev_oct = construir_evolucion_oct(datos["ayudas"], fechas)
    evolucion = construir_base_evolucion(ev_av, ev_oct, df_lb)

    log.info("Complicaciones (endoftalmitis)")
    complicaciones = calcular_complicaciones(consultas)
    pacientes = pacientes.merge(
        complicaciones[["pacienteojoreingreso", "Complicacion"]].drop_duplicates("pacienteojoreingreso"),
        on="pacienteojoreingreso", how="left")

    return {"pacientes": pacientes, "adherencia": adherencia, "oportunidad_apl": oportunidad,
            "evolucion": evolucion, "complicaciones": complicaciones}
