"""Utilidades compartidas: logging, validaciones y conversiones de agudeza visual."""
from __future__ import annotations

import logging
import math
import warnings
from typing import Iterable

import numpy as np
import pandas as pd

from . import config


def get_logger(nombre: str) -> logging.Logger:
    logger = logging.getLogger(nombre)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=config.LOG_LEVEL,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    # Los notebooks silenciaban warnings de pandas (groupby.apply); se acota a esas categorías.
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    return logger


def exigir_columnas(df: pd.DataFrame, columnas: Iterable[str], nombre: str) -> None:
    """Falla temprano y con mensaje claro si el insumo cambió de estructura."""
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        raise KeyError(f"Al insumo '{nombre}' le faltan columnas requeridas: {faltan}")


def reemplazar_av_especial(serie: pd.Series) -> pd.Series:
    """HBW/LP/NLP: 20.000 -> 4.000, 200.000 -> 10.000, 2.000.000 -> 20.000."""
    return serie.replace(config.MAPA_AV_ESPECIAL)


def snellen_a_logmar(valor) -> float:
    """'20/x' -> logMAR (redondeado a 2 decimales). NaN si no es interpretable."""
    if pd.isna(valor):
        return np.nan
    texto = str(valor).strip()
    if "/" not in texto:
        return np.nan
    try:
        num, den = texto.split("/")
        return round(math.log10(float(den) / float(num)), 2)
    except (ValueError, ZeroDivisionError):
        return np.nan


def clasificar_cambio_av(valor) -> object:
    """Δ letras: < -5 empeora, > 5 mejora, resto mantiene."""
    if pd.isna(valor):
        return np.nan
    if valor < -config.UMBRAL_CLASE_AV_LETRAS:
        return "empeora"
    if valor > config.UMBRAL_CLASE_AV_LETRAS:
        return "mejora"
    return "mantiene"
