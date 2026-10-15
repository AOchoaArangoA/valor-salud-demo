"""Punto de entrada:  python -m pipeline.main [--xlsm RUTA] [--output-dir DIR] [--excel]"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import config
from .extract import es_maestra_dummy, leer_ecv, leer_hojas, leer_maestra_costos
from .load import escribir_metadata, guardar
from .mart import construir_mart
from .transform_bev import transformar_bev
from .transform_costos import transformar_costos
from .transform_ecv import transformar_ecv
from .utils import get_logger

log = get_logger("pipeline")


def diagnosticar_insumos(datos) -> dict:
    """Completitud de los campos que sostienen KPIs del tablero. La app apaga los KPIs no evaluables."""
    ayu, apl = datos["ayudas"], datos["aplicaciones"]
    pct = lambda serie: round(float(serie.notna().mean()) * 100, 1)  # noqa: E731
    dq = {
        "oct_srf_completo_pct": pct(ayu["oct_srf"]),
        "oct_irf_distintos": int(ayu["oct_irf"].nunique()),
        "fecha_programacion_completa_pct": pct(apl["fecha_programacion"]),
    }
    dq["retina_seca_evaluable"] = dq["oct_srf_completo_pct"] >= 5 and dq["oct_irf_distintos"] > 1
    dq["cumplimiento_programacion_evaluable"] = dq["fecha_programacion_completa_pct"] >= 5
    for clave, ok in (("retina seca / respondedor", dq["retina_seca_evaluable"]),
                      ("cumplimiento de programación", dq["cumplimiento_programacion_evaluable"])):
        if not ok:
            log.warning("Insumo sin datos suficientes para: %s (ver metadata.json)", clave)
    return dq


def ejecutar(xlsm: Optional[Path] = None, output_dir: Optional[Path] = None, excel: bool = False, *,
             costos_modo: str = "auto", costos_path: Optional[Path] = None, ecv_path="auto",
             prestador: Optional[str] = None, extra_meta: Optional[dict] = None) -> Path:
    """Corre todo el proceso y devuelve la carpeta donde quedaron los resultados.

    `costos_modo`: 'auto' (variables de entorno) | 'libro' | 'archivo' (con `costos_path`) | 'dummy'.
    `ecv_path`: 'auto' (VLM_ECV_PATH), una ruta, o None (sin ECV: los indicadores de calidad de vida quedan vacíos).
    """
    t0 = time.time()
    xlsm = Path(xlsm or config.XLSM_PATH or "")
    datos = leer_hojas(xlsm)

    log.info("== BEV: adherencia, evolución AV/OCT, respondedor")
    bev = transformar_bev(datos)

    log.info("== Costos")
    maestra_costos = leer_maestra_costos(datos, costos_modo, costos_path)
    costos_dummy = es_maestra_dummy(maestra_costos)
    costos = transformar_costos(datos, maestra_costos)

    log.info("== ECV")
    ruta_ecv = config.ECV_PATH if ecv_path == "auto" else ecv_path
    ecv = transformar_ecv(leer_ecv(ruta_ecv) if ruta_ecv else None, datos["calidadvida"])

    log.info("== Mart del tablero")
    mart = construir_mart(bev, costos, ecv)

    destino = Path(output_dir or config.OUTPUT_DIR)
    guardar({**bev, **costos, "ecv": ecv, "tablero_pteojo": mart}, destino, excel=excel)
    if costos_modo == "auto":
        fuente = config.COSTOS_MAESTRA_PATH.name if config.COSTOS_MAESTRA_PATH else "hoja maestra_costos del libro"
    else:
        fuente = {"libro": "hoja maestra_costos del libro", "dummy": config.DUMMY_COSTOS_PATH.name}.get(
            costos_modo, Path(costos_path).name if costos_path else "archivo de costos")
    escribir_metadata(destino, {
        "prestador": prestador or config.PRESTADOR,
        "insumo": xlsm.name,
        "costos_fuente": fuente,
        "costos_es_dummy": costos_dummy,
        "ecv_fuente": Path(ruta_ecv).name if ruta_ecv else None,
        "av_rellena_por_logmar": config.RELLENAR_AV_POR_LOGMAR,
        "oportunidad_inicio_max_dias": config.OPORTUNIDAD_INICIO_MAX_DIAS,
        "tolerancia_programacion_dias": config.TOLERANCIA_PROGRAMACION_DIAS,
        "filas_mart": int(len(mart)),
        "calidad_insumo": diagnosticar_insumos(datos),
        **(extra_meta or {}),
    })
    log.info("Pipeline terminado en %.0f s", time.time() - t0)
    return destino


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Pipeline Valor en Salud (retina)")
    ap.add_argument("--xlsm", type=Path, help="Libro de insumos (por defecto VLM_XLSM_PATH)")
    ap.add_argument("--output-dir", type=Path, help="Carpeta de salida (por defecto VLM_OUTPUT_DIR)")
    ap.add_argument("--excel", action="store_true", help="Además de parquet, escribe los Excel con los nombres de los notebooks")
    args = ap.parse_args(argv)
    try:
        ejecutar(args.xlsm, args.output_dir, args.excel)
    except (FileNotFoundError, KeyError, ValueError) as e:   # insumos ausentes o con estructura distinta
        log.error("%s", e)
        return 2
    except Exception:                            # cualquier otro fallo: traza completa en el log
        log.exception("El pipeline falló")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
