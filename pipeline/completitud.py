"""Completitud del formulario (datos tal como llegan, antes de cualquier cálculo).

Se calcula al correr el pipeline y se guarda en  <processed>/<prestador>/<versión>/completitud_insumo.json :
  - por hoja y por columna: filas, celdas con dato y si la columna es obligatoria;
  - cruces entre hojas: registros que no encuentran su paciente-ojo reingreso (o paciente) en la hoja de referencia.
Solo guarda conteos y porcentajes, nunca datos de pacientes, por eso queda en claro como metadata.json.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from . import config

ARCHIVO = "completitud_insumo.json"
ID_OJO = "pacienteojoreingreso"

# (nombre, hoja que se revisa, columna llave, hoja de referencia): ¿cada registro encuentra su llave en la referencia?
CRUCES = [
    ("Aplicaciones con su paciente-ojo en línea base", "aplicaciones", ID_OJO, "lineabase"),
    ("Consultas con su paciente-ojo en línea base", "consultas", ID_OJO, "lineabase"),
    ("Ayudas diagnósticas con su paciente-ojo en línea base", "ayudas", ID_OJO, "lineabase"),
    ("Línea base con su paciente en la hoja de pacientes", "lineabase", "numero_doc", "pacientes"),
    ("Encuestas de calidad de vida con su paciente en la hoja de pacientes", "calidadvida", "numero_doc", "pacientes"),
]
# (nombre, hoja de referencia, columna llave, hoja que debería tenerla): ¿cada paciente-ojo tiene registros en la otra hoja?
COBERTURA = [
    ("Paciente-ojo de línea base con al menos una aplicación", "lineabase", ID_OJO, "aplicaciones"),
    ("Paciente-ojo de línea base con al menos una consulta", "lineabase", ID_OJO, "consultas"),
    ("Paciente-ojo de línea base con al menos una ayuda diagnóstica (OCT)", "lineabase", ID_OJO, "ayudas"),
    ("Pacientes con al menos una encuesta de calidad de vida", "pacientes", "numero_doc", "calidadvida"),
]


def _llaves(df: pd.DataFrame, col: str) -> pd.Series:
    """Llave como texto comparable: un documento leído como 1 en una hoja y 1.0 en otra debe cruzar."""
    if col not in df:
        return pd.Series(dtype=str)
    s = df[col].dropna()
    num = pd.to_numeric(s, errors="coerce")
    if len(s) and num.notna().all():
        return num.map(lambda v: f"{v:.0f}" if float(v).is_integer() else str(v))
    return s.astype(str).str.strip()


def _pct(a: int, b: int) -> Optional[float]:
    return round(a / b * 100, 1) if b else None


def calcular(datos: Dict[str, pd.DataFrame]) -> Dict:
    hojas: List[Dict] = []
    for hoja, df in datos.items():
        obligatorias = set(config.COLUMNAS_REQUERIDAS.get(hoja, []))
        columnas = []
        for col in df.columns:
            serie = df[col]
            con_dato = serie.notna() & ~serie.astype(str).str.strip().isin(["", "nan", "NaT", "None"])
            columnas.append({"columna": str(col), "obligatoria": col in obligatorias, "con_dato": int(con_dato.sum()),
                             "pct": _pct(int(con_dato.sum()), len(df))})
        hojas.append({"hoja": hoja, "filas": int(len(df)), "columnas": columnas,
                      "faltan_obligatorias": sorted(obligatorias - set(map(str, df.columns)))})
    cruces = []
    for nombre, hoja, col, ref in CRUCES:
        if hoja not in datos or ref not in datos or col not in datos[hoja] or col not in datos[ref]:
            continue
        llaves, validas = _llaves(datos[hoja], col), set(_llaves(datos[ref], col))
        ok = int(llaves.isin(validas).sum())
        cruces.append({"tipo": "Registros que encuentran su llave", "cruce": nombre, "llave": col, "total": int(len(llaves)),
                       "cumplen": ok, "no_cumplen": int(len(llaves)) - ok, "pct": _pct(ok, len(llaves))})
    for nombre, ref, col, hoja in COBERTURA:
        if hoja not in datos or ref not in datos or col not in datos[hoja] or col not in datos[ref]:
            continue
        base, con = set(_llaves(datos[ref], col)), set(_llaves(datos[hoja], col))
        ok = len(base & con)
        cruces.append({"tipo": "Cobertura", "cruce": nombre, "llave": col, "total": len(base),
                       "cumplen": ok, "no_cumplen": len(base) - ok, "pct": _pct(ok, len(base))})
    return {"generado": datetime.now().isoformat(timespec="seconds"), "hojas": hojas, "cruces": cruces}


def guardar(directorio: Path, reporte: Dict) -> None:
    (Path(directorio) / ARCHIVO).write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")


def leer(directorio: Path) -> Optional[Dict]:
    ruta = Path(directorio) / ARCHIVO
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None
