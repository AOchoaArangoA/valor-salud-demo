"""Compara los cálculos de la página «Análisis de adherencia» con las medidas DAX del Power BI 01-reporte-adherencia_v4.

La réplica DAX se arma aparte, directamente desde las tablas que el PBI leía (las mismas que hoy produce el proceso:
adherencia, evolucion, pacientes) y siguiendo sus pasos de Power Query: «Sin evaluar» en las clases vacías, un registro
por paciente-ojo reingreso en dim_Paciente (el más reciente) y conteos DISTINCTCOUNT. No usa logic_adherencia.

Ejecutar:
    python -m unittest tests.test_adherencia -v        # pruebas
    python tests/test_adherencia.py --tabla            # tabla de cifras PBI vs. app (para revisar)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "dashboard"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logic as L  # noqa: E402
import logic_adherencia as A  # noqa: E402

CORRIDA = ROOT / "data" / "processed" / "p2" / "v5.4.0_2026-10-27"
SIN = "Sin evaluar"


# =========================================================================== réplica del modelo del PBI
def modelo_pbi(corrida: Path = CORRIDA) -> dict:
    dim = pd.read_parquet(corrida / "pacientes.parquet")
    dim = dim.sort_values("fecha_registro", ascending=False).drop_duplicates("pacienteojoreingreso")   # «Duplicados quitados»
    adh = pd.read_parquet(corrida / "adherencia.parquet")
    evo = pd.read_parquet(corrida / "evolucion.parquet")
    for s in (16, 52, 104):                                    # «Valor reemplazado»: null -> "Sin evaluar"
        for c in (f"clase_AV_sem{s}", f"clase_OCT_sem{s}", f"RetinaSeca_sem{s}"):
            evo[c] = evo[c].astype(object).where(evo[c].notna(), SIN)
    return {"dim": dim, "adh": adh, "evo": evo}


def dax(m: dict) -> dict:
    """Las medidas del PBI (tabla _Medidas y tablas dinámicas de las hojas 2a a 3d), escritas como en DAX."""
    dim, adh, evo = m["dim"], m["adh"], m["evo"]
    r = {"# Pacientes únicos": dim["numero_doc"].nunique(), "# PO": dim["pacienteojo"].nunique(),
         "# POR": dim["pacienteojoreingreso"].nunique()}
    total_adh = adh["pacienteojoreingreso"].nunique()
    for s in (12, 16, 20):
        r[f"% Adherencia sem{s}"] = 100 * adh.loc[adh[f"Adherencia_final_{s}"] == 1, "pacienteojoreingreso"].nunique() / total_adh
    for a in ("diabetes", "hta", "dislipidemia", "insulina"):
        r[f"# POR con {a}"] = dim.loc[dim[f"ant_{a}"] == 1, "pacienteojoreingreso"].nunique()
    for s in (16, 52, 104):
        r[f"Promedio Dif Letras sem{s}"] = evo[f"dif_lts_sem{s}"].mean()
        r[f"% Sin Evaluar AV sem{s}"] = 100 * evo.loc[evo[f"clase_AV_sem{s}"] == SIN, "pacienteojoreingreso"].nunique() / evo["pacienteojoreingreso"].nunique()
        r[f"Clase AV sem{s} (dx × clase)"] = evo.groupby(["dx_ppal", f"clase_AV_sem{s}"])["pacienteojoreingreso"].nunique()
        r[f"Clase OCT sem{s} (dx × clase)"] = evo.groupby(["dx_ppal", f"clase_OCT_sem{s}"])["pacienteojoreingreso"].nunique()
        r[f"Retina seca sem{s} (dx × valor)"] = evo.groupby(["dx_ppal", f"RetinaSeca_sem{s}"])["pacienteojoreingreso"].nunique()
        r[f"Cruce AV×OCT sem{s}"] = evo.groupby([f"clase_AV_sem{s}", f"clase_OCT_sem{s}"])["pacienteojoreingreso"].nunique()
    r["Respondedor (dx × clase)"] = evo.groupby(["dx_ppal", "Respondedor_sem16"])["pacienteojoreingreso"].nunique()   # sin «Sin evaluar»
    x = adh.merge(dim[["pacienteojoreingreso", "dx_ppal"]], on="pacienteojoreingreso")
    r["Adherencia sem16 (dx × sí/no)"] = x.groupby(["dx_ppal", "Adherencia_final_16"])["pacienteojoreingreso"].nunique()
    r["Promedio Apl Acum sem16 (dx)"] = x.groupby("dx_ppal")["apl_acum_sem16"].mean()
    for c in ("extension_sem52", "extension_sem104", "apl_anio1", "apl_anio2"):
        r[f"Promedio {c} (dx)"] = adh.groupby("dx_ppal_desc")[c].mean()
        r[f"Mediana {c} (dx)"] = adh.groupby("dx_ppal_desc")[c].median()
    r["Promedio Oportunidad Inicio (dx)"] = evo.groupby("dx_ppal")["Oportunidad_inicio_tto"].mean()
    r["Mediana Oportunidad Inicio (dx)"] = evo.groupby("dx_ppal")["Oportunidad_inicio_tto"].median()
    tp = []                                                    # fact_TratamientoPrevio: anexar tp_<med> = 1
    for k, flag in (("afli", "AFL"), ("rani", "RNB"), ("beva", "Beva"), ("brolu", "BROLU"), ("fari", "FARI"), ("dexa", "DEXA")):
        tp.append(dim.loc[dim[f"tp_{k}"] == 1, ["pacienteojoreingreso", "dx_ppal"]].assign(flag=flag))
    tp = pd.concat(tp)
    r["Tratamiento previo (dx × medicamento)"] = tp.groupby(["dx_ppal", "flag"])["pacienteojoreingreso"].count()
    return r


# =========================================================================== lo mismo con la app
def datos_app(corrida: Path = CORRIDA) -> pd.DataFrame:
    mart, _ = L.cargar(corrida)
    return A.cargar(corrida, mart)


def app(df: pd.DataFrame) -> dict:
    r = {}
    c = A.conteos(df)
    r["# Pacientes únicos"], r["# PO"], r["# POR"] = c["pacientes"], c["po"], c["por"]
    for s, (pct, _, _) in A.adherencia_semanas(df).items():
        r[f"% Adherencia sem{s}"] = pct
    combos, totales = A.combinaciones_antecedentes(df)
    for a, nombre in (("diabetes", "Diabetes"), ("hta", "HTA"), ("dislipidemia", "Dislipidemia"), ("insulina", "Insulina")):
        r[f"# POR con {a}"] = int(totales.get(nombre, 0))
    for s in (16, 52, 104):
        r[f"Promedio Dif Letras sem{s}"] = pd.to_numeric(df[f"dif_lts_sem{s}"], errors="coerce").mean()
        t, pct_sin = A.cruce_av_oct(df, s)
        r[f"% Sin Evaluar AV sem{s}"] = pct_sin
        av = A.clase_av_por_dx(df, s)
        inv = {v: k for k, v in A.CLASES_AV.items()}
        av["categoria"] = av["categoria"].astype(str).map(lambda x: inv.get(x, x))
        r[f"Clase AV sem{s} (dx × clase)"] = av.set_index(["fila", "categoria"])["n"]
        r[f"Clase OCT sem{s} (dx × clase)"] = A.clase_oct_por_dx(df, s).assign(categoria=lambda x: x["categoria"].astype(str)).set_index(["fila", "categoria"])["n"]
        rs = A.retina_seca_por_dx(df, s)
        largo = pd.concat([rs.assign(v=1.0, n=rs["secos"]), rs.assign(v=0.0, n=rs["evaluados"] - rs["secos"]), rs.assign(v=SIN, n=rs["sin_evaluar"])])
        r[f"Retina seca sem{s} (dx × valor)"] = largo[largo["n"] > 0].set_index(["diagnostico", "v"])["n"]
        r[f"Cruce AV×OCT sem{s}"] = t.rename(index=inv).stack()[lambda x: x > 0]
    resp = A.respondedor_por_dx(df)
    resp = resp[resp["categoria"].astype(str) != A.SIN_EVALUAR]
    r["Respondedor (dx × clase)"] = resp.assign(categoria=lambda x: x["categoria"].astype(str)).set_index(["fila", "categoria"])["n"]
    ad = A.adherencia_por_dx(df, 16)
    r["Adherencia sem16 (dx × sí/no)"] = pd.concat([ad.assign(v=1, k=ad["adherentes"]), ad.assign(v=0, k=ad["n"] - ad["adherentes"])]
                                                   ).set_index(["diagnostico", "v"])["k"]
    r["Promedio Apl Acum sem16 (dx)"] = ad.set_index("diagnostico")["dosis"]
    for c in ("extension_sem52", "extension_sem104", "apl_anio1", "apl_anio2"):
        t = A.resumen_numerico(df, c).set_index("diagnostico").drop("Total")   # sin el filtro de 2 años: así lo hace el PBI
        r[f"Promedio {c} (dx)"], r[f"Mediana {c} (dx)"] = t["promedio"], t["mediana"]
    t = A.resumen_numerico(df, "Oportunidad_inicio_tto").set_index("diagnostico").drop("Total")
    r["Promedio Oportunidad Inicio (dx)"], r["Mediana Oportunidad Inicio (dx)"] = t["promedio"], t["mediana"]
    por_med, _ = A.tratamiento_previo(df)
    flags = {"Aflibercept": "AFL", "Ranibizumab": "RNB", "Bevacizumab": "Beva", "Brolucizumab": "BROLU", "Faricimab": "FARI", "Dexametasona": "DEXA"}
    r["Tratamiento previo (dx × medicamento)"] = por_med.assign(flag=por_med["medicamento"].map(flags)).set_index(["diagnostico", "flag"])["n"]
    return r


def _iguales(a, b) -> bool:
    if isinstance(a, pd.Series):
        a = a.astype(float).sort_index()
        b = pd.Series(b).astype(float)
        b.index = b.index.set_names(a.index.names)
        b = b.reindex(a.index)
        return len(a) == len(pd.Series(b).dropna()) and np.allclose(a.values, b.values, equal_nan=True)
    return bool(np.isclose(float(a), float(b), equal_nan=True))


class TestCifrasIgualesAlPBI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = datos_app()
        cls.pbi, cls.app = dax(modelo_pbi()), app(cls.df)

    def test_todas_las_medidas(self):
        for k, v in self.pbi.items():
            with self.subTest(medida=k):
                self.assertIn(k, self.app)
                self.assertTrue(_iguales(v, self.app[k]), f"{k}: PBI {v!r} ≠ app {self.app[k]!r}")

    def test_un_registro_por_por(self):
        self.assertEqual(len(self.df), self.df["pacienteojoreingreso"].nunique())


class TestVenn(unittest.TestCase):
    def test_zonas_cuadran_con_las_medidas_del_pbi(self):
        df = datos_app()
        zonas, totales, ninguno = A.venn_antecedentes(df)
        self.assertEqual(sum(zonas.values()) + ninguno, len(df))
        pbi = dax(modelo_pbi())
        for i, (col, nombre) in enumerate(A.ANTECEDENTES.items()):
            con = sum(n for k, n in zonas.items() if k[i] == "1")
            self.assertEqual(con, totales[nombre])
            self.assertEqual(con, pbi[f"# POR con {col.replace('ant_', '')}"])

    def test_cada_etiqueta_cae_en_su_zona(self):
        for clave, (x, y) in A.VENN_ZONAS.items():
            zona = "".join("1" if A.dentro_de_elipse(x, y, e) else "0" for e in A.VENN_ELIPSES)
            self.assertEqual(zona, clave)


class TestUniversoEvolucion(unittest.TestCase):
    """Con datos reales hay POR sin ningún registro de OCT/AV (717 de 3.334 en el prestador base). Como en el PBI
    (tabla fact_EvolAV_OCT), las clases de AV/OCT, la retina seca, el respondedor y los cruces no los cuentan como
    «Sin evaluar»: quedan fuera. Los sintéticos no tienen ese caso; aquí se simula."""

    def test_por_sin_evolucion_no_cuentan(self):
        df = datos_app()
        self.assertTrue(df["tiene_evolucion"].all())
        sin = df.copy()
        quitar = sin.index[:200]
        sin.loc[quitar, "tiene_evolucion"] = False
        sin.loc[quitar, [c for c in sin.columns if c.startswith(("clase_", "RetinaSeca_")) or c == "Respondedor_sem16"]] = np.nan
        self.assertEqual(int(A.clase_av_por_dx(sin, 52)["n"].sum()), len(df) - 200)
        self.assertEqual(int(A.clase_oct_por_dx(sin, 52)["n"].sum()), len(df) - 200)
        self.assertEqual(int(A.respondedor_por_dx(sin)["n"].sum()), len(df) - 200)
        self.assertEqual(int(A.retina_seca_por_dx(sin, 52)["total"].sum()), len(df) - 200)
        t, pct = A.cruce_av_oct(sin, 16)
        self.assertEqual(int(t.values.sum()), len(df) - 200)
        evo = sin[sin["tiene_evolucion"]]
        self.assertAlmostEqual(pct, 100 * evo["clase_AV_sem16"].isna().mean())


class TestHoja3a(unittest.TestCase):
    """Réplica de la hoja 3a del PBI (tabla de adherencia por diagnóstico, tabla de clase AV e histograma de letras).
    Las cifras se compararon además, fila por fila, con la foto del PBI usando el formulario real (19-nov-2026)."""

    def setUp(self):
        self.df = datos_app()
        self.pbi = dax(modelo_pbi())

    def test_tabla_adherencia(self):
        t = A.tabla_adherencia_dx(self.df, 16)
        pct, si, n = A.adherencia_semanas(self.df)[16]
        self.assertEqual(int(t.loc["Total", ("Sí", "n")]), si)
        self.assertEqual(int(t.loc["Total", ("Total", "n")]), n)
        self.assertAlmostEqual(t.loc["Total", ("Sí", "pct")], pct)
        self.assertAlmostEqual(t.drop("Total")[("Total", "pct")].sum(), 100.0)
        cuenta = self.pbi["Adherencia sem16 (dx × sí/no)"]
        for dx in t.index.drop("Total"):
            self.assertEqual(int(t.loc[dx, ("No", "n")]), int(cuenta.get((dx, 0), 0)))
            self.assertEqual(int(t.loc[dx, ("Sí", "n")]), int(cuenta.get((dx, 1), 0)))
            self.assertAlmostEqual(t.loc[dx, ("Total", "apl")], self.pbi["Promedio Apl Acum sem16 (dx)"][dx])
        self.assertEqual(list(t.index[:-1]), sorted(t.index[:-1], key=str.lower))

    def test_tabla_clase_av(self):
        for s in (16, 52, 104):
            t = A.tabla_clase_av(self.df, s)
            pbi = self.pbi[f"Clase AV sem{s} (dx × clase)"]
            for (dx, clase), n in pbi.items():
                self.assertEqual(int(t.loc[dx, clase]), int(n))
            self.assertEqual(int(t.loc["Total", "Total"]), int(pbi.sum()))

    def test_histograma_con_los_intervalos_del_pbi(self):
        v = pd.Series([-26, -25, -1, 0, 24, 25, 60])
        h = A.histograma_letras_pbi(v, 104).set_index("inicio")["n"].to_dict()
        self.assertEqual(h, {-50: 1, -25: 2, 0: 2, 25: 1, 50: 1})       # INT de DAX redondea hacia abajo
        self.assertEqual(A.BIN_LETRAS_PBI, {16: 10, 52: 13, 104: 25})


class TestCorrecciones(unittest.TestCase):
    """Donde la app corrige al PBI, la prueba deja escrita la diferencia esperada."""

    def test_intervalos_simetricos_y_del_mismo_ancho(self):
        v = pd.Series([-12, -7, -3, -2.5, 0, 2.4, 3, 9, 14])
        h = A.intervalos(v, 5)
        self.assertEqual(int(h["n"].sum()), len(v))
        self.assertEqual(h.set_index("centro").loc[0, "n"], 3)            # [-2,5; 2,5): -2,5, 0 y 2,4
        # el PBI usaba INT(x/10)*10 (INT de DAX redondea hacia abajo): el intervalo «0» iba de 0 a 10, no estaba
        # centrado en 0, así que un paciente estable (-2 letras) y otro con +9 caían en intervalos distintos o iguales sin simetría
        pbi = np.floor(v / 10) * 10
        self.assertEqual(int((pbi == 0).sum()), 4)                         # 0, 2,4, 3 y 9

    def test_inyecciones_usan_el_universo_del_tablero(self):
        df = datos_app()
        t = A.resumen_inyecciones(df).set_index("diagnostico")
        self.assertEqual(int(t.loc["Total", "n año 1"]), int(df["anio2_completo"].sum()))
        self.assertLess(int(t.loc["Total", "n año 1"]), int(df["apl_anio1"].notna().sum()))   # el PBI promedia a todos

    def test_grupos_de_edad_ordenados(self):
        p = A.piramide(datos_app())
        self.assertEqual(list(p["Grupo_edad"].cat.categories), [e for e in A.ORDEN_EDAD if e in set(p["Grupo_edad"].astype(str))])


def tabla_comparacion() -> pd.DataFrame:
    pbi, ap = dax(modelo_pbi()), app(datos_app())
    filas = []
    for k, v in pbi.items():
        if isinstance(v, pd.Series):
            filas.append({"medida": k, "PBI": f"{len(v)} celdas, suma {float(v.astype(float).sum()):,.1f}",
                          "app": f"{len(pd.Series(ap[k]).dropna())} celdas, suma {float(pd.Series(ap[k]).astype(float).sum()):,.1f}",
                          "igual": _iguales(v, ap[k])})
        else:
            filas.append({"medida": k, "PBI": f"{float(v):,.2f}", "app": f"{float(ap[k]):,.2f}", "igual": _iguales(v, ap[k])})
    return pd.DataFrame(filas)


if __name__ == "__main__":
    if "--tabla" in sys.argv:
        pd.set_option("display.width", 200, "display.max_rows", 200, "display.max_colwidth", 60)
        print(tabla_comparacion().to_string(index=False))
    else:
        unittest.main()
