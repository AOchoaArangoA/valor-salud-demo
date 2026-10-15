"""Transformaciones de Consolidar_base_costosSD.ipynb.

El notebook repetía 4 veces el mismo patrón (tratamiento, medicamentos, consultas, ayudas):
    costo unitario por evento -> trimestre relativo a la 1ª aplicación (T1..T12)
    -> pivote costos (_Tn) y conteos (_Nn) por grupo -> sumas anuales (_Anio1..3 / _NAnio1..3)
    -> "CostoFin": costo anual válido solo si hay >= 2 trimestres con información.
Aquí ese patrón vive en `pivotar_trimestral` + `costo_final_anual`.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from . import config
from .utils import exigir_columnas, get_logger

log = get_logger(__name__)
ID = "pacienteojoreingreso"
COL_GRUPO = "GrupoAjustado Valor en Salud"
COL_COSTO = "Costo promedio unitario"
ANIOS = {1: range(1, 5), 2: range(5, 9), 3: range(9, 13)}


# =========================================================================== maestra de costos
def normalizar_maestra(maestra: pd.DataFrame) -> pd.DataFrame:
    """Deja la maestra en el formato que usaba el notebook (df_ajustado).

    Si ya trae 'GrupoAjustado Valor en Salud' y 'Medicamento_anonimizado' (tabla externa original)
    se respeta. Si es la hoja 'maestra_costos' del libro (o el dummy por año, que repite cada fila
    una vez por año), esas dos columnas se derivan:
      - GrupoAjustado: config.GRUPO_AJUSTADO_EXPLICITO, o '<prefijo>_<Describe>' / 'Med_<abrev>'.
      - Medicamento_anonimizado: código de la molécula = posición del NOMBRE dentro de 'Medicamentos'
        (estable entre años: si el dummy repite Aflibercept en 7 filas -una por año-, las 7 reciben
        el mismo código).
    """
    exigir_columnas(maestra, ["Grupo", "Describe", COL_COSTO], "maestra_costos")
    m = maestra.copy()
    if COL_GRUPO not in m.columns:
        def _grupo(fila) -> str:
            clave = (fila["Grupo"], fila["Describe"])
            if clave in config.GRUPO_AJUSTADO_EXPLICITO:
                return config.GRUPO_AJUSTADO_EXPLICITO[clave]
            if fila["Grupo"] == "Medicamentos":
                return "Med_" + config.ABREV_MEDICAMENTO.get(fila["Describe"], str(fila["Describe"]).replace(" ", ""))
            prefijo = config.PREFIJO_GRUPO.get(fila["Grupo"], str(fila["Grupo"]).replace(" ", ""))
            return f"{prefijo}_{str(fila['Describe']).replace(' ', '')}"
        m[COL_GRUPO] = m.apply(_grupo, axis=1)
    if "Medicamento_anonimizado" not in m.columns:
        es_med = m["Grupo"] == "Medicamentos"
        nombres = m.loc[es_med, "Describe"].drop_duplicates().tolist()  # orden de 1ª aparición
        codigo = {nombre: i + 1 for i, nombre in enumerate(nombres)}
        m["Medicamento_anonimizado"] = np.nan
        m.loc[es_med, "Medicamento_anonimizado"] = m.loc[es_med, "Describe"].map(codigo)
    return m


def tiene_variacion_anual(maestra: pd.DataFrame) -> bool:
    """True si la maestra trae más de un costo por (Grupo, Describe) según el año (el dummy por
    año generado en tools/generate_dummy_costos_maestra.py; el histórico trae un solo costo)."""
    if "Año" not in maestra.columns:
        return False
    return bool(maestra.groupby(["Grupo", "Describe"])["Año"].nunique().max() > 1)


def _costear(df: pd.DataFrame, maestra: pd.DataFrame, grupo_maestra: str, col_llave: str,
             col_maestra: str = "Describe", col_fecha: str | None = None) -> pd.DataFrame:
    """Cruza cada evento con su costo unitario. Si la maestra varía por año (ver
    `tiene_variacion_anual`) y se da `col_fecha`, cruza además por el año calendario de esa fecha;
    si no, es el cruce plano de siempre (un costo único por concepto, sin importar el año)."""
    anual = col_fecha is not None and tiene_variacion_anual(maestra)
    cols = [col_maestra, COL_GRUPO, COL_COSTO] + (["Año"] if anual else [])
    sub = maestra[maestra["Grupo"] == grupo_maestra][cols]
    if not anual:
        return df.merge(sub, how="left", left_on=col_llave, right_on=col_maestra)
    df = df.copy()
    df["_anio_evento"] = df[col_fecha].dt.year
    fusion = df.merge(sub, how="left", left_on=[col_llave, "_anio_evento"], right_on=[col_maestra, "Año"])
    return fusion.drop(columns=["_anio_evento", "Año"])


# =========================================================================== núcleo reutilizable
def _con_trimestre(df: pd.DataFrame, col_fecha: str, solo_positivos: bool) -> pd.DataFrame:
    """Trimestre relativo a la primera aplicación: (días//30)//3 + 1, limitado a T1..T12."""
    df = df.copy()
    dias = (df[col_fecha] - df["fecha_primera_aplicacion"]).dt.days
    df["trimestre_rel"] = ((dias // 30) // 3 + 1)
    if solo_positivos:  # consultas/ayudas previas a la 1ª inyección se descartan
        df = df[df["trimestre_rel"] > 0]
    df = df[df["trimestre_rel"] <= config.TRIMESTRES_MAX]
    df["trimestre_rel"] = df["trimestre_rel"].astype(int)
    return df


def pivotar_trimestral(df: pd.DataFrame, todas_las_columnas: bool = False) -> pd.DataFrame:
    """Costos (<grupo>_T1..) y conteos (<grupo>_N1..) por trimestre + sumas anuales.

    `todas_las_columnas=True` reproduce el comportamiento del notebook para consultas: crea siempre
    T1..T12 aunque ningún paciente tenga registros en ese trimestre.
    """
    costos = df.groupby([ID, "trimestre_rel", COL_GRUPO])[COL_COSTO].sum().reset_index()
    conteos = df.groupby([ID, "trimestre_rel", COL_GRUPO]).size().reset_index(name="n")

    def _pivot(base: pd.DataFrame, valor: str, prefijo: str) -> pd.DataFrame:
        p = base.pivot_table(index=ID, columns=[COL_GRUPO, "trimestre_rel"], values=valor, aggfunc="sum", fill_value=0)
        p.columns = [f"{g}_{prefijo}{t}" for g, t in p.columns]
        return p.reset_index()

    piv = _pivot(costos, COL_COSTO, "T").merge(_pivot(conteos, "n", "N"), on=ID, how="outer")

    for grupo in df[COL_GRUPO].dropna().unique():
        for anio, trims in ANIOS.items():
            for pref_t, pref_a in (("T", "Anio"), ("N", "NAnio")):
                cols = [f"{grupo}_{pref_t}{i}" for i in trims]
                if todas_las_columnas:
                    for c in cols:
                        if c not in piv.columns:
                            piv[c] = 0
                piv[f"{grupo}_{pref_a}{anio}"] = piv[[c for c in cols if c in piv.columns]].sum(axis=1)
    return piv


def costo_final_anual(piv: pd.DataFrame, columnas_trimestre: Dict[int, List[str]], prefijo_salida: str,
                     ignorar_ceros: bool) -> pd.DataFrame:
    """Costo anual válido solo si hay >= MIN_TRIMESTRES_CON_COSTO trimestres con información.

    `columnas_trimestre`: {anio: [columnas de costo de sus 4 trimestres]}.
    `ignorar_ceros=True`  (tratamiento y medicamentos): un trimestre en 0 no cuenta como información.
    `ignorar_ceros=False` (consultas y ayudas): tal como en el notebook, solo cuenta que la columna exista
                          (por lo que la regla casi nunca filtra). Ver README, sección "Hallazgos".
    """
    for anio, cols in columnas_trimestre.items():
        cols = [c for c in cols if c in piv.columns]
        bloque = piv[cols].replace(0, np.nan) if ignorar_ceros else piv[cols]
        cumple = bloque.notna().sum(axis=1) >= config.MIN_TRIMESTRES_CON_COSTO
        piv[f"{prefijo_salida}{anio}"] = np.where(cumple, piv[cols].sum(axis=1), np.nan)
    return piv


def _cols_por_anio(patron: str) -> Dict[int, List[str]]:
    """{1: ['<patron>1', ..., '<patron>4'], 2: [...5..8], 3: [...9..12]} con patron tipo 'Cons_Retina_T'."""
    return {a: [f"{patron}{i}" for i in trims] for a, trims in ANIOS.items()}


# =========================================================================== orquestación
def transformar_costos(datos: Dict[str, pd.DataFrame], maestra: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    df_apl, df_cons, df_ayu = datos["aplicaciones"], datos["consultas"], datos["ayudas"]
    exigir_columnas(df_apl, [ID, "fecha_aplicacion", "tipo_tto", "molecula", "dx_ppal_desc"], "aplicaciones")
    m = normalizar_maestra(maestra)

    # Primera aplicación por paciente-ojo (CELDA 43)
    primera = (df_apl.sort_values("fecha_aplicacion").drop_duplicates(subset=[ID], keep="first")
               [[ID, "fecha_aplicacion", "dx_ppal_desc"]].rename(columns={"fecha_aplicacion": "fecha_primera_aplicacion"}))

    # ---- costeo por tipo de evento (CELDAS 8-38)
    tto = _costear(df_apl, m, "Tipo de tratamiento", "tipo_tto", col_fecha="fecha_aplicacion")
    # 'molecula' es código numérico anonimizado en un prestador (P1) y el nombre en texto en
    # otro; se cruza por el que corresponda según cómo llegó la columna.
    col_llave_med, col_maestra_med = (("molecula", "Describe") if df_apl["molecula"].dtype == object
                                      else ("molecula", "Medicamento_anonimizado"))
    med = _costear(df_apl, m, "Medicamentos", col_llave_med, col_maestra=col_maestra_med, col_fecha="fecha_aplicacion")
    cons = df_cons.copy()
    cons["tipo_consulta"] = cons["tipo_consulta"].str.replace("oftalmología", "Oftalmología", regex=True)
    cons = _costear(cons, m, "Consultas", "tipo_consulta", col_fecha="fecha_consulta")
    ayu = _costear(df_ayu, m, "Tipo de ayuda", "tipo_ayuda", col_fecha="fecha_ayuda")
    # Ayudas sin cruce se costean como 'Otros' (CELDA 37-38)
    otros = m[(m["Grupo"] == "Tipo de ayuda") & (m["Describe"] == "Otros")]
    if not otros.empty:
        sin_costo = ayu[COL_COSTO].isna()
        if tiene_variacion_anual(m):
            otros_por_anio = otros.set_index("Año")[COL_COSTO]
            ayu.loc[sin_costo, COL_COSTO] = ayu.loc[sin_costo, "fecha_ayuda"].dt.year.map(otros_por_anio)
        else:
            ayu.loc[sin_costo, COL_COSTO] = otros[COL_COSTO].iloc[0]
        ayu[COL_GRUPO] = ayu[COL_GRUPO].fillna(otros[COL_GRUPO].iloc[0])

    tto = tto.merge(primera[[ID, "fecha_primera_aplicacion"]], how="left", on=ID)
    med = med.merge(primera[[ID, "fecha_primera_aplicacion"]], how="left", on=ID)
    cons = cons.merge(primera[[ID, "fecha_primera_aplicacion"]], how="left", on=ID)
    ayu = ayu.merge(primera[[ID, "fecha_primera_aplicacion"]], how="left", on=ID)

    # ---- pivotes trimestrales
    tto = _con_trimestre(tto, "fecha_aplicacion", solo_positivos=False)
    piv_tto = pivotar_trimestral(tto)
    piv_med = pivotar_trimestral(_con_trimestre(med, "fecha_aplicacion", solo_positivos=False))
    piv_cons = pivotar_trimestral(_con_trimestre(cons, "fecha_consulta", solo_positivos=True), todas_las_columnas=True)
    piv_ayu = pivotar_trimestral(_con_trimestre(ayu, "fecha_ayuda", solo_positivos=True))

    # ---- medicamentos agrupados: suma de todas las moléculas por trimestre / año (CELDA 59)
    base_med = pd.DataFrame({ID: piv_med[ID]})
    for i in range(1, config.TRIMESTRES_MAX + 1):
        base_med[f"medicamentos_t{i}"] = piv_med.filter(regex=f"_T{i}$").sum(axis=1)
        base_med[f"med_N_t{i}"] = piv_med.filter(regex=f"_N{i}$").sum(axis=1)
    for a in ANIOS:
        base_med[f"medicamentos_anio{a}"] = piv_med.filter(regex=f"_Anio{a}$").sum(axis=1)
        base_med[f"med_N_anio{a}"] = piv_med.filter(regex=f"_NAnio{a}$").sum(axis=1)
    costo_final_anual(base_med, _cols_por_anio("medicamentos_t"), "CostoFin_medicamentos_Anio", ignorar_ceros=True)

    # ---- costo final anual por componente
    for grupo in [c[:-len("_Anio1")] for c in piv_tto.columns if c.endswith("_Anio1")]:
        costo_final_anual(piv_tto, _cols_por_anio(f"{grupo}_T"), f"CostoFin_{grupo}_Anio", ignorar_ceros=True)
    costo_final_anual(piv_cons, _cols_por_anio("Cons_Retina_T"), "costofin_cons_retina_anio", ignorar_ceros=False)
    costo_final_anual(piv_cons, _cols_por_anio("Cons_Oftalmo_T"), "costofin_cons_oftalmo_anio", ignorar_ceros=False)
    costo_final_anual(piv_ayu, _cols_por_anio("TipoAyuda_OCT_T"), "costofin_ayu_anio", ignorar_ceros=False)

    final = consolidar_costo_final(base_med, piv_tto, piv_cons, piv_ayu, tto, primera)
    return {"costos_final": final, "costos_tto": piv_tto, "costos_med_agrupado": base_med,
            "costos_med_detalle": piv_med, "costos_consultas": piv_cons, "costos_ayudas": piv_ayu}


def consolidar_costo_final(base_med, piv_tto, piv_cons, piv_ayu, tto, primera) -> pd.DataFrame:
    """CELDAS 84-96: une los CostoFin por componente, suma por año y clasifica por percentiles."""
    partes: List[pd.DataFrame] = []
    for base in (base_med, piv_tto, piv_cons, piv_ayu):
        cols = [c for c in base.columns if "costofin_" in c.lower()] + [ID]
        partes.append(base[cols].copy())
    merged = partes[0]
    for p in partes[1:]:
        merged = merged.merge(p, on=ID, how="outer")
    merged.columns = merged.columns.str.lower()

    for a in ANIOS:
        suma = merged.filter(regex=f"anio{a}").sum(axis=1)
        # Regla del notebook: se acepta el costo anual si la suma es >= 2 (el mínimo es de "unidades", no de trimestres)
        merged[f"costofin_anio{a}"] = np.where(suma >= 2, suma, np.nan)

    orden = [ID]
    for a in ANIOS:
        orden += [f"costofin_medicamentos_anio{a}", f"costofin_tipotto_inyiv_anio{a}", f"costofin_cons_retina_anio{a}",
                  f"costofin_cons_oftalmo_anio{a}", f"costofin_ayu_anio{a}", f"costofin_anio{a}"]
    for c in orden:
        if c not in merged.columns:
            merged[c] = np.nan
    merged = merged[orden]

    dx = tto[[ID, "dx_ppal_desc"]].drop_duplicates().rename(columns={"dx_ppal_desc": "dx_ppal_desc_x"})
    merged = merged.merge(dx, on=ID, how="left")

    # Clase de costo (Bajo/Medio/Alto) por percentiles 25/75 DENTRO de cada diagnóstico.
    # El notebook del zip calcula percentiles globales, pero los Excel que se usaron (base_costos_finales_
    # consolidado) los traen por diagnóstico; se sigue el output efectivo.
    for a in ANIOS:
        col = f"costofin_anio{a}"
        por_dx = merged.groupby("dx_ppal_desc_x")[col]
        merged[f"p25_anio{a}"] = por_dx.transform(lambda x: x.quantile(0.25))
        merged[f"p75_anio{a}"] = por_dx.transform(lambda x: x.quantile(0.75))
        merged[f"{col}_class"] = np.where(merged[col] < merged[f"p25_anio{a}"], "Bajo",
                                          np.where(merged[col] > merged[f"p75_anio{a}"], "Alto",
                                                   np.where(merged[col].isna(), "", "Medio")))
    return merged
