"""Lógica del dashboard sin dependencias de Streamlit: carga, filtros, KPIs y formato."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pipeline import config, seguridad  # noqa: E402  (carpeta de datos, desde VLM_DATA_ROOT / .env)

OUTPUT_DIR = config.OUTPUT_DIR
SEMANAS = [0, 12, 16, 20, 52, 104]
# Semáforo de cumplimiento (% ): verde >= 85, ámbar >= 70, rojo < 70
UMBRAL_VERDE, UMBRAL_AMBAR = 85, 70
# Glosario: cada concepto se llama igual en todo el tablero.
N_SECA = "Anatomía sin líquido en OCT"
N_ADH = "Adherencia a dosis de carga"
N_CUMPL = "Cumplimiento de aplicaciones"
N_EXT = "Extensión última dosis"
N_ANAT = "Anatomía sin líquido en OCT"
N_ECV1 = "Encuesta de calidad de vida 1"
N_ECV2 = "Encuesta de calidad de vida 2"
N_PAC = "Pacientes con maculopatía"
N_PO = "Paciente-ojo"
N_POR = "Paciente-ojo reingreso"


def _leer_meta(carpeta: Path) -> Optional[Dict]:
    f = carpeta / "metadata.json"
    if not f.is_file() or not ((carpeta / "tablero_pteojo.parquet").is_file() or (carpeta / "tablero_pteojo.parquet.enc").is_file()):
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def listar_corridas(directorio: Optional[Path] = None) -> List[Dict]:
    """Corridas disponibles: <processed>/<prestador>/<version>/ (más la carpeta plana de versiones anteriores),
    la más reciente primero."""
    directorio = Path(directorio or OUTPUT_DIR)
    out = []
    candidatas = list(directorio.glob("*/*/")) + [directorio]
    for c in candidatas:
        if any(parte.startswith(".") for parte in c.relative_to(directorio).parts):   # carpetas temporales de un proceso en curso
            continue
        meta = _leer_meta(c)
        if meta is None:
            continue
        prestador, version = meta.get("prestador", "sin_definir"), meta.get("version")
        entrega = meta.get("entrega") or meta.get("carpeta") or (f"v{version}" if version else meta.get("insumo", "corrida anterior"))
        etiqueta = f"{str(prestador).upper()} · {entrega}"
        out.append({"ruta": c, "etiqueta": f"{etiqueta} · {str(meta.get('generado', ''))[:16].replace('T', ' ')}",
                    "generado": meta.get("generado", ""), "meta": meta})
    out.sort(key=lambda x: x["generado"], reverse=True)          # dentro de cada prestador, la carga más reciente primero
    orden = getattr(config, "PRESTADORES_ORDEN", ["p1", "p2"])
    pos = lambda c: orden.index(str(c["meta"].get("prestador", "")).lower()) if str(c["meta"].get("prestador", "")).lower() in orden else len(orden)  # noqa: E731
    return sorted(out, key=pos)                                    # orden estable: P1 (base), luego P2, luego el resto


def cargar(directorio: Path, llave: Optional[bytes] = None) -> Tuple[pd.DataFrame, Dict]:
    directorio = Path(directorio)
    return seguridad.leer_parquet(directorio / "tablero_pteojo.parquet", llave), json.loads((directorio / "metadata.json").read_text(encoding="utf-8"))


COLS_APL = ["pacienteojoreingreso", "con_dosis", "Oportunidad_aplicacion_dias", "Clasificacion_cumplimiento",
            "Semanas_Apl_a_Prog", "Semanas_Entre_Dosis"]
COLS_APL_ANIO = ["dias_desde_primera", "Oportunidad_aplicacion_cat"]   # opcionales: cumplimiento por año de tratamiento


def cargar_aplicaciones(directorio: Path, llave: Optional[bytes] = None) -> Optional[pd.DataFrame]:
    """Detalle por aplicación (cumplimiento y extensión). None si la corrida es anterior a este detalle."""
    f = Path(directorio) / "oportunidad_apl.parquet"
    try:
        d = seguridad.leer_parquet(f, llave)
    except (OSError, ValueError):
        return None
    return d[COLS_APL + [c for c in COLS_APL_ANIO if c in d.columns]] if all(c in d.columns for c in COLS_APL) else None


def cumplimiento_anios(apl: Optional[pd.DataFrame], ids) -> Dict[int, Tuple[float, int]]:
    """% de aplicaciones 'Cumple' (dentro de la ventana de la fecha programada) por AÑO DE TRATAMIENTO: año 1 = días 0-364
    desde la 1ª inyección, año 2 = días 365-728 (la misma definición de inyecciones y costos). Se cuenta por aplicación
    (no es un promedio de promedios por paciente). Devuelve {1: (%, n aplicaciones), 2: (%, n aplicaciones)}."""
    vacio = {1: (np.nan, 0), 2: (np.nan, 0)}
    if apl is None or not all(c in apl.columns for c in COLS_APL_ANIO):
        return vacio
    a = apl[apl["pacienteojoreingreso"].isin(set(ids)) & apl["Oportunidad_aplicacion_cat"].notna()]
    out = {}
    for anio, (lo, hi) in {1: (0, 364), 2: (365, 728)}.items():
        x = a[a["dias_desde_primera"].between(lo, hi)]
        out[anio] = (float((x["Oportunidad_aplicacion_cat"] == "Cumple").mean() * 100) if len(x) else np.nan, int(len(x)))
    return out


COLS_ANUALES = ["apl_anio1", "apl_anio2", "cumplimiento_anio1", "cumplimiento_anio2", "n_moleculas_anio1", "n_moleculas_anio2",
                "costofin_anio1", "costofin_anio2", "med_N_anio1", "med_N_anio2", "Cons_Retina_NAnio1", "Cons_Retina_NAnio2",
                "Cons_Oftalmo_NAnio1", "Cons_Oftalmo_NAnio2", "TipoAyuda_OCT_NAnio1", "TipoAyuda_OCT_NAnio2",
                "TipoTto_InyIV_NAnio1", "TipoTto_InyIV_NAnio2"]


def enmascarar_anios(df: pd.DataFrame) -> pd.DataFrame:
    """Utilización y costos de año 1/2 solo para pacientes-ojo con 2 años de seguimiento posible
    (evita que quien aún no cumple el año 2 se promedie como '0 inyecciones')."""
    d = df.copy()
    cols = [c for c in COLS_ANUALES if c in d]
    d.loc[~d["anio2_completo"], cols] = np.nan
    return d


# ------------------------------------------------------------------ estadísticos con n
def media(df: pd.DataFrame, col: str) -> Tuple[float, int]:
    s = df[col].dropna() if col in df else pd.Series(dtype=float)
    return (float(s.mean()) if len(s) else np.nan), int(len(s))


def porcentaje(df: pd.DataFrame, col: str) -> Tuple[float, int]:
    m, n = media(df, col)
    return m * 100, n


def suma_columnas(df: pd.DataFrame, cols: list) -> pd.Series:
    return df[cols].sum(axis=1, min_count=1)


def kpis(df: pd.DataFrame) -> Dict[str, Tuple[float, int]]:
    """Todos los indicadores de la propuesta -> (valor, n con dato)."""
    d = df.copy()
    d["cons_ret1"], d["cons_ret2"] = d["Cons_Retina_NAnio1"], d["Cons_Retina_NAnio2"]
    out = {"pteojo": (float(len(d)), len(d))}
    for s in (16, 52, 104):
        out[f"dav{s}"] = media(d, f"dif_lts_sem{s}")
        out[f"seca{s}"] = porcentaje(d, f"RetinaSeca_sem{s}")
    out["respondedor"] = porcentaje(d, "respondedor")
    out["oct0"] = media(d, "OCT_inicial")
    out["av0"] = media(d, "AV_letras_inicial")
    out["av0_med"] = (float(d["AV_letras_inicial"].median()) if d["AV_letras_inicial"].notna().any() else np.nan, int(d["AV_letras_inicial"].notna().sum()))
    out["oct0_med"] = (float(d["OCT_inicial"].median()) if d["OCT_inicial"].notna().any() else np.nan, int(d["OCT_inicial"].notna().sum()))
    for s_ in (16, 52, 104):
        out[f"oct{s_}_um"] = media(d, f"OCT_sem{s_}")
        out[f"dmic{s_}"] = media(d, f"dif_micras_sem{s_}")
    for a in (1, 2):
        out[f"iny{a}"] = media(d, f"apl_anio{a}")
        out[f"cumpl{a}"] = porcentaje(d, f"cumplimiento_anio{a}")
        out[f"mol{a}"] = media(d, f"n_moleculas_anio{a}")
        out[f"consret{a}"] = media(d, f"Cons_Retina_NAnio{a}")
        out[f"consoft{a}"] = media(d, f"Cons_Oftalmo_NAnio{a}")
        out[f"oct{a}"] = media(d, f"TipoAyuda_OCT_NAnio{a}")
        out[f"costo{a}"] = media(d, f"costofin_anio{a}")
    # ECV es por paciente: se promedia por paciente para no pesar doble a quien tiene dos ojos
    # y solo con quienes respondieron AMBAS encuestas: así ECV1, ECV2 y Δ describen al mismo grupo
    pac = d.drop_duplicates("numero_doc")
    pac = pac[pac["ecv1"].notna() & pac["ecv2"].notna()]
    for c in ("ecv1", "ecv2", "delta_ecv"):
        out[c] = media(pac, c)
    if config.RESPONDEDOR_PRUEBA is not None:
        out["respondedor"] = (float(config.RESPONDEDOR_PRUEBA), out["respondedor"][1] or len(d))
    # Se recalcula con el umbral vigente (config) y no con la marca guardada en la corrida, que pudo usar otro umbral
    dias = d["Oportunidad_inicio_tto"]
    d["oportunidad_ok"] = np.where(dias.isna(), np.nan, (dias <= config.OPORTUNIDAD_INICIO_MAX_DIAS).astype(float))
    out["oportuno"] = porcentaje(d, "oportunidad_ok")
    out["carga"] = porcentaje(d, "adherencia_carga")
    out["adh16"] = porcentaje(d, "Adherencia_final_16")
    out["ext52"] = media(d, "extension_sem52")
    out["ext104"] = media(d, "extension_sem104")
    out["dias_inicio"] = media(d, "Oportunidad_inicio_tto")
    out["ext_ult"] = media(d, "extension_ultima_dosis")
    return out


def ecv_perfil(df: pd.DataFrame) -> pd.DataFrame:
    """Perfil de calidad de vida por dimensión (y total): una fila por dimensión.

    Promedio de la encuesta 1 y de la encuesta 2 con todos los que la respondieron (n1, n2) y,
    aparte, la comparación 2 vs 1 SOLO con pacientes que tienen ambas encuestas (n_par, p1, p2, delta).
    Es por paciente (no por ojo): se deduplica por numero_doc.
    """
    pac = df.drop_duplicates("numero_doc")
    filas = [("Total", "Total", "Total", "ecv1", "ecv2")] + [
        (k, et, g, f"ecvd_{k}_1", f"ecvd_{k}_2") for k, et, g in config.ECV_DIMENSIONES]
    out = []
    for k, et, g, c1, c2 in filas:
        if c1 not in pac.columns:
            continue
        par = pac[pac[c1].notna() & pac[c2].notna()]
        dif = par[c2] - par[c1]
        sem = ((par["fecha_ecv2"] - par["fecha_ecv1"]).dt.days / 7) if "fecha_ecv1" in par else pd.Series(dtype=float)
        out.append(dict(clave=k, dimension=et, grupo=g, n1=int(pac[c1].notna().sum()), media1=pac[c1].mean(),
                        n2=int(pac[c2].notna().sum()), media2=pac[c2].mean(), n_par=len(par),
                        par1=par[c1].mean(), par2=par[c2].mean(), delta=dif.mean(),
                        med1=par[c1].median(), med2=par[c2].median(),
                        n_mejora5=int((dif > 5).sum()), pct_mejora5=float((dif > 5).mean() * 100) if len(par) else np.nan,
                        n_ecv2_70=int((par[c2] > 70).sum()), pct_ecv2_70=float((par[c2] > 70).mean() * 100) if len(par) else np.nan,
                        sem_entre=float(sem.mean()) if len(sem.dropna()) else np.nan))
    return pd.DataFrame(out)


def semaforo(pct: float) -> str:
    if pd.isna(pct):
        return "⚪"
    return "🟢" if pct >= UMBRAL_VERDE else ("🟡" if pct >= UMBRAL_AMBAR else "🔴")


# ------------------------------------------------------------------ cohortes
def con_cohorte(df: pd.DataFrame, por: str) -> pd.DataFrame:
    d = df.copy()
    if por == "Diagnóstico":
        d["cohorte"] = d["diagnostico"]
    elif por == "Medicamento":
        d["cohorte"] = d["medicamento_label"]
    elif por == "Diagnóstico × medicamento":
        d["cohorte"] = d["diagnostico"] + " · " + d["medicamento_label"]
    else:
        d["cohorte"] = d["anio_inicio"].astype("Int64").astype(str)
    return d


def resumen_cohortes(df: pd.DataFrame, por: str, n_min: int) -> pd.DataFrame:
    d = con_cohorte(df, por)
    d["costo_total"] = suma_columnas(d, ["costofin_anio1", "costofin_anio2"]).where(d[["costofin_anio1", "costofin_anio2"]].notna().all(axis=1))
    g = d.groupby("cohorte")
    r = pd.DataFrame({
        "n": g.size(),
        "dav16": g["dif_lts_sem16"].mean(), "dav52": g["dif_lts_sem52"].mean(), "dav104": g["dif_lts_sem104"].mean(),
        "respondedor": g["respondedor"].mean() * 100,
        "seca52": g["RetinaSeca_sem52"].mean() * 100, "seca104": g["RetinaSeca_sem104"].mean() * 100,
        "iny1": g["apl_anio1"].mean(), "iny2": g["apl_anio2"].mean(),
        "costo1": g["costofin_anio1"].mean(), "costo2": g["costofin_anio2"].mean(), "costo_total": g["costo_total"].mean(),
        "n_costo_total": g["costo_total"].count(),
    }).reset_index()
    return r[r["n"] >= n_min].sort_values("n", ascending=False)


# ------------------------------------------------------------------ trayectorias
def trayectoria_larga(df: pd.DataFrame, prefijo: str = "dif_lts", base0: bool = True) -> pd.DataFrame:
    """Formato largo (id, semana, valor). Con base0 agrega S0=0 (Δ letras)."""
    filas = []
    cols = {s: f"{prefijo}_sem{s}" for s in SEMANAS if s and f"{prefijo}_sem{s}" in df}
    if base0:
        filas.append(pd.DataFrame({"id": df["pacienteojoreingreso"], "semana": 0, "valor": 0.0}))
    for s, c in cols.items():
        filas.append(pd.DataFrame({"id": df["pacienteojoreingreso"], "semana": s, "valor": df[c]}))
    largo = pd.concat(filas, ignore_index=True).dropna(subset=["valor"])
    n_puntos = largo.groupby("id")["semana"].transform("count")
    return largo[n_puntos >= 2].sort_values(["id", "semana"])


# Espagueti de la propuesta del equipo: eje LB / S16 / S52 / S104 (equidistante), umbral de +5 letras
PUNTOS_ESPAGUETI = [("LB", None), ("S16", 16), ("S52", 52), ("S104", 104)]
UMBRAL_MEJORA_LETRAS = 5
# Ejemplo ilustrativo para la pestaña de metodología: tres ojos INVENTADOS (no son pacientes) con la AV en letras ETDRS en LB / S16 / S52 / S104.
EJEMPLO_AV = [("Ojo A", [45, 55, 60, 62]), ("Ojo B", [55, 57, 53, 56]), ("Ojo C", [60, 52, 48, 45])]
# Equivalencia de agudeza visual de 20/10 a 20/4000, tal como la entregó el equipo experto (revisión del 31-oct-2026):
# (Snellen decimal, letras ETDRS, Snellen en pies, Snellen en metros, logMAR). CD = cuenta dedos, MM = movimiento de manos.
# 20/2000 (cuenta dedos) = 2 letras y 20/4000 (movimiento de manos) = 0 letras (revisión del equipo experto, nov-2026).
EQUIV_SNELLEN = [
    ("2.00", 100, "20/10", "6/3", -0.3), ("1.60", 95, "20/12.5", "6/4", -0.2), ("1.25", 90, "20/16", "6/5", -0.1),
    ("1.00", 85, "20/20", "6/6", 0.0), ("0.80", 80, "20/25", "6/7.5", 0.1), ("0.63", 75, "20/32", "6/9", 0.2),
    ("0.50", 70, "20/40", "6/12", 0.3), ("0.40", 65, "20/50", "6/15", 0.4), ("0.32", 60, "20/63", "6/19", 0.5),
    ("0.25", 55, "20/80", "6/24", 0.6), ("0.20", 50, "20/100", "6/30", 0.7), ("0.16", 45, "20/125", "6/38", 0.8),
    ("0.125", 40, "20/160", "6/48", 0.9), ("0.10", 35, "20/200", "6/60", 1.0), ("0.08", 30, "20/250", "6/75", 1.1),
    ("0.06", 25, "20/320", "6/96", 1.2), ("0.05", 20, "20/400", "6/120", 1.3), ("0.04", 15, "20/500", "6/150", 1.4),
    ("0.03", 10, "20/630", "6/190", 1.5), ("0.025", 5, "20/800", "6/240", 1.6), ("0.01 (CD)", 2, "20/2000", "6/600", 1.9),
    ("MM", 0, "20/4000", "6/1200", 2.3),
]
COLUMNAS_SNELLEN = ["Snellen decimal", "Letras ETDRS", "Snellen (pies)", "Snellen (metros)", "logMAR"]

# Datos de MUESTRA para la guía «Gráficos utilizados en el análisis exploratorio» (metodología): valores fijos e inventados,
# no salen de ninguna corrida ni de ningún paciente. Espaguetis: AV en letras en línea base, 6 y 12 meses.
EJEMPLO_TRAYECTORIAS = [(64, 75, 76), (56, 70, 71), (50, 63, 72), (43, 64, 68), (40, 44, 67), (36, 49, 55), (43, 47, 37),
                        (36, 40, 42), (29, 40, 26), (24, 32, 24), (20, 23, 20), (14, 16, 22), (16, 54, 54)]


def ejemplo_distribuciones() -> Dict[str, np.ndarray]:
    """AV en letras de dos grupos de MUESTRA (semilla fija: siempre los mismos valores) para cajas y bigotes y violín."""
    rng = np.random.default_rng(31)
    dmre = np.clip(rng.normal(49, 11, 80), 16, 76)
    emd = np.concatenate([np.clip(rng.normal(43, 11, 70), 16, 70), [8, 5]])   # dos valores extremos bajos
    return {"DMRE (neovascular)": dmre.round(), "EMD (diabético)": emd.round()}
CRITERIOS_ESPAGUETI = ["Aleatoria (reproducible)", "Mayor mejora (Δ AV final)", "Mayor caída (Δ AV final)",
                       "Más seguimiento (con S104)"]


def trayectorias_av(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por (paciente-ojo, punto) con Δ letras vs. LB. LB = 0. Solo pacientes-ojo con >= 1 medición
    posterior a LB. Incluye `ultimo` (Δ del último punto disponible) y `n_pts` para ordenar/filtrar."""
    base = df[["pacienteojoreingreso", "diagnostico", "medicamento_label"]].rename(columns={"pacienteojoreingreso": "id"})
    partes = []
    for i, (etq, sem) in enumerate(PUNTOS_ESPAGUETI):
        v = 0.0 if sem is None else df[f"dif_lts_sem{sem}"]
        partes.append(base.assign(x=i, etiqueta=etq, valor=v))
    largo = pd.concat(partes, ignore_index=True).dropna(subset=["valor"])
    n = largo.groupby("id")["x"].transform("count")
    largo = largo[n >= 2].sort_values(["id", "x"])
    ult = largo.groupby("id")["valor"].last().rename("ultimo")
    largo = largo.join(ult, on="id")
    largo["n_pts"] = largo.groupby("id")["x"].transform("count")
    return largo


def elegir_pacientes(tray: pd.DataFrame, n: int, criterio: str, semilla: int = 7) -> list:
    """Los `n` pacientes-ojo que se dibujan según el criterio (todos si n >= total)."""
    por_id = tray.drop_duplicates("id").set_index("id")
    ids = por_id.index.tolist()
    if n >= len(ids):
        return ids
    if criterio.startswith("Mayor mejora"):
        orden = por_id["ultimo"].sort_values(ascending=False).index
    elif criterio.startswith("Mayor caída"):
        orden = por_id["ultimo"].sort_values(ascending=True).index
    elif criterio.startswith("Más seguimiento"):
        orden = por_id.sort_values(["n_pts", "ultimo"], ascending=[False, False]).index
    else:
        orden = pd.Index(np.random.default_rng(semilla).permutation(ids))
    return list(orden[:n])


def clase_cambio(ultimo: float) -> str:
    if ultimo > UMBRAL_MEJORA_LETRAS:
        return "Mejora (> +5)"
    if ultimo < -UMBRAL_MEJORA_LETRAS:
        return "Empeora (< −5)"
    return "Se mantiene (±5)"


def dispersion_valor(df: pd.DataFrame, semana: int = 104, costo: str = "total") -> pd.DataFrame:
    """Por paciente-ojo: Δ AV en la semana y costo ('anio1', 'anio2' o 'total' = año 1 + año 2)."""
    d = df[["pacienteojoreingreso", "diagnostico", "medicamento_label", f"dif_lts_sem{semana}",
            "costofin_anio1", "costofin_anio2"]].copy()
    if costo == "total":
        d["costo_total"] = d[["costofin_anio1", "costofin_anio2"]].sum(axis=1, min_count=2)
    else:
        d["costo_total"] = d[f"costofin_{costo}"]
    return d.dropna(subset=[f"dif_lts_sem{semana}", "costo_total"])


# ------------------------------------------------------------------ caja y bigotes (regla de Tukey, 1,5 × RIQ)
GRUPOS_CUANTIL = ["Atípico inferior", "Bigote abajo", "Caja", "Bigote arriba", "Atípico superior"]


def tukey(serie: pd.Series) -> dict:
    """Cuartiles, límites (fences) y extremos de los bigotes de una variable."""
    s_ = pd.to_numeric(serie, errors="coerce").dropna()
    if s_.empty:
        return {}
    q1, med, q3 = s_.quantile([.25, .5, .75])
    riq = q3 - q1
    lo_f, hi_f = q1 - 1.5 * riq, q3 + 1.5 * riq
    dentro = s_[(s_ >= lo_f) & (s_ <= hi_f)]
    return dict(n=int(len(s_)), media=float(s_.mean()), sd=float(s_.std()) if len(s_) > 1 else np.nan, min=float(s_.min()), q1=float(q1),
                mediana=float(med), q3=float(q3), max=float(s_.max()), riq=float(riq), lim_inf=float(dentro.min()),
                lim_sup=float(dentro.max()), atip_inf=int((s_ < lo_f).sum()), atip_sup=int((s_ > hi_f).sum()))


def grupo_cuantil(serie: pd.Series) -> pd.Series:
    """Etiqueta cada valor: Atípico inferior | Bigote abajo (límite inferior..Q1) | Caja (Q1..Q3) |
    Bigote arriba (Q3..límite superior) | Atípico superior. Sin dato -> NaN."""
    t = tukey(serie)
    v = pd.to_numeric(serie, errors="coerce")
    if not t:
        return pd.Series(np.nan, index=serie.index, dtype=object)
    lo_f, hi_f = t["q1"] - 1.5 * t["riq"], t["q3"] + 1.5 * t["riq"]
    g = np.select([v < lo_f, v < t["q1"], v <= t["q3"], v <= hi_f, v > hi_f], GRUPOS_CUANTIL, default="")
    return pd.Series(np.where(v.isna(), None, g), index=serie.index, dtype=object)


def tabla_variacion(df: pd.DataFrame, columnas: dict, decimales: int = 1) -> pd.DataFrame:
    """Una fila por variable: n, media, mediana, Q1, Q3, límites de bigote, mínimo, máximo y atípicos."""
    filas = []
    for col, nombre in columnas.items():
        if col not in df:
            continue
        t = tukey(df[col])
        if not t:
            continue
        filas.append({"Variable": nombre, "n": t["n"], "Media": t["media"], "Mediana": t["mediana"], "Q1": t["q1"], "Q3": t["q3"],
                      "Bigote inf.": t["lim_inf"], "Bigote sup.": t["lim_sup"], "Mín.": t["min"], "Máx.": t["max"],
                      "Atípicos": t["atip_inf"] + t["atip_sup"]})
    return pd.DataFrame(filas)


# ------------------------------------------------------------------ formato (es-CO)
def f_num(v: Optional[float], dec: int = 1, signo: bool = False) -> str:
    if v is None or pd.isna(v):
        return "—"
    s = f"{v:+,.{dec}f}" if signo else f"{v:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def f_pct(v: Optional[float]) -> str:
    return "—" if v is None or pd.isna(v) else f_num(v, 1) + " %"


def f_money(v: Optional[float]) -> str:
    return "—" if v is None or pd.isna(v) else "$ " + f_num(v, 0)


def f_millones(v: Optional[float]) -> str:
    """$ 5,9 M para tarjetas estrechas; el valor exacto va en la ayuda."""
    return "—" if v is None or pd.isna(v) else "$ " + f_num(v / 1e6, 1) + " M"


# ------------------------------------------------------------------ rangos de AV inicial (cuartiles del prestador)
BANDAS_AV = ["AV baja", "AV media", "AV alta"]


def cortes_av(mart: pd.DataFrame) -> Tuple[float, float]:
    """Q1 y Q3 de la AV inicial de TODA la corrida (es decir, del prestador), no del filtro actual: así los rangos no cambian al filtrar."""
    v = pd.to_numeric(mart["AV_letras_inicial"], errors="coerce").dropna()
    return (float(v.quantile(.25)), float(v.quantile(.75))) if len(v) else (np.nan, np.nan)


def texto_bandas_av(q1: float, q3: float) -> str:
    return f"AV baja: ≤ Q1 ({q1:g} letras) · AV media: entre Q1 y Q3 · AV alta: ≥ Q3 ({q3:g} letras)"


def banda_av(serie: pd.Series, q1: float, q3: float) -> pd.Series:
    """AV baja: ≤ Q1 · AV media: entre Q1 y Q3 · AV alta: ≥ Q3 (los atípicos quedan en baja o alta). Sin dato -> NaN."""
    v = pd.to_numeric(serie, errors="coerce")
    g = np.select([v <= q1, v >= q3], BANDAS_AV[::2], default=BANDAS_AV[1])
    return pd.Series(np.where(v.isna(), None, g), index=serie.index, dtype=object)


def resumen_bandas_av(df: pd.DataFrame, q1: float, q3: float) -> pd.DataFrame:
    """Por rango de AV inicial: valor general (media) frente a la mediana y el cambio respecto al valor base."""
    d = df.assign(banda=banda_av(df["AV_letras_inicial"], q1, q3))
    filas = []
    for nombre, g in [(b, d[d["banda"] == b]) for b in BANDAS_AV] + [("General", d[d["banda"].notna()])]:
        if g.empty:
            continue
        fila = {"Rango de AV inicial": nombre, "n": int(len(g)), "AV inicial (media)": g["AV_letras_inicial"].mean(),
                "AV inicial (mediana)": g["AV_letras_inicial"].median()}
        for sem in (52, 104):
            c = g[f"dif_lts_sem{sem}"].dropna()
            fila[f"Δ AV S{sem} (media)"] = c.mean() if len(c) else np.nan
            fila[f"Δ AV S{sem} (mediana)"] = c.median() if len(c) else np.nan
            fila[f"n S{sem}"] = int(len(c))
        filas.append(fila)
    return pd.DataFrame(filas)


# ------------------------------------------------------------------ completitud de los resultados del proceso
# (grupo, columna del mart, nombre, universo): el universo es la columna que dice quién YA podía tener el dato
# (p. ej. S104 solo para quien lleva 2 años); None = todos los paciente-ojo reingreso.
COMPLETITUD_RESULTADOS = [
    ("Identificación y filtros", "diagnostico", "Diagnóstico", None),
    ("Identificación y filtros", "medicamento_label", "Medicamento", None),
    ("Identificación y filtros", "sede", "Sede", None),
    ("Identificación y filtros", "eapb", "EAPB", None),
    ("Identificación y filtros", "sexo", "Sexo", None),
    ("Identificación y filtros", "edad", "Edad", None),
    ("Agudeza visual", "AV_letras_inicial", "AV inicial", None),
    ("Agudeza visual", "AV_letras_sem16", "AV S16", None),
    ("Agudeza visual", "AV_letras_sem52", "AV S52", "anio1_completo"),
    ("Agudeza visual", "AV_letras_sem104", "AV S104", "anio2_completo"),
    ("OCT", "OCT_inicial", "OCT inicial", None),
    ("OCT", "OCT_sem16", "OCT S16", None),
    ("OCT", "OCT_sem52", "OCT S52", "anio1_completo"),
    ("OCT", "OCT_sem104", "OCT S104", "anio2_completo"),
    ("OCT", "RetinaSeca_sem52", "Anatomía sin líquido S52", "anio1_completo"),
    ("OCT", "RetinaSeca_sem104", "Anatomía sin líquido S104", "anio2_completo"),
    ("Proceso de atención", "Oportunidad_inicio_tto", "Oportunidad de inicio (días)", None),
    ("Proceso de atención", "Adherencia_final_12", "Adherencia a dosis de carga", None),
    ("Proceso de atención", "extension_ultima_dosis", "Extensión última dosis", None),
    ("Proceso de atención", "cumplimiento_anio1", "Cumplimiento año 1", "anio1_completo"),
    ("Proceso de atención", "cumplimiento_anio2", "Cumplimiento año 2", "anio2_completo"),
    ("Utilización y costos", "apl_anio1", "Inyecciones año 1", "anio1_completo"),
    ("Utilización y costos", "apl_anio2", "Inyecciones año 2", "anio2_completo"),
    ("Utilización y costos", "costofin_anio1", "Costo año 1", "anio1_completo"),
    ("Utilización y costos", "costofin_anio2", "Costo año 2", "anio2_completo"),
    ("Calidad de vida", "ecv1", "Encuesta de calidad de vida 1 (total)", None),
    ("Calidad de vida", "ecv2", "Encuesta de calidad de vida 2 (total)", None),
]


def con_dato(serie: pd.Series) -> pd.Series:
    """True donde hay dato (un texto vacío cuenta como faltante)."""
    return serie.notna() & ~serie.astype(str).str.strip().isin(["", "nan", "NaT", "None"])


def completitud_resultados(mart: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for grupo, col, nombre, universo in COMPLETITUD_RESULTADOS:
        if col not in mart:
            filas.append({"Grupo": grupo, "Variable": nombre, "Con dato": 0, "% del total": 0.0, "Podían tenerlo": np.nan,
                          "% de quienes podían tenerlo": np.nan, "Nota": "La corrida no trae esta variable"})
            continue
        ok = con_dato(mart[col])
        base = mart[universo].fillna(False).astype(bool) if universo and universo in mart else pd.Series(True, index=mart.index)
        filas.append({"Grupo": grupo, "Variable": nombre, "Con dato": int(ok.sum()), "% del total": ok.mean() * 100 if len(ok) else np.nan,
                      "Podían tenerlo": int(base.sum()), "% de quienes podían tenerlo": ok[base].mean() * 100 if base.any() else np.nan,
                      "Nota": "" if not universo else ("Solo con 1 año de seguimiento posible" if universo == "anio1_completo"
                                                      else "Solo con 2 años de seguimiento posible")})
    return pd.DataFrame(filas)
