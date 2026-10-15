"""Cifrado en reposo de los datos sensibles (insumos y resultados de prestadores reales).

Cómo funciona, en simple:
  - La clave NO se guarda en ningún archivo. Se escribe al cifrar y al abrir el tablero.
  - De la clave se deriva (scrypt, lento a propósito) una llave de cifrado; la sal vive en <data>/cifrado.json.
  - Cada archivo cifrado queda como <nombre>.enc (Fernet: AES + autenticación). metadata.json y manifest.json
    se dejan en claro (no traen datos de pacientes) para poder listar las corridas.
  - El tablero descifra en memoria; el archivo en claro no se vuelve a escribir en disco.
"""
from __future__ import annotations

import base64
import io
import json
import os
import secrets
from pathlib import Path
from typing import Optional

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import config

ARCHIVO_CONFIG = "cifrado.json"
SUFIJO = ".enc"
_TEXTO_VERIFICACION = b"valor-en-salud"


class ClaveRequerida(Exception):
    """El archivo está cifrado y no hay llave cargada."""


def _derivar(clave: str, sal: bytes) -> bytes:
    kdf = Scrypt(salt=sal, length=32, n=2 ** 15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(clave.encode("utf-8")))


def _ruta_config(raiz: Optional[Path] = None) -> Path:
    return Path(raiz or config.DATA_ROOT) / ARCHIVO_CONFIG


def hay_cifrado(raiz: Optional[Path] = None) -> bool:
    return _ruta_config(raiz).is_file()


def crear_llave(clave: str, raiz: Optional[Path] = None) -> bytes:
    """Primera vez: crea la sal y el testigo de verificación. Si ya existe, valida la clave (o falla)."""
    ruta = _ruta_config(raiz)
    if ruta.is_file():
        llave = llave_desde_clave(clave, raiz)
        if llave is None:
            raise ValueError("La clave no coincide con la que se usó al cifrar los datos.")
        return llave
    sal = secrets.token_bytes(16)
    llave = _derivar(clave, sal)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"sal": base64.b64encode(sal).decode(), "verificacion": Fernet(llave).encrypt(_TEXTO_VERIFICACION).decode(),
                                "kdf": "scrypt n=32768 r=8 p=1", "cifrado": "Fernet (AES-128-CBC + HMAC-SHA256)"}, indent=2), encoding="utf-8")
    return llave


def llave_desde_clave(clave: str, raiz: Optional[Path] = None) -> Optional[bytes]:
    """Llave derivada si la clave es correcta; None si no."""
    ruta = _ruta_config(raiz)
    if not ruta.is_file() or not clave:
        return None
    cfg = json.loads(ruta.read_text(encoding="utf-8"))
    llave = _derivar(clave, base64.b64decode(cfg["sal"]))
    try:
        return llave if Fernet(llave).decrypt(cfg["verificacion"].encode()) == _TEXTO_VERIFICACION else None
    except InvalidToken:
        return None


def llave_de_entorno(raiz: Optional[Path] = None) -> Optional[bytes]:
    """Para arranque sin teclado (servicio): VLM_CLAVE. Guardar la clave en el mismo equipo reduce la protección; úselo solo si es necesario."""
    return llave_desde_clave(os.getenv("VLM_CLAVE", ""), raiz)


def cifrar_archivo(ruta: Path, llave: bytes) -> Path:
    destino = Path(str(ruta) + SUFIJO)
    destino.write_bytes(Fernet(llave).encrypt(Path(ruta).read_bytes()))
    return destino


def descifrar_bytes(ruta_enc: Path, llave: bytes) -> bytes:
    try:
        return Fernet(llave).decrypt(Path(ruta_enc).read_bytes())
    except InvalidToken as e:
        raise ValueError(f"No se pudo descifrar {Path(ruta_enc).name}: clave incorrecta o archivo dañado.") from e


def carpeta_cifrada(directorio: Path) -> bool:
    """True si la carpeta tiene datos cifrados y no tiene el parquet principal en claro."""
    d = Path(directorio)
    return (d / f"tablero_pteojo.parquet{SUFIJO}").is_file() and not (d / "tablero_pteojo.parquet").is_file()


def leer_parquet(ruta: Path, llave: Optional[bytes] = None) -> pd.DataFrame:
    """Lee el parquet en claro o, si solo existe la versión .enc, la descifra en memoria."""
    ruta = Path(ruta)
    if ruta.is_file():
        return pd.read_parquet(ruta)
    enc = Path(str(ruta) + SUFIJO)
    if not enc.is_file():
        raise FileNotFoundError(ruta)
    if llave is None:
        raise ClaveRequerida(ruta.name)
    return pd.read_parquet(io.BytesIO(descifrar_bytes(enc, llave)))
