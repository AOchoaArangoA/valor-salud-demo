"""Cálculos de la página «Análisis de adherencia» (migración del Power BI 01-reporte-adherencia_v4), sin Streamlit.

Cada función recibe la tabla por paciente-ojo reingreso (POR) que arma `cargar` y devuelve un DataFrame listo para
graficar. Las reglas son las del PBI, con las correcciones acordadas en el plan:
  * un registro por POR y conteos de POR distintos (no de filas);
  * «Sin evaluar» cuando falta la clase de AV, de OCT, la retina seca o el respondedor;
  * histogramas con intervalos iguales en todas las semanas y centrados en 0 (el PBI usaba 10/13/25 letras según la
    semana y su intervalo «0» iba de 0 a +10, así que «sin cambio» no quedaba en el centro).
Las pruebas que comparan estas funciones con las medidas DAX están en tests/test_adherencia.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pipeline import completitud, seguridad

SEMANAS_RESULTADO = [16, 52, 104]          # selector de semana de la página
SEMANAS_ADHERENCIA = [12, 16, 20]          # la adherencia a la carga se mide a estas semanas
SIN_EVALUAR = "Sin evaluar"
ORDEN_EDAD = ["< 50", "50-59", "60-69", "70-79", "80-89", ">= 90"]
CLASES_AV = {"mejora": "Mejora", "mantiene": "Se mantiene", "empeora": "Empeora"}
ORDEN_AV = ["Mejora", "Se mantiene", "Empeora", SIN_EVALUAR]
ORDEN_OCT = ["Entra al rango normal", "Se mantiene ≤ 300", "Se mantiene > 300", "Sale del rango normal", SIN_EVALUAR]
ORDEN_RESP = ["Respondedor", "Respondedor parcial", "No respondedor", SIN_EVALUAR]
ANTECEDENTES = {"ant_diabetes": "Diabetes", "ant_hta": "HTA", "ant_dislipidemia": "Dislipidemia", "ant_insulina": "Insulina"}
TRATAMIENTOS_PREVIOS = {"afli": "Aflibercept", "rani": "Ranibizumab", "beva": "Bevacizumab", "brolu": "Brolucizumab",
                        "fari": "Faricimab", "dexa": "Dexametasona"}
COLS_EVOL = [f"clase_{v}_sem{s}" for v in ("AV", "OCT") for s in SEMANAS_RESULTADO]
COLS_ADH = [f"apl_acum_sem{s}" for s in (16, 20)]
COLS_PAC = (["estatus_fumar", "actividad_fisica"] + list(ANTECEDENTES)
            + [f"tp_{m}" for m in TRATAMIENTOS_PREVIOS])


# =========================================================================== carga
def cargar(directorio: Path, mart: pd.DataFrame, llave: Optional[bytes] = None) -> pd.DataFrame:
    """La tabla del tablero (`mart`, un registro por POR) más lo que el PBI de adherencia usa y el tablero no trae:
    las clases de AV y OCT (evolucion), las dosis acumuladas (adherencia) y hábitos, antecedentes y tratamiento previo
    (pacientes). Las columnas que una corrida no tenga quedan vacías: la página muestra «sin datos» en vez de fallar."""
    d = mart.copy()
    for archivo, cols in (("evolucion", COLS_EVOL), ("adherencia", COLS_ADH), ("pacientes", COLS_PAC)):
        try:
            extra = seguridad.leer_parquet(Path(directorio) / f"{archivo}.parquet", llave)
        except (OSError, ValueError):
            extra = pd.DataFrame(columns=["pacienteojoreingreso"])
        if archivo == "evolucion":   # universo de las clases de AV/OCT, retina seca, respondedor y cruces (fact_EvolAV del PBI)
            d["tiene_evolucion"] = d["pacienteojoreingreso"].isin(set(extra.get("pacienteojoreingreso", [])))
        presentes = [c for c in cols if c in extra.columns and c not in d.columns]
        if presentes:
            extra = extra.drop_duplicates("pacienteojoreingreso")[["pacienteojoreingreso"] + presentes]
            d = d.merge(extra, on="pacienteojoreingreso", how="left")
        for c in cols:
            if c not in d.columns:
                d[c] = np.nan
    return d


def conteos_formulario(directorio: Path) -> Optional[Dict[str, int]]:
    """Filas que llegaron en el formulario (antes de limpiar): pacientes y registros de línea de base."""
    rep = completitud.leer(Path(directorio))
    if not rep:
        return None
    filas = {h["hoja"]: h["filas"] for h in rep.get("hojas", [])}
    return {"pacientes": filas.get("pacientes"), "lineabase": filas.get("lineabase")}


# =========================================================================== utilidades
def conteos(df: pd.DataFrame) -> Dict[str, int]:
    """# Pacientes únicos, # PO y # POR (medidas DAX DISTINCTCOUNT sobre dim_Paciente)."""
    return {"pacientes": int(df["numero_doc"].nunique()), "po": int(df["pacienteojo"].nunique()),
            "por": int(df["pacienteojoreingreso"].nunique())}


def con_sin_evaluar(serie: pd.Series, mapa: Optional[Dict] = None) -> pd.Series:
    s = serie.map(mapa) if mapa else serie
    return s.astype(object).where(s.notna(), SIN_EVALUAR)


def reparto(df: pd.DataFrame, fila: str, col: pd.Series, orden: List[str]) -> pd.DataFrame:
    """Conteo de POR por (fila, categoría) con su % dentro de la fila. Largo: fila, categoria, n, pct, total."""
    t = pd.DataFrame({"fila": df[fila].values, "categoria": col.values, "id": df["pacienteojoreingreso"].values})
    g = t.groupby(["fila", "categoria"])["id"].nunique().rename("n").reset_index()
    g["total"] = g.groupby("fila")["n"].transform("sum")
    g["pct"] = 100 * g["n"] / g["total"]
    g["categoria"] = pd.Categorical(g["categoria"], [c for c in orden if c in set(g["categoria"])] +
                                    sorted(set(g["categoria"]) - set(orden)))
    return g.sort_values(["fila", "categoria"]).reset_index(drop=True)


def orden_dx(df: pd.DataFrame) -> List[str]:
    """Diagnósticos de mayor a menor número de POR (mismo orden en todos los gráficos)."""
    if "pacienteojoreingreso" in df:
        return df.groupby("diagnostico")["pacienteojoreingreso"].nunique().sort_values(ascending=False).index.tolist()
    return df["diagnostico"].value_counts().index.tolist()


def intervalos(serie: pd.Series, ancho: float) -> pd.DataFrame:
    """Histograma con intervalos del mismo ancho y simétricos alrededor de 0: el intervalo centrado en c va de
    c − ancho/2 a c + ancho/2 (incluye el borde inferior). Devuelve centro, n y %."""
    v = pd.to_numeric(serie, errors="coerce").dropna()
    if v.empty:
        return pd.DataFrame(columns=["centro", "n", "pct"])
    centro = np.floor((v + ancho / 2) / ancho) * ancho
    g = centro.value_counts().sort_index().rename_axis("centro").rename("n").reset_index()
    g["pct"] = 100 * g["n"] / g["n"].sum()
    return g


def resumen_numerico(df: pd.DataFrame, col: str, por: str = "diagnostico") -> pd.DataFrame:
    """n, promedio y mediana por grupo y en total (las tablas de extensión, inyecciones y oportunidad del PBI)."""
    v = df[[por, col]].assign(**{col: pd.to_numeric(df[col], errors="coerce")}).dropna(subset=[col])
    g = v.groupby(por)[col].agg(n="count", promedio="mean", mediana="median").reset_index()
    g = g.set_index(por).reindex([d for d in orden_dx(df) if d in set(g[por])]).reset_index()
    total = pd.DataFrame({por: ["Total"], "n": [len(v)], "promedio": [v[col].mean()], "mediana": [v[col].median()]})
    return pd.concat([g, total], ignore_index=True)


# =========================================================================== 1 · Población
def por_dx_sexo(df: pd.DataFrame) -> pd.DataFrame:
    return reparto(df, "diagnostico", df["sexo"].fillna("Sin dato"), ["Femenino", "Masculino", "Sin dato"])


def piramide(df: pd.DataFrame) -> pd.DataFrame:
    """POR por grupo de edad y sexo (grupos del proceso automático, que ya clasifica bien 80-89)."""
    g = df.groupby(["Grupo_edad", "sexo"])["pacienteojoreingreso"].nunique().rename("n").reset_index()
    g["Grupo_edad"] = pd.Categorical(g["Grupo_edad"], [e for e in ORDEN_EDAD if e in set(g["Grupo_edad"])])
    return g.sort_values("Grupo_edad").reset_index(drop=True)


def habitos(df: pd.DataFrame) -> pd.DataFrame:
    """Tabaquismo y actividad física, % de POR por sexo. Largo: habito, categoria, sexo, n, pct."""
    orden = ["Nunca he fumado", "Exfumador", "Fumador actual", "Sí", "No", "Sin dato"]
    act = df["actividad_fisica"].map({1: "Sí", 0: "No", "1": "Sí", "0": "No", "Si": "Sí", "Sí": "Sí", "No": "No"})
    partes = []
    for nombre, serie in (("Tabaquismo", df["estatus_fumar"]), ("Actividad física", act)):
        t = reparto(df.assign(_sexo=df["sexo"].fillna("Sin dato")), "_sexo", serie.fillna("Sin dato"), orden)
        partes.append(t.rename(columns={"fila": "sexo"}).assign(habito=nombre, categoria=lambda x: x["categoria"].astype(str)))
    out = pd.concat(partes, ignore_index=True)
    out["categoria"] = pd.Categorical(out["categoria"], [c for c in orden if c in set(out["categoria"])] + sorted(set(out["categoria"]) - set(orden)))
    return out


def combinaciones_antecedentes(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """Para el UpSet: (combinaciones exactas con su n de POR, de mayor a menor; total de POR por antecedente)."""
    m = df[list(ANTECEDENTES)].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int).eq(1)
    m.columns = list(ANTECEDENTES.values())
    totales = m.sum().sort_values(ascending=False)
    clave = m.apply(lambda r: tuple(c for c in totales.index if r[c]), axis=1)
    combos = clave.value_counts().rename_axis("combinacion").rename("n").reset_index()
    combos["pct"] = 100 * combos["n"] / len(df) if len(df) else 0.0
    return combos, totales


# Venn de 4 conjuntos: 4 elipses (con círculos no se forman las 15 zonas). Centro x, centro y, ancho, alto, ángulo (grados),
# en un lienzo de 0 a 1. Cada zona lleva su etiqueta en un punto que está dentro de ella (lo verifica tests/test_adherencia.py
# con dentro_de_elipse).
VENN_ELIPSES = [(0.350, 0.400, 0.72, 0.45, 140), (0.450, 0.500, 0.72, 0.45, 140), (0.544, 0.500, 0.72, 0.45, 40), (0.644, 0.400, 0.72, 0.45, 40)]
VENN_ZONAS = {"1000": (0.14, 0.42), "0100": (0.32, 0.72), "0010": (0.68, 0.72), "0001": (0.85, 0.42), "1100": (0.23, 0.59),
              "1010": (0.29, 0.30), "1001": (0.50, 0.17), "0110": (0.50, 0.66), "0101": (0.71, 0.30), "0011": (0.77, 0.59),
              "1110": (0.35, 0.50), "1101": (0.61, 0.24), "1011": (0.39, 0.24), "0111": (0.65, 0.50), "1111": (0.50, 0.38)}


def dentro_de_elipse(x: float, y: float, elipse) -> bool:
    cx, cy, w, h, ang = elipse
    t = np.radians(ang)
    dx, dy = x - cx, y - cy
    u, v = dx * np.cos(t) + dy * np.sin(t), -dx * np.sin(t) + dy * np.cos(t)
    return (u / (w / 2)) ** 2 + (v / (h / 2)) ** 2 <= 1


def venn_antecedentes(df: pd.DataFrame) -> Tuple[Dict[str, int], Dict[str, int], int]:
    """Para el diagrama de Venn (hoja 2b del PBI): POR en cada una de las 15 zonas, con clave de 4 dígitos en el orden
    fijo de ANTECEDENTES (Diabetes, HTA, Dislipidemia, Insulina): "1010" = diabetes y dislipidemia, sin HTA ni insulina.
    Devuelve (zonas, total por antecedente, POR sin ninguno de los cuatro)."""
    m = df[list(ANTECEDENTES)].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int).eq(1)
    clave = m.astype(int).astype(str).agg("".join, axis=1)
    cuenta = clave.value_counts()
    zonas = {f"{i:04b}": int(cuenta.get(f"{i:04b}", 0)) for i in range(1, 16)}
    totales = {nombre: int(m[col].sum()) for col, nombre in ANTECEDENTES.items()}
    return zonas, totales, int(cuenta.get("0000", 0))


def medicamento_por_dx(df: pd.DataFrame) -> pd.DataFrame:
    return reparto(df, "diagnostico", df["medicamento_label"].astype(str), sorted(df["medicamento_label"].astype(str).unique()))


def tratamiento_previo(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(POR con cada tratamiento previo por diagnóstico; % de POR con algún tratamiento previo por diagnóstico).
    Igual que fact_TratamientoPrevio del PBI: una fila por POR y medicamento con tp_<med> = 1."""
    cols = {f"tp_{k}": v for k, v in TRATAMIENTOS_PREVIOS.items()}
    m = df[list(cols)].apply(pd.to_numeric, errors="coerce").eq(1)
    largo = m.assign(diagnostico=df["diagnostico"].values).melt("diagnostico", var_name="col", value_name="si")
    largo = largo[largo["si"]].assign(medicamento=lambda x: x["col"].map(cols))
    por_med = largo.groupby(["diagnostico", "medicamento"]).size().rename("n").reset_index()
    alguno = df.assign(_previo=m.any(axis=1)).groupby("diagnostico")["_previo"].agg(n="size", con_previo="sum").reset_index()
    alguno["pct"] = 100 * alguno["con_previo"] / alguno["n"]
    return por_med, alguno


# =========================================================================== 2 · Inicio y adherencia
def adherencia_semanas(df: pd.DataFrame) -> Dict[int, Tuple[float, int, int]]:
    """{semana: (% adherentes, adherentes, POR evaluados)}; medida DAX % Adherencia semX = adherentes / # POR."""
    out = {}
    for s in SEMANAS_ADHERENCIA:
        v = pd.to_numeric(df[f"Adherencia_final_{s}"], errors="coerce")
        ids = df.loc[v.notna(), "pacienteojoreingreso"]
        si = df.loc[v.eq(1), "pacienteojoreingreso"].nunique()
        n = ids.nunique()
        out[s] = (100 * si / n if n else np.nan, int(si), int(n))
    return out


def adherencia_por_dx(df: pd.DataFrame, semana: int) -> pd.DataFrame:
    """% adherente a la carga por diagnóstico, con n y dosis acumuladas promedio a la semana (si la corrida las trae)."""
    v = pd.to_numeric(df[f"Adherencia_final_{semana}"], errors="coerce")
    dosis = pd.to_numeric(df.get(f"apl_acum_sem{semana}"), errors="coerce") if f"apl_acum_sem{semana}" in df else pd.Series(np.nan, index=df.index)
    t = pd.DataFrame({"diagnostico": df["diagnostico"], "adh": v, "dosis": dosis}).dropna(subset=["adh"])
    g = t.groupby("diagnostico").agg(n=("adh", "size"), adherentes=("adh", "sum"), dosis=("dosis", "mean")).reset_index()
    g["pct"] = 100 * g["adherentes"] / g["n"]
    return g.set_index("diagnostico").reindex([d for d in orden_dx(df) if d in set(g["diagnostico"])]).reset_index()


# =========================================================================== 3 · Resultados
def con_evaluacion(df: pd.DataFrame) -> pd.DataFrame:
    """Solo los POR con al menos un registro de evolución (OCT o AV), como la tabla fact_EvolAV_OCT del PBI. Los POR sin
    ningún registro no cuentan como «Sin evaluar»: no entran (con datos reales del prestador base son 717 de 3.334)."""
    return df[df["tiene_evolucion"].fillna(False).astype(bool)] if "tiene_evolucion" in df else df


def clase_av_por_dx(df: pd.DataFrame, semana: int) -> pd.DataFrame:
    df = con_evaluacion(df)
    return reparto(df, "diagnostico", con_sin_evaluar(df[f"clase_AV_sem{semana}"], CLASES_AV), ORDEN_AV)


def clase_oct_por_dx(df: pd.DataFrame, semana: int) -> pd.DataFrame:
    df = con_evaluacion(df)
    return reparto(df, "diagnostico", con_sin_evaluar(df[f"clase_OCT_sem{semana}"]), ORDEN_OCT)


def respondedor_por_dx(df: pd.DataFrame) -> pd.DataFrame:
    df = con_evaluacion(df)
    return reparto(df, "diagnostico", con_sin_evaluar(df["Respondedor_sem16"]), ORDEN_RESP)


def retina_seca_por_dx(df: pd.DataFrame, semana: int) -> pd.DataFrame:
    """% con retina seca entre los POR evaluados en la semana, por diagnóstico; sin_evaluar aparte."""
    df = con_evaluacion(df)
    v = pd.to_numeric(df[f"RetinaSeca_sem{semana}"], errors="coerce")
    t = pd.DataFrame({"diagnostico": df["diagnostico"], "v": v})
    g = t.groupby("diagnostico")["v"].agg(evaluados="count", secos="sum", total="size").reset_index()
    g["sin_evaluar"] = g["total"] - g["evaluados"]
    g["pct"] = np.where(g["evaluados"] > 0, 100 * g["secos"] / g["evaluados"].where(g["evaluados"] > 0), np.nan)
    return g.set_index("diagnostico").reindex([d for d in orden_dx(df) if d in set(g["diagnostico"])]).reset_index()


# =========================================================================== 4 · Adherencia y resultados
def cruce_av_oct(df: pd.DataFrame, semana: int) -> Tuple[pd.DataFrame, float]:
    """Matriz clase AV (filas) × clase OCT (columnas) en número de POR, y % de POR sin AV evaluada en la semana
    (medidas DAX # POR Cruce V1V2V3 y % Sin Evaluar AV semX)."""
    df = con_evaluacion(df)
    av = con_sin_evaluar(df[f"clase_AV_sem{semana}"], CLASES_AV)
    oct_ = con_sin_evaluar(df[f"clase_OCT_sem{semana}"])
    t = pd.crosstab(av, oct_).reindex(index=[c for c in ORDEN_AV if c in set(av)], columns=[c for c in ORDEN_OCT if c in set(oct_)]).fillna(0).astype(int)
    pct_sin = 100 * float((av == SIN_EVALUAR).mean()) if len(av) else np.nan
    return t, pct_sin


def resultados_por_adherencia(df: pd.DataFrame, semana: int, semana_adh: int = 16) -> pd.DataFrame:
    """Adherentes frente a no adherentes a la carga (semana 16), por diagnóstico: % que mejora la AV, % con retina seca
    (entre evaluados) y cambio promedio de letras a la semana elegida. Gráfico nuevo (no estaba en el PBI)."""
    adh = pd.to_numeric(df[f"Adherencia_final_{semana_adh}"], errors="coerce").map({1: "Adherente", 0: "No adherente"})
    clase = df[f"clase_AV_sem{semana}"]
    seca = pd.to_numeric(df[f"RetinaSeca_sem{semana}"], errors="coerce")
    letras = pd.to_numeric(df[f"dif_lts_sem{semana}"], errors="coerce")
    t = pd.DataFrame({"diagnostico": df["diagnostico"], "grupo": adh, "mejora": clase.eq("mejora").where(clase.notna()),
                      "seca": seca, "letras": letras}).dropna(subset=["grupo"])
    filas = []
    for (dx, grupo), x in pd.concat([t, t.assign(diagnostico="Todos")]).groupby(["diagnostico", "grupo"]):
        filas.append({"diagnostico": dx, "grupo": grupo, "n": len(x), "n_av": int(x["mejora"].notna().sum()),
                      "pct_mejora": 100 * x["mejora"].dropna().astype(float).mean() if x["mejora"].notna().any() else np.nan,
                      "n_oct": int(x["seca"].notna().sum()), "pct_seca": 100 * x["seca"].mean() if x["seca"].notna().any() else np.nan,
                      "letras": x["letras"].mean()})
    out = pd.DataFrame(filas)
    if out.empty:
        return out
    orden = ["Todos"] + orden_dx(df)
    out["diagnostico"] = pd.Categorical(out["diagnostico"], [d for d in orden if d in set(out["diagnostico"])])
    return out.sort_values(["diagnostico", "grupo"]).reset_index(drop=True)


# =========================================================================== 5 · Carga de tratamiento
def _con_dos_anios(df: pd.DataFrame) -> pd.DataFrame:
    """Mismo universo que el Tablero (logic.enmascarar_anios): año 1 y año 2 solo con 2 años de seguimiento posible.
    El PBI promediaba a todos, y quien aún no cumple el año 2 contaba como 0 inyecciones."""
    return df[df["anio2_completo"].fillna(False).astype(bool)] if "anio2_completo" in df else df


def distribucion_inyecciones(df: pd.DataFrame) -> pd.DataFrame:
    """POR por número de inyecciones en el año 1 y en el año 2."""
    base, partes = _con_dos_anios(df), []
    for anio in (1, 2):
        v = pd.to_numeric(base[f"apl_anio{anio}"], errors="coerce").dropna().astype(int)
        g = v.value_counts().sort_index().rename_axis("inyecciones").rename("n").reset_index()
        g["pct"] = 100 * g["n"] / g["n"].sum() if len(g) else 0.0
        partes.append(g.assign(anio=f"Año {anio}"))
    return pd.concat(partes, ignore_index=True)


def resumen_inyecciones(df: pd.DataFrame) -> pd.DataFrame:
    base = _con_dos_anios(df)
    a1 = resumen_numerico(base, "apl_anio1").set_index("diagnostico").add_suffix(" año 1")
    a2 = resumen_numerico(base, "apl_anio2").set_index("diagnostico").add_suffix(" año 2")
    return a1.join(a2, how="outer").reindex(a1.index).reset_index()


# =========================================================================== réplica de la hoja 3a del PBI
# «Variables MPR — Adherencia y Agudeza Visual»: el equipo experto pidió verla igual que en el PBI (19-nov-2026).
BIN_LETRAS_PBI = {16: 10, 52: 13, 104: 25}   # columnas «dif_lts_semX (ubicaciones)» del PBI: INT(x / ancho) * ancho


def _orden_alfabetico(valores) -> List[str]:
    """Orden de las filas en las tablas dinámicas del PBI: alfabético sin distinguir mayúsculas."""
    return sorted({str(v) for v in valores}, key=str.lower)


def tabla_adherencia_dx(df: pd.DataFrame, semana: int = 16) -> pd.DataFrame:
    """Tabla «Adherencia a dosis de carga — semana 16, por diagnóstico» del PBI. Filas: diagnóstico (orden alfabético)
    y Total. Columnas (grupo, medida): grupo No / Sí / Total; medida apl = promedio de aplicaciones acumuladas a la
    semana, n = número de POR, pct = % sobre el total general (DIVIDE(COUNT, ScopedEval(COUNT, [])) del PBI)."""
    adh = pd.to_numeric(df[f"Adherencia_final_{semana}"], errors="coerce")
    col = f"apl_acum_sem{semana}"
    dosis = pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(np.nan, index=df.index)
    t = pd.DataFrame({"dx": df["diagnostico"].astype(str), "grupo": adh.map({0: "No", 1: "Sí"}), "dosis": dosis}).dropna(subset=["grupo"])
    total = len(t)
    filas = _orden_alfabetico(t["dx"]) + ["Total"]
    cols = pd.MultiIndex.from_product([["No", "Sí", "Total"], ["apl", "n", "pct"]])
    out = pd.DataFrame(index=filas, columns=cols, dtype=float)
    for fila in filas:
        x = t if fila == "Total" else t[t["dx"] == fila]
        for grupo in ("No", "Sí", "Total"):
            y = x if grupo == "Total" else x[x["grupo"] == grupo]
            out.loc[fila, (grupo, "apl")] = y["dosis"].mean() if len(y) else np.nan
            out.loc[fila, (grupo, "n")] = len(y)
            out.loc[fila, (grupo, "pct")] = 100 * len(y) / total if total else np.nan
    return out


def tabla_clase_av(df: pd.DataFrame, semana: int) -> pd.DataFrame:
    """Tabla «Clase de ganancia de agudeza visual por diagnóstico (semana seleccionable)» del PBI: POR por diagnóstico y
    clase (empeora, mantiene, mejora, Sin evaluar) con su Total. Solo POR con registro de evolución (fact_EvolAV_OCT)."""
    d = con_evaluacion(df)
    clase = d[f"clase_AV_sem{semana}"].astype(object).where(d[f"clase_AV_sem{semana}"].notna(), SIN_EVALUAR)
    t = pd.crosstab(d["diagnostico"].astype(str), clase)
    columnas = ["empeora", "mantiene", "mejora", SIN_EVALUAR]
    t = t.reindex(index=_orden_alfabetico(t.index), columns=columnas, fill_value=0)
    t["Total"] = t.sum(axis=1)
    t.loc["Total"] = t.sum()
    return t.astype(int)


def histograma_letras_pbi(serie: pd.Series, semana: int) -> pd.DataFrame:
    """Gráfico «Distribución de diferencia en letras AV (semana seleccionable)» del PBI: cada valor cae en el intervalo
    INT(x / ancho) * ancho (INT de DAX redondea hacia abajo), con ancho 10, 13 o 25 letras según la semana."""
    ancho = BIN_LETRAS_PBI[semana]
    v = pd.to_numeric(serie, errors="coerce").dropna()
    inicio = (np.floor(v / ancho) * ancho).astype(int)
    g = inicio.value_counts().sort_index().rename_axis("inicio").rename("n").reset_index()
    g["fin"] = g["inicio"] + ancho
    return g
