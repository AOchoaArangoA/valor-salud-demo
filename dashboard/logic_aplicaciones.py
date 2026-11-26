"""Cálculos de la página «Seguimiento de aplicaciones», sin Streamlit.

Une dos fuentes que el equipo usaba por separado:
  * Power BI «reporte_aplicaciones_v4»: dosis aplicadas, dosis programadas y cumplimiento de la fecha programada en un
    período, más el visor de pacientes. Sus columnas calculadas (DAX) se replican aquí una por una.
  * Excel «tablero_alertas_aplicaciones»: con una fecha de corte, la última cita programada de cada paciente-ojo
    reingreso (POR) y si está en rango, retrasada o a futuro; el reporte por diagnóstico, medicamento, EAPB y médico;
    y la gestión de los incumplimientos (que en la app se registra en pipeline/gestion.py).

Reglas confirmadas con los datos del PBI (nov-2026): «Dosis aplicadas» filtra por fecha de aplicación; «Dosis
programadas» por fecha programada; «Cumplimiento» por fecha de aplicación, entre las aplicaciones que tienen la cita
de la dosis anterior. Las pruebas están en tests/test_aplicaciones.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pipeline import config, seguridad

EN_BLANCO = "(En blanco)"
COLS_PACIENTE = ["eapb", "sede", "sexo", "nombres", "apellidos", "egreso_fecha", "egreso_causa"]
# Estados de la alerta (hoja «agrupar_ultima_fecha» del Excel; el Excel llama «Se adelantó» a la cita futura)
EN_RANGO, RETRASO, FUTURA, SIN_FECHA = "En rango", "Retraso", "Cita futura", "Sin fecha programada"


def tolerancia() -> int:
    return int(config.TOLERANCIA_PROGRAMACION_DIAS)


def redondear(x: pd.Series) -> pd.Series:
    """ROUND(x, 0) de DAX: la mitad se aleja de cero (pandas redondea al par: 2,5 -> 2; DAX -> 3)."""
    return np.sign(x) * np.floor(np.abs(x) + 0.5)


def etiqueta_molecula(x) -> str:
    """Misma etiqueta anonimizada del Tablero: el código 1 se muestra como MED1."""
    if pd.isna(x):
        return EN_BLANCO
    try:
        return config.MEDICAMENTO_LABEL.format(codigo=int(float(x)))
    except (TypeError, ValueError):
        return str(x)


def clasificar(dias: pd.Series, tol: Optional[int] = None, grave: Optional[int] = None) -> pd.Series:
    """Columna calculada Clasificacion_Cumplimiento del PBI (6 clases + «Sin dato»)."""
    t = tolerancia() if tol is None else tol
    g = config.RETRASO_GRAVE_DIAS if grave is None else grave
    return pd.Series(np.select(
        [dias.isna(), dias < -t, dias < 0, dias == 0, dias <= t, dias <= g],
        ["Sin dato", f"1. Muy adelantado (>{t}d)", f"2. Adelantado (1-{t}d)", "3. Exacto", f"4. Retraso leve (1-{t}d)",
         f"5. Retraso moderado ({t + 1}-{g}d)"], default=f"6. Retraso grave (>{g}d)"), index=dias.index)


def columnas_pbi(apl: pd.DataFrame) -> pd.DataFrame:
    """Columnas calculadas de la tabla visaplicaciones del PBI, con su misma lógica:
    FecApl_Anterior  = fecha de aplicación de la dosis con_dosis − 1 del mismo POR (con fecha)
    FechaProg_Anterior = fecha programada en la dosis con_dosis − 1 del mismo POR
    Dias/Semanas_Entre_Dosis = aplicación − aplicación anterior (semanas = ROUND(días / 7))
    Dias/Semanas_Apl_a_Prog  = fecha programada − fecha de aplicación (de la misma fila)
    Dias_Cumplimiento = fecha de aplicación − fecha programada en la dosis anterior; Clasificacion_Cumplimiento."""
    d = apl.copy()
    ant = d[["pacienteojoreingreso", "con_dosis", "fecha_aplicacion", "fecha_programacion"]].copy()
    ant["con_dosis"] = ant["con_dosis"] + 1                     # la fila de la dosis n se cruza con la dosis n + 1
    prev = ant.groupby(["pacienteojoreingreso", "con_dosis"]).agg(FecApl_Anterior=("fecha_aplicacion", "max"),
                                                                  FechaProg_Anterior=("fecha_programacion", "max")).reset_index()
    d = d.drop(columns=[c for c in ("FecApl_Anterior", "FechaProg_Anterior") if c in d]).merge(prev, on=["pacienteojoreingreso", "con_dosis"], how="left")
    d["Dias_Entre_Dosis"] = (d["fecha_aplicacion"] - d["FecApl_Anterior"]).dt.days
    d["Semanas_Entre_Dosis"] = redondear(d["Dias_Entre_Dosis"] / 7)
    d["Dias_Apl_a_Prog"] = (d["fecha_programacion"] - d["fecha_aplicacion"]).dt.days
    d["Semanas_Apl_a_Prog"] = redondear(d["Dias_Apl_a_Prog"] / 7)
    d["Dias_Cumplimiento"] = (d["fecha_aplicacion"] - d["FechaProg_Anterior"]).dt.days
    d["Clasificacion_Cumplimiento"] = clasificar(d["Dias_Cumplimiento"])
    return d


def cargar(directorio: Path, llave: Optional[bytes] = None) -> Optional[pd.DataFrame]:
    """Una fila por aplicación (tabla oportunidad_apl del proceso) con los datos del paciente (EAPB, sede, nombre,
    egreso) y las columnas calculadas del PBI. None si la corrida no trae el detalle de aplicaciones."""
    try:
        apl = seguridad.leer_parquet(Path(directorio) / "oportunidad_apl.parquet", llave)
    except (OSError, ValueError):
        return None
    try:
        pac = seguridad.leer_parquet(Path(directorio) / "pacientes.parquet", llave)
        pac = pac.sort_values("fecha_registro", ascending=False).drop_duplicates("pacienteojoreingreso") if "fecha_registro" in pac else pac.drop_duplicates("pacienteojoreingreso")
        cols = [c for c in COLS_PACIENTE if c in pac.columns and c not in apl.columns]
        apl = apl.merge(pac[["pacienteojoreingreso"] + cols], on="pacienteojoreingreso", how="left")
    except (OSError, ValueError):
        pass
    for c in COLS_PACIENTE:
        if c not in apl:
            apl[c] = np.nan
    for c in ("fecha_aplicacion", "fecha_programacion", "egreso_fecha"):
        apl[c] = pd.to_datetime(apl[c], errors="coerce")
    apl["diagnostico_apl"] = apl["dx_ppal_desc"].astype(object).where(apl["dx_ppal_desc"].notna(), EN_BLANCO).astype(str)
    apl["molecula_label"] = apl["molecula"].map(etiqueta_molecula)
    apl["eapb_label"] = apl["eapb"].astype(object).where(apl["eapb"].notna(), EN_BLANCO).astype(str)
    return columnas_pbi(apl)


# =========================================================================== hojas del PBI
def en_periodo(apl: pd.DataFrame, campo: str, desde, hasta) -> pd.DataFrame:
    f = apl[campo]
    return apl[f.notna() & (f >= pd.Timestamp(desde)) & (f <= pd.Timestamp(hasta))]


def dosis_aplicadas(apl: pd.DataFrame, desde, hasta) -> pd.DataFrame:
    """Hoja 1: medida «Dosis Aplicadas» = filas con fecha de aplicación, en el período por fecha de aplicación."""
    return en_periodo(apl, "fecha_aplicacion", desde, hasta)


def dosis_programadas(apl: pd.DataFrame, desde, hasta) -> pd.DataFrame:
    """Hoja 2: medida «Dosis Programadas» = filas con fecha programada, en el período por fecha programada.
    Es también la hoja «Programación» del Excel (citas con fecha programada en el rango)."""
    return en_periodo(apl, "fecha_programacion", desde, hasta)


def cumplimiento(apl: pd.DataFrame, desde, hasta) -> pd.DataFrame:
    """Hoja 3: medida «Total Cumplimiento» = aplicaciones del período (por fecha de aplicación) con Dias_Cumplimiento."""
    x = dosis_aplicadas(apl, desde, hasta)
    return x[x["Dias_Cumplimiento"].notna()]


def pct_dentro_ventana(x: pd.DataFrame, tol: Optional[int] = None) -> float:
    """Medida «Pct Dentro Ventana»: Dias_Cumplimiento entre −10 y +10 días sobre «Total Cumplimiento»."""
    t = tolerancia() if tol is None else tol
    return float(100 * x["Dias_Cumplimiento"].between(-t, t).mean()) if len(x) else np.nan


def conteo(x: pd.DataFrame, col: str) -> pd.DataFrame:
    """Barras de distribución (diagnóstico, EAPB, medicamento): número de filas por categoría, de mayor a menor."""
    if x.empty:
        return pd.DataFrame(columns=[col, "n", "pct"])
    g = x[col].astype(str).value_counts().rename_axis(col).rename("n").reset_index()
    g["pct"] = 100 * g["n"] / g["n"].sum()
    return g


def matriz(x: pd.DataFrame, filas: str, columnas: str, orden_columnas: Optional[List] = None) -> pd.DataFrame:
    """Tabla dinámica del PBI (p. ej. consecutivo de dosis × semanas entre dosis) con fila y columna Total."""
    y = x.dropna(subset=[filas, columnas])
    if y.empty:
        return pd.DataFrame()
    t = pd.crosstab(y[filas], y[columnas])
    if orden_columnas is not None:
        t = t.reindex(columns=[c for c in orden_columnas if c in t.columns])
    t.index = [int(i) if float(i).is_integer() else i for i in t.index]
    t.columns = [int(c) if isinstance(c, (int, float, np.integer, np.floating)) and float(c).is_integer() else c for c in t.columns]
    t["Total"] = t.sum(axis=1)
    t.loc["Total"] = t.sum()
    return t.astype(int)


def orden_clasificacion() -> List[str]:
    return [c for c in clasificar(pd.Series([-99, -1, 0, 1, 20, 99], dtype=float)).tolist()]


# =========================================================================== Excel de alertas
def alertas(apl: pd.DataFrame, corte, ventana: Optional[int] = None, modo_excel: bool = False) -> pd.DataFrame:
    """Hoja «agrupar_ultima_fecha» del Excel: una fila por POR con su última fecha programada y los días a la fecha de
    corte (días = corte − última programada). Estado: En rango si |días| ≤ ventana; Retraso si días > ventana;
    Cita futura si días < −ventana; Sin fecha programada si nunca se le programó una cita.

    Diferencias con el Excel (modo_excel=False, el de la app):
      * solo cuenta lo aplicado hasta la fecha de corte, como dice la hoja Parámetros («última dosis por paciente-ojo
        hasta esta fecha»); el Excel tomaba la última programación de toda la base aunque fuera posterior al corte;
      * sin fecha programada queda como «Sin fecha programada»; el Excel la reemplazaba por 01/01/1950 y salía como
        retraso de décadas. Con modo_excel=True se reproduce el Excel tal cual (lo usan las pruebas)."""
    v = tolerancia() if ventana is None else int(ventana)
    corte = pd.Timestamp(corte)
    a = apl.copy()
    if modo_excel:
        a["fecha_programacion"] = a["fecha_programacion"].fillna(pd.Timestamp("1950-01-01"))
    else:
        a = a[a["fecha_aplicacion"].notna() & (a["fecha_aplicacion"] <= corte)]
    attrs = ("numero_doc", "nombres", "apellidos", "molecula_label", "medico", "dx_ppal", "diagnostico_apl", "eapb_label", "sede",
             "egreso_fecha", "egreso_causa")
    if a.empty:
        return pd.DataFrame(columns=["pacienteojoreingreso", "ultima_programada", "ultima_aplicacion", "con_dosis", *attrs, "dias", "estado"])
    if modo_excel:
        # Power Query: Table.Group por POR (las filas sin POR forman un grupo más) y List.Min de cada atributo
        a["pacienteojoreingreso"] = a["pacienteojoreingreso"].astype(object).where(a["pacienteojoreingreso"].notna(), "(sin POR)")
        g = a.groupby("pacienteojoreingreso")
        out = pd.DataFrame({"ultima_programada": g["fecha_programacion"].max(), "ultima_aplicacion": g["fecha_aplicacion"].max(),
                            "con_dosis": g["con_dosis"].max()})
        for c in attrs:
            out[c] = g[c].agg(lambda x: x.dropna().astype(str).min() if x.notna().any() else np.nan) if c in a else np.nan
    else:
        a = a.sort_values(["pacienteojoreingreso", "fecha_aplicacion", "con_dosis"])
        ultima = a.groupby("pacienteojoreingreso").tail(1).set_index("pacienteojoreingreso")   # atributos de la última aplicación
        out = pd.DataFrame({"ultima_programada": a.groupby("pacienteojoreingreso")["fecha_programacion"].max()})
        out["ultima_aplicacion"] = ultima["fecha_aplicacion"]
        out["con_dosis"] = ultima["con_dosis"]
        for c in attrs:
            out[c] = ultima[c] if c in ultima else np.nan
    out["dias"] = (corte - out["ultima_programada"]).dt.days
    out["estado"] = np.select([out["dias"].isna(), out["dias"].abs() <= v, out["dias"] > v],
                              [SIN_FECHA, EN_RANGO, RETRASO], default=FUTURA)
    return out.reset_index()


def etiqueta_estado(estado: str, ventana: Optional[int] = None) -> str:
    v = tolerancia() if ventana is None else ventana
    return {EN_RANGO: f"En rango (±{v} días)", RETRASO: f"Retraso > {v} días", FUTURA: f"Cita futura (> {v} días)",
            SIN_FECHA: SIN_FECHA}.get(estado, estado)


def reporte_por(al: pd.DataFrame, prog: pd.DataFrame, col_alerta: str, col_prog: str) -> pd.DataFrame:
    """Bloques de la hoja Reportes del Excel: por categoría, citas programadas en el rango (N y %), POR en rango
    (N y % de los en rango) y POR con retraso (N y % de los retrasados)."""
    p = prog[col_prog].astype(str).value_counts()
    c = al.loc[al["estado"] == EN_RANGO, col_alerta].astype(str).value_counts()
    r = al.loc[al["estado"] == RETRASO, col_alerta].astype(str).value_counts()
    t = pd.DataFrame({"prog_n": p, "cumplen_n": c, "retraso_n": r}).fillna(0).astype(int)
    for k in ("prog", "cumplen", "retraso"):
        tot = t[f"{k}_n"].sum()
        t[f"{k}_pct"] = 100 * t[f"{k}_n"] / tot if tot else 0.0
    t = t.sort_values(["prog_n", "retraso_n"], ascending=False)
    total = t.sum(numeric_only=True).to_frame("Total").T
    return pd.concat([t, total])


def reporte_dosis(prog: pd.DataFrame, max_dosis: int = 6) -> pd.DataFrame:
    """«Reporte 5 — Últimas dosis» del Excel: citas programadas en el rango por consecutivo de dosis (1 a 6). Se agrega
    «7 o más» para que el total cuadre siempre (en el Excel, las dosis 7+ no aparecían)."""
    n = prog["con_dosis"].dropna().astype(int)
    etiquetas = [f"Dosis {i}" for i in range(1, max_dosis + 1)] + [f"{max_dosis + 1} o más"]
    k = n.clip(upper=max_dosis + 1).map(lambda i: f"Dosis {i}" if i <= max_dosis else f"{max_dosis + 1} o más")
    t = k.value_counts().reindex(etiquetas, fill_value=0).rename("n").to_frame()
    t["pct"] = 100 * t["n"] / t["n"].sum() if t["n"].sum() else 0.0
    t.loc["Total"] = [t["n"].sum(), t["pct"].sum()]
    return t


def kpis_alertas(prog: pd.DataFrame, al: pd.DataFrame, gestionados: Optional[set] = None) -> Dict[str, float]:
    """KPIs generales de la hoja Reportes: programación (registros, pacientes-ojo únicos, sin fecha), cumplen
    (total y % sobre evaluados = en rango + retraso) y no cumplen (total, con y sin gestión registrada)."""
    en_rango = int((al["estado"] == EN_RANGO).sum())
    retraso = al[al["estado"] == RETRASO]
    con_g = int(retraso.apply(lambda r: (r["pacienteojoreingreso"], r["ultima_programada"]) in (gestionados or set()), axis=1).sum()) if len(retraso) else 0
    return {"prog_registros": len(prog), "prog_por": int(prog["pacienteojoreingreso"].nunique()),
            "sin_fecha": int((al["estado"] == SIN_FECHA).sum()), "en_rango": en_rango, "retraso": len(retraso),
            "pct_en_rango": 100 * en_rango / (en_rango + len(retraso)) if (en_rango + len(retraso)) else np.nan,
            "futura": int((al["estado"] == FUTURA).sum()), "con_gestion": con_g, "sin_gestion": len(retraso) - con_g}
