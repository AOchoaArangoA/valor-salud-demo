"""ECV (calidad de vida): resumen por paciente.

No existe un notebook de ECV en los insumos: solo sus salidas (prom_dimensiones_pteojo.xlsx con el
promedio por dimensión y total, y tiempo_entre_encuestas.xlsx). Por eso aquí NO se recalcula el puntaje:
se consume el promedio total y se pivota encuesta 1 vs encuesta 2. El tiempo entre encuestas sí se
recalcula (es trivial) desde la hoja 'calidadvida'.

La ECV es por PACIENTE (numero_doc), no por paciente-ojo: en el mart se replica a cada ojo del paciente.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import config
from .utils import exigir_columnas, get_logger

log = get_logger(__name__)


COLUMNAS_ECV = ["numero_doc", "ecv1", "ecv2", "delta_ecv", "fecha_ecv1", "fecha_ecv2", "semanas_entre_ecv"]
# Además del total: una columna por dimensión y encuesta (ecvd_<dimensión>_1 / _2).
COLUMNAS_DIM = [f"ecvd_{k}_{n}" for k, _, _ in config.ECV_DIMENSIONES for n in (1, 2)]


def ecv_vacia() -> pd.DataFrame:
    """Sin resultado de calidad de vida: el tablero muestra '—' en ECV en vez de mezclar datos de otro prestador."""
    return pd.DataFrame({**{c: pd.Series(dtype="float64") for c in COLUMNAS_DIM},
                         "numero_doc": pd.Series(dtype="float64"), "ecv1": pd.Series(dtype="float64"),
                         "ecv2": pd.Series(dtype="float64"), "delta_ecv": pd.Series(dtype="float64"),
                         "fecha_ecv1": pd.Series(dtype="datetime64[ns]"), "fecha_ecv2": pd.Series(dtype="datetime64[ns]"),
                         "semanas_entre_ecv": pd.Series(dtype="float64")})


def transformar_ecv(df_prom: Optional[pd.DataFrame], df_calidadvida: pd.DataFrame) -> pd.DataFrame:
    if df_prom is None:
        log.warning("Sin resultado de ECV para este insumo: los indicadores de calidad de vida quedan vacíos.")
        return ecv_vacia()
    exigir_columnas(df_prom, ["numero_doc", "nro_encuesta", "Total_prom"], "ECV (prom_dimensiones)")
    exigir_columnas(df_calidadvida, ["numero_doc", "nro_encuesta", "fechaencuesta"], "calidadvida")

    prom = df_prom.copy()
    prom["numero_doc"] = pd.to_numeric(prom["numero_doc"], errors="coerce")
    dup = int(prom.duplicated(["numero_doc", "nro_encuesta"]).sum())
    if dup:
        log.warning("ECV: %d filas repetidas por paciente y encuesta; se conserva la primera", dup)
    total = prom.pivot_table(index="numero_doc", columns="nro_encuesta", values="Total_prom", aggfunc="first")
    total = total.reindex(columns=[1, 2]).rename(columns={1: "ecv1", 2: "ecv2"})
    total["delta_ecv"] = total["ecv2"] - total["ecv1"]

    fechas = df_calidadvida.pivot_table(index="numero_doc", columns="nro_encuesta", values="fechaencuesta", aggfunc="first")
    fechas = fechas.reindex(columns=[1, 2]).rename(columns={1: "fecha_ecv1", 2: "fecha_ecv2"})
    fechas["semanas_entre_ecv"] = (fechas["fecha_ecv2"] - fechas["fecha_ecv1"]).dt.days / 7

    dims = prom.pivot_table(index="numero_doc", columns="nro_encuesta", aggfunc="first",
                            values=[f"{k}_prom" for k, _, _ in config.ECV_DIMENSIONES if f"{k}_prom" in prom.columns])
    dims.columns = [f"ecvd_{c.removesuffix('_prom')}_{int(n)}" for c, n in dims.columns]
    dims = dims.reindex(columns=COLUMNAS_DIM)   # dimensión ausente en el archivo -> columna vacía

    ecv = total.join(fechas, how="outer").join(dims, how="outer").reset_index()
    log.info("ECV: %d pacientes (%d con ambas encuestas)", len(ecv), int(ecv["delta_ecv"].notna().sum()))
    return ecv
