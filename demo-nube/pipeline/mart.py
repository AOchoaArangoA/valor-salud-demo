"""Mart del tablero: una fila por paciente-ojo-reingreso con todo lo que consumen los 5 niveles.

Réplica en código de la hoja 'Datos tablero' de "Tablero_DMREn_datos_y_KPIs" (propuesta 17-09-2026),
pero calculada con los datos reales. Las métricas marcadas como DERIVADA no existían en los notebooks
y se definieron aquí a partir de la propuesta (ver README, "Supuestos a validar").
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from . import config
from .utils import get_logger

log = get_logger(__name__)
ID = "pacienteojoreingreso"


def _cumplimiento_programacion(oportunidad: pd.DataFrame) -> pd.DataFrame:
    """DERIVADA: % de aplicaciones 'Cumple' (dentro de la ventana de config.TOLERANCIA_PROGRAMACION_DIAS vs. fecha programada) por paciente-ojo y año."""
    d = oportunidad["dias_desde_primera"]
    o = oportunidad.assign(anio=np.where(d.between(0, 364), 1, np.where(d.between(365, 728), 2, np.nan)))
    o = o[o["anio"].notna() & o["Oportunidad_aplicacion_cat"].notna()]
    o["cumple"] = (o["Oportunidad_aplicacion_cat"] == "Cumple").astype(float)
    r = o.groupby([ID, "anio"])["cumple"].mean().unstack("anio").reindex(columns=[1.0, 2.0])
    r.columns = ["cumplimiento_anio1", "cumplimiento_anio2"]
    if r.isna().all().all():  # 5.3.2 trae fecha_programacion vacía: la métrica no es calculable
        log.warning("cumplimiento de programación: sin datos (fecha_programacion vacía en el insumo)")
    return r.reset_index()


def _extension_ultima_dosis(oportunidad: pd.DataFrame) -> pd.DataFrame:
    """Extensión última dosis: semanas entre la última aplicación del paciente-ojo-reingreso y la anterior
    (solo si tiene al menos 2 aplicaciones)."""
    o = oportunidad.sort_values([ID, "con_dosis"])
    ult = o.groupby(ID).tail(1)
    ult = ult[ult["con_dosis"] >= 2][[ID, "Semanas_Entre_Dosis"]].rename(columns={"Semanas_Entre_Dosis": "extension_ultima_dosis"})
    return ult


def _n_moleculas(serie: pd.Series) -> pd.Series:
    """Moléculas distintas a partir del texto '3, 4' que deja el notebook."""
    return serie.fillna("").apply(lambda t: len([x for x in str(t).split(",") if x.strip()]))


def _si_no(mask: pd.Series, base: pd.Series) -> pd.Series:
    """1/0 con NaN donde no hay dato base."""
    return pd.Series(np.where(base.isna(), np.nan, mask.astype(float)), index=base.index)


def construir_mart(bev: Dict[str, pd.DataFrame], costos: Dict[str, pd.DataFrame], ecv: pd.DataFrame) -> pd.DataFrame:
    # ---- espina dorsal: Base_pacientes (una fila por paciente-ojo-reingreso)
    cols_pac = ["pacienteojoreingreso", "pacienteojo", "numero_doc", "ojo", "reingreso", "dx_ppal", "dx_fecha",
                "medicamento", "sede", "eapb", "sexo", "edad", "Grupo_edad", "egreso_causa", "Complicacion"]
    spine = bev["pacientes"][[c for c in cols_pac if c in bev["pacientes"].columns]]
    dup = int(spine[ID].duplicated().sum())
    if dup:
        log.warning("mart: %d filas duplicadas por pacienteojoreingreso en pacientes; se conserva la primera", dup)
    mart = spine.drop_duplicates(ID).rename(columns={"dx_ppal": "diagnostico"})

    # ---- resultados clínicos
    ev = bev["evolucion"].drop_duplicates(ID)
    cols_ev = ([ID, "AV_letras_inicial", "OCT_inicial", "Oportunidad_inicio_tto", "Respondedor_sem16"]
               + [f"{p}_sem{s}" for p in ("AV_letras", "dif_lts", "OCT", "RetinaSeca", "dif_micras")
                  for s in config.SEMANAS_ACUMULADAS])
    mart = mart.merge(ev[[c for c in cols_ev if c in ev.columns]], on=ID, how="left")

    # ---- adherencia / extensión / inyecciones
    adh = bev["adherencia"].drop_duplicates(ID)
    cols_adh = [ID, "fecha_primera", "apl_anio1", "apl_anio2", "molecula_anio1", "molecula_anio2",
                "apl_acum_sem12", "Adherencia_final_12", "Adherencia_final_16", "Adherencia_final_20",
                "extension_sem52", "extension_sem104"]
    mart = mart.merge(adh[cols_adh], on=ID, how="left")
    mart = mart.merge(_cumplimiento_programacion(bev["oportunidad_apl"]), on=ID, how="left")
    mart = mart.merge(_extension_ultima_dosis(bev["oportunidad_apl"]), on=ID, how="left")
    for a in (1, 2):
        mart[f"n_moleculas_anio{a}"] = _n_moleculas(mart[f"molecula_anio{a}"])

    # ---- utilización y costos
    cf = costos["costos_final"].drop_duplicates(ID)[[ID, "costofin_anio1", "costofin_anio2", "costofin_anio1_class"]]
    mart = mart.merge(cf, on=ID, how="left")
    fuentes = {
        "costos_med_agrupado": ["med_N_anio1", "med_N_anio2"],
        "costos_tto": ["TipoTto_InyIV_NAnio1", "TipoTto_InyIV_NAnio2"],
        "costos_consultas": ["Cons_Retina_NAnio1", "Cons_Retina_NAnio2", "Cons_Oftalmo_NAnio1", "Cons_Oftalmo_NAnio2"],
        "costos_ayudas": ["TipoAyuda_OCT_NAnio1", "TipoAyuda_OCT_NAnio2"],
    }
    for tabla, cols in fuentes.items():
        t = costos[tabla]
        mart = mart.merge(t[[ID] + [c for c in cols if c in t.columns]].drop_duplicates(ID), on=ID, how="left")

    # ---- ECV (por paciente)
    mart = mart.merge(ecv, on="numero_doc", how="left")

    # ---- banderas para el tablero (1/0/NaN)
    mart["oportunidad_ok"] = _si_no(mart["Oportunidad_inicio_tto"] <= config.OPORTUNIDAD_INICIO_MAX_DIAS, mart["Oportunidad_inicio_tto"])
    mart["adherencia_carga"] = _si_no(mart["Adherencia_final_12"] == 1, mart["Adherencia_final_12"])
    mart["respondedor"] = _si_no(mart["Respondedor_sem16"] == "Respondedor", mart["Respondedor_sem16"])
    mart["anio_inicio"] = pd.to_datetime(mart["fecha_primera"]).dt.year
    # 'medicamento' es código anonimizado (P1) o el nombre real en texto; en texto se
    # muestra tal cual, en código se anonimiza como en la propuesta del tablero (MED1, MED2...).
    def _etiqueta_medicamento(x):
        if pd.isna(x):
            return "Sin dato"
        return str(x) if isinstance(x, str) else config.MEDICAMENTO_LABEL.format(codigo=int(x))
    mart["medicamento_label"] = mart["medicamento"].apply(_etiqueta_medicamento)
    # Seguimiento posible: el año 2 solo es comparable si ya transcurrieron 728 días desde la 1ª inyección
    # hasta la última fecha de datos (si no, inyecciones/costos del año 2 estarían censurados).
    fecha_corte = pd.to_datetime(bev["adherencia"]["fecha_ultima"]).max()
    dias_posibles = (fecha_corte - pd.to_datetime(mart["fecha_primera"])).dt.days
    mart["anio1_completo"] = dias_posibles >= 364
    mart["anio2_completo"] = dias_posibles >= 728
    mart["tiene_s52"] = mart["dif_lts_sem52"].notna()
    mart["tiene_s104"] = mart["dif_lts_sem104"].notna()
    log.info("Mart: %d paciente-ojo | %d con AV S52 | %d con AV S104", len(mart), mart["tiene_s52"].sum(), mart["tiene_s104"].sum())
    return mart
