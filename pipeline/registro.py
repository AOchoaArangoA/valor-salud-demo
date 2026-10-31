"""Bitácora de ejecuciones del pipeline (la página «Historial de ejecuciones» la lee).

Cada ejecución, termine bien o mal, deja:
  - una línea JSON en  <DATA_ROOT>/logs/ejecuciones.jsonl  (quién, cuándo, cuánto tardó, resultado, error);
  - el detalle de los mensajes del proceso en  <DATA_ROOT>/logs/<id>.log .
No guarda datos de pacientes: solo conteos, nombres de archivo y los mensajes que ya escribe el pipeline.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from . import config

ARCHIVO = "ejecuciones.jsonl"


def carpeta_logs(raiz: Optional[Path] = None) -> Path:
    return Path(raiz or config.DATA_ROOT) / "logs"


class _Captura(logging.Handler):
    """Copia a una lista los mensajes de los loggers del pipeline mientras dura la ejecución."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lineas: List[str] = []
        self.avisos = 0
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self.avisos += 1
        self.lineas.append(self.format(record))


@contextmanager
def ejecucion(origen: str, raiz: Optional[Path] = None, **campos) -> Iterator[Dict]:
    """Registra una ejecución. Quien la usa puede completar el dict (p. ej. 'resultados', 'filas_mart').
    Si ocurre un error se registra como «falla» con su mensaje y el error se vuelve a lanzar."""
    rec: Dict = {"id": f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}", "origen": origen,
                 "inicio": datetime.now().isoformat(timespec="seconds"), **campos}
    captura = _Captura()
    raiz_log = logging.getLogger("pipeline")
    nivel_previo = raiz_log.level
    raiz_log.addHandler(captura)
    if raiz_log.getEffectiveLevel() > logging.INFO:
        raiz_log.setLevel(logging.INFO)
    t0 = time.time()
    try:
        yield rec
        rec["estado"] = "éxito"
    except BaseException as e:
        rec["estado"] = "falla"
        rec["mensaje"] = str(e).strip() or type(e).__name__
        captura.lineas.append(f"{datetime.now():%H:%M:%S} | ERROR   | {type(e).__name__}: {rec['mensaje']}")
        raise
    finally:
        raiz_log.removeHandler(captura)
        raiz_log.setLevel(nivel_previo)
        rec["fin"] = datetime.now().isoformat(timespec="seconds")
        rec["duracion_s"] = round(time.time() - t0, 1)
        rec["avisos"] = captura.avisos
        _guardar(rec, captura.lineas, raiz)


def _guardar(rec: Dict, lineas: List[str], raiz: Optional[Path]) -> None:
    """Escribir la bitácora nunca debe tumbar una carga: si la carpeta no se puede escribir, se omite."""
    try:
        d = carpeta_logs(raiz)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{rec['id']}.log").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        with open(d / ARCHIVO, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: (str(v) if isinstance(v, Path) else v) for k, v in rec.items()}, ensure_ascii=False) + "\n")
    except OSError as e:
        logging.getLogger("pipeline.registro").warning("No se pudo escribir la bitácora de ejecuciones: %s", e)


def leer(raiz: Optional[Path] = None) -> List[Dict]:
    """Ejecuciones registradas, la más reciente primero. Una línea dañada se ignora."""
    ruta = carpeta_logs(raiz) / ARCHIVO
    if not ruta.is_file():
        return []
    out = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda r: r.get("inicio", ""), reverse=True)


def detalle(id_: str, raiz: Optional[Path] = None) -> Optional[str]:
    ruta = carpeta_logs(raiz) / f"{Path(id_).name}.log"
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else None
