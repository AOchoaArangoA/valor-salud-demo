"""Carga de un insumo nuevo: valida, guarda con la convención de data/raw, corre el pipeline y publica.

Flujo (lo usa la pantalla "Cargar insumo" del tablero, pero funciona sin Streamlit):
    1. valida el libro en una carpeta de paso (.staging): hojas, filas y columnas requeridas;
    2. lo guarda en  <DATA_ROOT>/raw/<prestador>/v<version>_<fecha>/  con su manifest.json;
    3. corre el pipeline y deja los resultados en  <DATA_ROOT>/processed/<prestador>/v<version>_<fecha>/ .
Si algo falla, no queda ninguna carpeta a medias y la versión anterior sigue intacta.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from . import config
from .extract import leer_hojas
from .main import ejecutar
from .utils import get_logger

log = get_logger(__name__)
LOCK_MAX_SEGUNDOS = 30 * 60   # un bloqueo más viejo se considera abandonado


class CargaError(Exception):
    """Error esperable (archivo inválido, bloqueo, datos incompletos): el mensaje se le muestra tal cual al usuario."""


def _slug(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.strip().lower()).strip("-")
    if not s:
        raise CargaError(f"'{texto}' no sirve como identificador: use letras o números.")
    return s


def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


class _Bloqueo:
    """Un solo proceso a la vez escribe en la carpeta de datos (si no, dos cargas simultáneas se pisarían)."""

    def __init__(self, raiz: Path):
        self.ruta = raiz / ".carga.lock"

    def __enter__(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        if self.ruta.exists() and time.time() - self.ruta.stat().st_mtime > LOCK_MAX_SEGUNDOS:
            self.ruta.unlink()
        try:
            fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise CargaError("Hay otra carga en proceso. Espere unos minutos y vuelva a intentar.")
        os.write(fd, f"{datetime.now().isoformat(timespec='seconds')}".encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        try:
            self.ruta.unlink()
        except OSError:
            pass


def validar_libro(ruta: Path) -> Dict[str, int]:
    """Lee el libro con las mismas reglas que el pipeline. Devuelve filas por hoja o lanza CargaError."""
    try:
        datos = leer_hojas(ruta)
    except FileNotFoundError as e:
        raise CargaError(str(e))
    except (KeyError, ValueError) as e:
        raise CargaError(str(e).strip("'\""))
    except Exception as e:  # archivo corrupto, no es un Excel, etc.
        raise CargaError(f"No se pudo leer el archivo como libro de Excel: {e}")
    return {h: int(len(df)) for h, df in datos.items()}


def listar_prestadores(raiz: Optional[Path] = None) -> list:
    raw = (raiz or config.DATA_ROOT) / "raw"
    return sorted(p.name for p in raw.iterdir() if p.is_dir() and not p.name.startswith(".")) if raw.is_dir() else []


def _carpeta_libre(base: Path, nombre: str) -> Path:
    destino, n = base / nombre, 2
    while destino.exists():
        destino = base / f"{nombre}_{n}"
        n += 1
    return destino


def registrar_entrega(*, prestador: str, version: str, usuario: str, libro: bytes, libro_nombre: str,
                      ecv: Optional[bytes] = None, ecv_nombre: str = "ecv.xlsx",
                      costos_modo: str = "libro", costos: Optional[bytes] = None, costos_nombre: str = "costos.xlsx",
                      raiz: Optional[Path] = None, progreso: Callable[[str], None] = lambda m: None,
                      meta_extra: Optional[Dict] = None) -> Dict[str, Path]:
    """Valida, guarda y procesa una entrega. Devuelve {'raw': ..., 'processed': ...}.
    `meta_extra`: campos adicionales que quedan en el manifest y en metadata.json (p. ej. {'es_demo': True})."""
    raiz = Path(raiz or config.DATA_ROOT)
    prestador, version, usuario = _slug(prestador), version.strip(), usuario.strip()
    if not usuario:
        raise CargaError("Indique su nombre: queda registrado en el manifest de la entrega.")
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", version):
        raise CargaError("La versión del formulario debe verse como 5.3.3 (letras, números, punto o guion).")
    if costos_modo == "archivo" and not costos:
        raise CargaError("Eligió subir la tabla de costos pero no adjuntó el archivo.")
    if costos_modo not in ("libro", "archivo", "dummy"):
        raise CargaError(f"Modo de costos desconocido: {costos_modo}")

    with _Bloqueo(raiz):
        paso = raiz / "raw" / ".staging" / uuid.uuid4().hex[:8]
        paso.mkdir(parents=True)
        final_raw: Optional[Path] = None
        try:
            progreso("Validando el libro…")
            if not libro[:2] == b"PK":   # un .xlsx/.xlsm es un zip
                raise CargaError("El archivo no es un libro de Excel válido (.xlsm o .xlsx).")
            ruta_paso = paso / "libro.xlsm"   # nombre corto: evita el límite de 260 caracteres de Windows
            ruta_paso.write_bytes(libro)
            filas = validar_libro(ruta_paso)

            nombre_ver = f"v{version}_{date.today():%Y-%m-%d}"
            final_raw = _carpeta_libre(raiz / "raw" / prestador, nombre_ver)
            final_proc = raiz / "processed" / prestador / final_raw.name
            progreso("Guardando el insumo…")
            final_raw.mkdir(parents=True)
            shutil.move(str(ruta_paso), final_raw / libro_nombre)
            archivos = {libro_nombre: {"sha256": _sha256(libro), "descripcion": "libro del formulario (insumo principal)"}}
            ruta_ecv = ruta_costos = None
            if ecv:
                ruta_ecv = final_raw / ecv_nombre
                ruta_ecv.write_bytes(ecv)
                archivos[ecv_nombre] = {"sha256": _sha256(ecv), "descripcion": "resultado de calidad de vida (ECV)"}
            if costos_modo == "archivo":
                ruta_costos = final_raw / costos_nombre
                ruta_costos.write_bytes(costos)
                archivos[costos_nombre] = {"sha256": _sha256(costos), "descripcion": "tabla de costos"}

            manifest = {
                "prestador": prestador, "version_formulario": version, "fecha_recepcion": f"{date.today():%Y-%m-%d}",
                "cargado_por": usuario, "cargado_en": datetime.now().isoformat(timespec="seconds"),
                "formato": "carga desde el tablero", "archivos": archivos, "filas_por_hoja": filas,
                "costos_modo": costos_modo, "ecv_incluida": bool(ecv),
                "notas": [] if ecv else ["Sin resultado de ECV: los indicadores de calidad de vida quedan vacíos."],
                **(meta_extra or {}),
            }
            (final_raw / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            progreso("Procesando (adherencia, agudeza visual, OCT, costos)… puede tardar un minuto")
            try:
                ejecutar(final_raw / libro_nombre, final_proc, costos_modo=costos_modo, costos_path=ruta_costos,
                         ecv_path=ruta_ecv, prestador=prestador,
                         extra_meta={"version": version, "cargado_por": usuario, "carpeta": final_raw.name, **(meta_extra or {})})
            except (FileNotFoundError, KeyError, ValueError) as e:
                raise CargaError(f"El archivo es legible pero el proceso no pudo calcularlo: {e}")
            progreso("Listo.")
            return {"raw": final_raw, "processed": final_proc}
        except BaseException:
            # Nada a medias: se retira lo que esta carga alcanzó a crear
            if final_raw is not None and final_raw.exists():
                shutil.rmtree(final_raw, ignore_errors=True)
            if final_raw is not None:
                shutil.rmtree(raiz / "processed" / prestador / final_raw.name, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(paso, ignore_errors=True)


def reprocesar(raw_dir: Path, *, costos_modo: str = "libro", costos: Optional[Path] = None,
               ecv: Optional[Path] = None, raiz: Optional[Path] = None) -> Path:
    """Vuelve a correr el pipeline sobre una entrega que ya está en data/raw (sin copiar nada).
    Los resultados quedan en <raiz>/processed/<prestador>/<carpeta> y reemplazan los de esa misma carpeta."""
    raiz = Path(raiz or config.DATA_ROOT)
    raw_dir = Path(raw_dir)
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    # el libro es el archivo que el manifest marca como insumo principal; si no, el único .xlsm
    marcados = [n for n, d in manifest.get("archivos", {}).items()
                if str(d.get("descripcion", d) if isinstance(d, dict) else d).lower().startswith(("insumo", "libro"))]
    libro = next((raw_dir / n for n in marcados if (raw_dir / n).is_file()),
                 next((p for p in sorted(raw_dir.glob("*.xlsm")) if not p.name.startswith("~$")), None))
    if libro is None:
        raise CargaError(f"No hay libro .xlsm/.xlsx en {raw_dir}")
    destino = raiz / "processed" / raw_dir.parent.name / raw_dir.name
    with _Bloqueo(raiz):
        return ejecutar(libro, destino, costos_modo=costos_modo, costos_path=costos, ecv_path=ecv, prestador=raw_dir.parent.name,
                        extra_meta={"version": manifest.get("version_formulario"), "cargado_por": manifest.get("cargado_por", "carga inicial"),
                                    "carpeta": raw_dir.name})
