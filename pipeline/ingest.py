"""Carga de un insumo nuevo: valida, guarda con la convención de data/raw, corre el pipeline y publica.

Flujo (lo usa la página «Pipeline de datos» de la app, pero funciona sin Streamlit):
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
from typing import Callable, Dict, List, Optional

from . import config, registro
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
        if "Excel file format" in str(e) or "engine" in str(e):   # pandas no reconoce el archivo como Excel
            raise CargaError(f"No se pudo leer '{Path(ruta).name}' como libro de Excel: el archivo está dañado o no es un .xlsx/.xlsm.")
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


def _registrar_entrega(*, prestador: str, version: str, usuario: str, libro: bytes, libro_nombre: str,
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


def _resumen_resultado(rec: Dict, processed: Path) -> None:
    rec["prestador"], rec["carpeta"], rec["resultados"] = processed.parent.name, processed.name, str(processed)
    try:
        rec["filas_mart"] = json.loads((processed / "metadata.json").read_text(encoding="utf-8")).get("filas_mart")
    except (OSError, ValueError):
        pass


def _con_log(progreso: Optional[Callable[[str], None]]) -> Callable[[str], None]:
    """Los avisos de avance («Validando el libro…») también quedan en el log de la ejecución."""
    def avance(mensaje: str) -> None:
        log.info(mensaje)
        if progreso:
            progreso(mensaje)
    return avance


def registrar_entrega(*, en_vivo: Optional[Callable[[str], None]] = None, **kw) -> Dict[str, Path]:
    """Igual que _registrar_entrega, y además deja la ejecución (éxito o falla) en la bitácora (pipeline/registro.py).
    `en_vivo` recibe cada línea del log mientras el proceso corre."""
    kw["progreso"] = _con_log(kw.get("progreso"))
    with registro.ejecucion("Carga de un formulario nuevo", raiz=kw.get("raiz"), en_vivo=en_vivo, prestador=kw.get("prestador"),
                            version=kw.get("version"), usuario=kw.get("usuario"), archivo=kw.get("libro_nombre")) as rec:
        res = _registrar_entrega(**kw)
        _resumen_resultado(rec, res["processed"])
        return res


def _archivo_marcado(raw_dir: Path, manifest: Dict, prefijos: tuple) -> Optional[Path]:
    """El archivo de la entrega cuya descripción en el manifest empieza por alguno de los prefijos (p. ej. 'tabla de costos')."""
    for nombre, d in manifest.get("archivos", {}).items():
        desc = str(d.get("descripcion", "") if isinstance(d, dict) else d).lower()
        if desc.startswith(prefijos) and (raw_dir / nombre).is_file():
            return raw_dir / nombre
    return None


def listar_entregas(raiz: Optional[Path] = None) -> List[Dict]:
    """Entregas guardadas en <raiz>/raw/<prestador>/<versión>/ (las que tienen manifest), la más reciente primero."""
    raw = Path(raiz or config.DATA_ROOT) / "raw"
    out = []
    for m in raw.glob("*/*/manifest.json") if raw.is_dir() else []:
        if m.parent.parent.name.startswith("."):
            continue
        try:
            man = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"ruta": m.parent, "prestador": m.parent.parent.name, "carpeta": m.parent.name, "manifest": man})
    return sorted(out, key=lambda e: str(e["manifest"].get("cargado_en") or e["manifest"].get("fecha_recepcion") or ""), reverse=True)


def reprocesar(raw_dir: Path, *, costos_modo: Optional[str] = None, costos: Optional[Path] = None, ecv: Optional[Path] = None,
               raiz: Optional[Path] = None, usuario: Optional[str] = None, en_vivo: Optional[Callable[[str], None]] = None) -> Path:
    """Vuelve a correr el pipeline sobre una entrega que ya está en data/raw (sin copiar nada).
    Si no se indican, la tabla de costos y el resultado de calidad de vida se toman de la propia entrega (según su manifest).
    Cada ejecución es una corrida NUEVA: la primera queda en <raiz>/processed/<prestador>/<entrega> y las siguientes en
    <entrega>__e<id de la ejecución>, así se conservan todas las versiones que se van ejecutando. Se calcula en una
    carpeta temporal y solo aparece en el tablero si el proceso termina bien."""
    raiz = Path(raiz or config.DATA_ROOT)
    raw_dir = Path(raw_dir)
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    libro = _archivo_marcado(raw_dir, manifest, ("insumo", "libro")) or next(
        (p for p in sorted(raw_dir.glob("*.xls[xm]")) if not p.name.startswith("~$") and p.name != (ecv.name if ecv else "")), None)
    if libro is None:
        raise CargaError(f"No hay libro .xlsm/.xlsx en {raw_dir}")
    ecv = ecv or _archivo_marcado(raw_dir, manifest, ("resultado de calidad de vida", "ecv"))
    costos = costos or _archivo_marcado(raw_dir, manifest, ("tabla de costos",))
    costos_modo = costos_modo or ("archivo" if costos else manifest.get("costos_modo", "libro"))
    with registro.ejecucion("Ejecución sobre una entrega guardada", raiz=raiz, en_vivo=en_vivo, prestador=raw_dir.parent.name,
                            version=manifest.get("version_formulario"), usuario=usuario or manifest.get("cargado_por"),
                            archivo=libro.name, entrega=raw_dir.name) as rec, _Bloqueo(raiz):
        base = raiz / "processed" / raw_dir.parent.name
        destino = base / raw_dir.name if not (base / raw_dir.name).exists() else base / f"{raw_dir.name}__e{rec['id']}"
        rec["destino"] = str(destino)
        log.info("Entrega: %s/%s · libro: %s · costos: %s · calidad de vida: %s", raw_dir.parent.name, raw_dir.name, libro.name,
                 costos.name if costos else costos_modo, ecv.name if ecv else "sin archivo")
        log.info("Resultados de esta ejecución: %s", destino.name)
        log.info("Validando el libro…")
        validar_libro(libro)   # un libro dañado o incompleto se informa con un mensaje claro, igual que en una carga nueva
        temporal = base / f".{destino.name}.nuevo"
        try:
            try:
                ejecutar(libro, temporal, costos_modo=costos_modo, costos_path=costos, ecv_path=ecv, prestador=raw_dir.parent.name,
                         extra_meta={"version": manifest.get("version_formulario"), "cargado_por": usuario or manifest.get("cargado_por", "carga inicial"),
                                     "carpeta": raw_dir.name, "entrega": raw_dir.name, "ejecucion": rec["id"],
                                     **{k: manifest[k] for k in ("es_demo", "sintetico", "semilla", "descripcion") if k in manifest}})
            except (FileNotFoundError, KeyError, ValueError) as e:
                raise CargaError(f"El archivo es legible pero el proceso no pudo calcularlo: {e}")
            temporal.rename(destino)
        finally:
            shutil.rmtree(temporal, ignore_errors=True)
        _resumen_resultado(rec, destino)
        return destino
