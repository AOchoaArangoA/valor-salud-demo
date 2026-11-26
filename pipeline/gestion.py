"""Registro de la gestión de los incumplimientos (reemplaza la hoja «TablaGestion» del Excel de alertas).

Cada gestión queda ligada a una cita concreta: paciente-ojo reingreso (POR) + fecha programada que no se cumplió. Así,
cuando el paciente vuelve y se le programa una cita nueva, la alerta nueva aparece sin gestión y la anterior queda en
el historial. (El Excel la ligaba solo al POR y además sin el dígito de reingreso, por eso no la encontraba.)

Reglas:
  * nunca se borra ni se sobrescribe: una corrección es un registro nuevo; para cada cita vale el más reciente;
  * cada registro guarda quién lo hizo y cuándo;
  * se guarda en <carpeta de datos>/gestion/<prestador>/gestion.csv, aparte de los formularios: una carga nueva del
    formulario no la toca. Si la instalación usa cifrado (pipeline/seguridad.py), el archivo se guarda cifrado;
  * dos personas pueden registrar a la vez: la escritura se hace con un candado de archivo.
"""
from __future__ import annotations

import io
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from . import config, seguridad

COLUMNAS = ["id", "registrado_en", "pacienteojoreingreso", "fecha_programada", "causa", "observacion", "gestionado_por"]
# Catálogo de la hoja «Causas» del Excel (las subcategorías de «Decisión del paciente» van con su principal).
CAUSAS: List[str] = [
    "Decisión médica",
    "Decisión del paciente · No quiere continuar",
    "Decisión del paciente · No tiene acompañante",
    "Decisión del paciente · Gastos de bolsillo",
    "Decisión del paciente · Otra",
    "Fallecimiento",
    "Novedades de afiliación",
    "Cambio de IPS",
    "Terapia Exit",
    "Seis meses última inyección",
    "Pendiente programación",
    "Otra",
]


def principal(causa: str) -> str:
    """«Decisión del paciente · Gastos de bolsillo» -> «Decisión del paciente» (para el reporte por causa)."""
    return str(causa).split(" · ")[0]


def ruta(prestador: str, raiz: Optional[Path] = None) -> Path:
    base = Path(raiz) if raiz else config.DATA_ROOT
    return base / "gestion" / str(prestador or "sin_definir").lower() / "gestion.csv"


@contextmanager
def _candado(archivo: Path):
    archivo.parent.mkdir(parents=True, exist_ok=True)
    lock = archivo.with_suffix(".lock")
    with open(lock, "w") as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:   # Windows: sin fcntl; un solo usuario a la vez en una instalación local
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_UN)
            except ImportError:
                pass


def _llave(raiz: Optional[Path]) -> Optional[bytes]:
    return seguridad.llave_de_entorno(raiz) if seguridad.hay_cifrado(raiz) else None


def leer(prestador: str, raiz: Optional[Path] = None, llave: Optional[bytes] = None) -> pd.DataFrame:
    """Todos los registros (historial completo), del más antiguo al más reciente."""
    f = ruta(prestador, raiz)
    enc = Path(str(f) + seguridad.SUFIJO)
    try:
        if enc.is_file():
            k = llave or _llave(raiz)
            if k is None:
                return pd.DataFrame(columns=COLUMNAS)
            df = pd.read_csv(io.BytesIO(seguridad.descifrar_bytes(enc, k)), dtype=str)
        elif f.is_file():
            df = pd.read_csv(f, dtype=str)
        else:
            return pd.DataFrame(columns=COLUMNAS)
    except (OSError, ValueError):
        return pd.DataFrame(columns=COLUMNAS)
    for c in COLUMNAS:
        if c not in df:
            df[c] = None
    df["fecha_programada"] = pd.to_datetime(df["fecha_programada"], errors="coerce")
    return df[COLUMNAS].sort_values("registrado_en").reset_index(drop=True)


def vigentes(df: pd.DataFrame) -> pd.DataFrame:
    """La gestión más reciente de cada cita (POR + fecha programada)."""
    if df.empty:
        return df
    return df.sort_values("registrado_en").groupby(["pacienteojoreingreso", "fecha_programada"], dropna=False).tail(1).reset_index(drop=True)


def registrar(prestador: str, pacienteojoreingreso: str, fecha_programada, causa: str, observacion: str, gestionado_por: str,
              raiz: Optional[Path] = None, llave: Optional[bytes] = None) -> Dict[str, str]:
    """Agrega un registro y devuelve lo guardado. Exige causa del catálogo y el nombre de quien registra."""
    if causa not in CAUSAS:
        raise ValueError(f"Causa fuera del catálogo: {causa}")
    if not str(gestionado_por or "").strip():
        raise ValueError("Falta el nombre de quien registra la gestión.")
    if not str(pacienteojoreingreso or "").strip():
        raise ValueError("Falta el paciente-ojo reingreso.")
    fp = pd.Timestamp(fecha_programada) if pd.notna(fecha_programada) else None
    fila = {"id": uuid.uuid4().hex[:12], "registrado_en": datetime.now().isoformat(timespec="seconds"),
            "pacienteojoreingreso": str(pacienteojoreingreso), "fecha_programada": fp.date().isoformat() if fp is not None else "",
            "causa": causa, "observacion": str(observacion or "").strip(), "gestionado_por": str(gestionado_por).strip()}
    f = ruta(prestador, raiz)
    with _candado(f):
        actual = leer(prestador, raiz, llave)
        actual["fecha_programada"] = pd.to_datetime(actual["fecha_programada"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        nuevo = pd.concat([actual, pd.DataFrame([fila])], ignore_index=True)[COLUMNAS]
        k = llave or _llave(raiz)
        if seguridad.hay_cifrado(raiz) and k is None:
            raise ValueError("Los datos de esta instalación están cifrados: abra la corrida con la clave antes de registrar la gestión.")
        tmp = f.with_suffix(".tmp")
        nuevo.to_csv(tmp, index=False)
        if k is not None:
            enc = seguridad.cifrar_archivo(tmp, k)
            tmp.unlink()                                      # el texto en claro no se queda en el disco
            os.replace(enc, Path(str(f) + seguridad.SUFIJO))
            if f.exists():
                f.unlink()
        else:
            os.replace(tmp, f)
    return fila
