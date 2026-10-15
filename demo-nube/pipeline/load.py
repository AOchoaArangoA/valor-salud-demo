"""Carga: escribe las tablas (parquet para la app; Excel opcional con los nombres del notebook)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .utils import get_logger

log = get_logger(__name__)

# nombre interno -> nombre del Excel que generaban los notebooks
NOMBRES_LEGADO = {
    "pacientes": "Base_pacientes", "adherencia": "Adherencia_aplicaciones",
    "oportunidad_apl": "Oportunidad_apl_tto", "evolucion": "Base_evol_OCT_AV_Respondedor",
    "complicaciones": "Complicaciones_endoftalmitis",
    "costos_final": "base_costos_finales_consolidado", "costos_tto": "conteos_costos_tipotto_consolidado",
    "costos_med_agrupado": "conteos_costos_medicamentos_agrupados_consolidado",
    "costos_med_detalle": "conteos_costos_medicamentos_consolidado",
    "costos_consultas": "conteos_costos_consultas_consolidado", "costos_ayudas": "conteos_costos_ayudas_consolidado",
}


def _compatible_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas object con números (p. ej. tras groupby.apply) -> numéricas; el resto -> texto."""
    df = df.copy()
    for col in df.select_dtypes(include="object").columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            if not df[col].map(lambda v: v is None or isinstance(v, (str, pd.Timestamp)) or pd.isna(v)).all():
                df[col] = df[col].astype(str)
    return df


def guardar(tablas: Dict[str, pd.DataFrame], directorio: Path, excel: bool = False) -> None:
    directorio.mkdir(parents=True, exist_ok=True)
    for nombre, df in tablas.items():
        df = _compatible_parquet(df)
        df.to_parquet(directorio / f"{nombre}.parquet", index=False)
        if excel:
            df.to_excel(directorio / f"{NOMBRES_LEGADO.get(nombre, nombre)}.xlsx", index=False)
        log.info("guardado %-22s %6d filas", nombre, len(df))


def escribir_metadata(directorio: Path, info: Dict[str, Any]) -> None:
    """Procedencia de la corrida: la app la muestra para que nadie confunda costos de referencia con oficiales."""
    info = {"generado": datetime.now().isoformat(timespec="seconds"), **info}
    (directorio / "metadata.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
