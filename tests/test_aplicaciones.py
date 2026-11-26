"""Pruebas de la página «Seguimiento de aplicaciones» (logic_aplicaciones.py y pipeline/gestion.py).

1. Columnas calculadas y medidas del Power BI «reporte_aplicaciones_v4»: se reescriben aquí de forma independiente, fila
   por fila y como en DAX (búsqueda de la dosis con_dosis − 1 del mismo POR), y se comparan con la app.
2. Lógica del Excel «tablero_alertas_aplicaciones» (agrupar_ultima_fecha, Programación, Reportes): réplica independiente
   de los pasos de Power Query y de las fórmulas, comparada con la app en modo Excel; y el modo de la app.
3. Registro de la gestión: se guarda, se lee, no se borra, vale el más reciente, exige causa y responsable, y se cifra.

Además (fuera de estas pruebas, con los archivos reales; nov-2026): las columnas calculadas coinciden con las que trae
el modelo del PBI en 2.243 de 2.245 filas (las 2 restantes son registros que el lector del .pbix no decodifica bien), y
las 31 cifras de la hoja Reportes del Excel coinciden con la app en modo Excel.

Ejecutar:  python -m unittest tests.test_aplicaciones -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "dashboard"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import logic_aplicaciones as LA  # noqa: E402
from pipeline import gestion, seguridad  # noqa: E402

CORRIDA = ROOT / "data" / "processed" / "p2" / "v5.4.0_2026-10-27"


def datos() -> pd.DataFrame:
    return LA.cargar(CORRIDA)


def redondeo_dax(x: float) -> float:
    return float(np.sign(x) * np.floor(abs(x) + 0.5))


# =========================================================================== réplica DAX, fila por fila
def columnas_dax(apl: pd.DataFrame) -> pd.DataFrame:
    """Como las columnas calculadas del PBI: para cada fila, CALCULATE(MAX(...), FILTER(ALL(tabla), mismo POR y
    con_dosis = actual − 1)). Recorre las filas una por una (lento a propósito: no comparte código con la app)."""
    por_clave = {}
    for r in apl.itertuples():
        por_clave.setdefault((r.pacienteojoreingreso, r.con_dosis), []).append(r)
    filas = []
    for r in apl.itertuples():
        prev = por_clave.get((r.pacienteojoreingreso, r.con_dosis - 1), [])
        apl_ant = max([p.fecha_aplicacion for p in prev if pd.notna(p.fecha_aplicacion)], default=pd.NaT)
        prog_ant = max([p.fecha_programacion for p in prev if pd.notna(p.fecha_programacion)], default=pd.NaT)
        dias_entre = (r.fecha_aplicacion - apl_ant).days if pd.notna(apl_ant) else np.nan
        dias_prog = (r.fecha_programacion - r.fecha_aplicacion).days if pd.notna(r.fecha_programacion) and pd.notna(r.fecha_aplicacion) else np.nan
        dias_cumpl = (r.fecha_aplicacion - prog_ant).days if pd.notna(prog_ant) and pd.notna(r.fecha_aplicacion) else np.nan
        if pd.isna(dias_cumpl):
            clase = "Sin dato"
        elif dias_cumpl < -10:
            clase = "1. Muy adelantado (>10d)"
        elif dias_cumpl < 0:
            clase = "2. Adelantado (1-10d)"
        elif dias_cumpl == 0:
            clase = "3. Exacto"
        elif dias_cumpl <= 10:
            clase = "4. Retraso leve (1-10d)"
        elif dias_cumpl <= 30:
            clase = "5. Retraso moderado (11-30d)"
        else:
            clase = "6. Retraso grave (>30d)"
        filas.append({"FecApl_Anterior": apl_ant, "FechaProg_Anterior": prog_ant, "Dias_Entre_Dosis": dias_entre,
                      "Semanas_Entre_Dosis": redondeo_dax(dias_entre / 7) if pd.notna(dias_entre) else np.nan,
                      "Dias_Apl_a_Prog": dias_prog, "Semanas_Apl_a_Prog": redondeo_dax(dias_prog / 7) if pd.notna(dias_prog) else np.nan,
                      "Dias_Cumplimiento": dias_cumpl, "Clasificacion_Cumplimiento": clase})
    return pd.DataFrame(filas, index=apl.index)


class TestColumnasYMedidasPBI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apl = datos()
        cls.dax = columnas_dax(cls.apl)

    def test_columnas_calculadas_fila_por_fila(self):
        for c in self.dax.columns:
            with self.subTest(columna=c):
                a, b = self.dax[c], self.apl[c]
                if c == "Clasificacion_Cumplimiento":
                    self.assertTrue((a == b).all())
                elif c in ("FecApl_Anterior", "FechaProg_Anterior"):
                    self.assertTrue(((a == b) | (a.isna() & b.isna())).all())
                else:
                    self.assertTrue(np.allclose(pd.to_numeric(a), pd.to_numeric(b), equal_nan=True))

    def test_medidas_del_periodo(self):
        desde, hasta = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")
        a = self.apl
        aplicadas = int(((a.fecha_aplicacion >= desde) & (a.fecha_aplicacion <= hasta)).sum())
        programadas = int(((a.fecha_programacion >= desde) & (a.fecha_programacion <= hasta)).sum())
        en_periodo = a[(a.fecha_aplicacion >= desde) & (a.fecha_aplicacion <= hasta)]
        cumpl = en_periodo[self.dax.loc[en_periodo.index, "Dias_Cumplimiento"].notna()]
        dentro = self.dax.loc[cumpl.index, "Dias_Cumplimiento"].between(-10, 10).mean() * 100
        self.assertEqual(len(LA.dosis_aplicadas(a, desde, hasta)), aplicadas)
        self.assertEqual(len(LA.dosis_programadas(a, desde, hasta)), programadas)
        self.assertEqual(len(LA.cumplimiento(a, desde, hasta)), len(cumpl))
        self.assertAlmostEqual(LA.pct_dentro_ventana(LA.cumplimiento(a, desde, hasta)), dentro)

    def test_distribuciones_y_matriz(self):
        x = LA.dosis_aplicadas(self.apl, "2025-01-01", "2025-12-31")
        c = LA.conteo(x, "molecula_label")
        self.assertEqual(int(c["n"].sum()), len(x))
        m = LA.matriz(x, "con_dosis", "Semanas_Entre_Dosis")
        self.assertEqual(int(m.loc["Total", "Total"]), int(x["Semanas_Entre_Dosis"].notna().sum()))

    def test_redondeo_como_dax(self):
        self.assertEqual(list(LA.redondear(pd.Series([2.5, -2.5, 1.49, 0.5]))), [3.0, -3.0, 1.0, 1.0])


# =========================================================================== réplica del Excel
def agrupar_ultima_fecha_excel(apl: pd.DataFrame, corte, ventana: int) -> pd.DataFrame:
    """Pasos de Power Query del Excel: fecha programada vacía -> 01/01/1950; Table.Group por POR con
    List.Max(fecha_programacion) y List.Min de los atributos; DAYS(corte, última) y la fórmula del Flag."""
    a = apl.copy()
    a["fecha_programacion"] = a["fecha_programacion"].fillna(pd.Timestamp("1950-01-01"))
    filas = []
    for por, g in a.groupby(a["pacienteojoreingreso"].fillna("(sin POR)")):
        ultima = g["fecha_programacion"].max()
        dias = (pd.Timestamp(corte) - ultima).days
        flag = "En Rango" if abs(dias) <= ventana else ("Retraso" if dias > ventana else "Se adelantó")
        filas.append({"pacienteojoreingreso": por, "dias": dias, "flag": flag, "dx": g["diagnostico_apl"].dropna().astype(str).min(),
                      "medico": g["medico"].dropna().astype(str).min()})
    return pd.DataFrame(filas)


class TestExcelAlertas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.apl = datos()
        cls.corte = pd.Timestamp("2025-06-30")

    def test_modo_excel_igual_a_la_replica(self):
        ex = agrupar_ultima_fecha_excel(self.apl, self.corte, 10).set_index("pacienteojoreingreso")
        app = LA.alertas(self.apl, self.corte, 10, modo_excel=True).set_index("pacienteojoreingreso")
        self.assertEqual(set(ex.index), set(app.index))
        mapa = {"En Rango": LA.EN_RANGO, "Retraso": LA.RETRASO, "Se adelantó": LA.FUTURA}
        self.assertTrue((ex["flag"].map(mapa) == app.loc[ex.index, "estado"]).all())
        self.assertTrue((ex["dias"] == app.loc[ex.index, "dias"]).all())
        self.assertTrue((ex["dx"] == app.loc[ex.index, "diagnostico_apl"]).all())

    def test_programacion_y_ultimas_dosis(self):
        desde, hasta = pd.Timestamp("2025-06-01"), pd.Timestamp("2025-06-30")
        prog = LA.dosis_programadas(self.apl, desde, hasta)
        b = self.apl
        self.assertEqual(len(prog), int(((b.fecha_programacion >= desde) & (b.fecha_programacion <= hasta)).sum()))   # COUNTIFS de B7
        d = LA.reporte_dosis(prog)
        for i in range(1, 7):                                                                                         # COUNTIFS de C48:C53
            self.assertEqual(int(d.loc[f"Dosis {i}", "n"]), int((prog["con_dosis"] == i).sum()))
        self.assertEqual(int(d.loc["Total", "n"]), len(prog))

    def test_reporte_por_categoria(self):
        prog = LA.dosis_programadas(self.apl, "2025-06-01", "2025-06-30")
        al = LA.alertas(self.apl, self.corte, 10, modo_excel=True)
        r = LA.reporte_por(al, prog, "diagnostico_apl", "diagnostico_apl")
        ex = agrupar_ultima_fecha_excel(self.apl, self.corte, 10)
        for dx, n in ex[ex["flag"] == "Retraso"]["dx"].value_counts().items():                                       # COUNTIFS de K13:K16
            self.assertEqual(int(r.loc[dx, "retraso_n"]), int(n))
        self.assertAlmostEqual(float(r.drop("Total")["retraso_pct"].sum()), 100.0)

    def test_modo_app_hasta_la_fecha_de_corte(self):
        """La app solo mira lo aplicado hasta la fecha de corte. Con una fecha de corte posterior a todos los datos y sin
        fechas programadas vacías, da lo mismo que el Excel."""
        corte = self.apl["fecha_aplicacion"].max() + pd.Timedelta(days=1)
        self.assertEqual(int(self.apl["fecha_programacion"].isna().sum()), 0)
        app = LA.alertas(self.apl, corte, 10).set_index("pacienteojoreingreso")["estado"]
        ex = LA.alertas(self.apl, corte, 10, modo_excel=True).set_index("pacienteojoreingreso")["estado"]
        self.assertTrue((app == ex.loc[app.index]).all())
        # con un corte intermedio, una aplicación posterior al corte no cuenta
        corte = pd.Timestamp("2023-06-30")
        al = LA.alertas(self.apl, corte, 10)
        self.assertTrue((al["ultima_aplicacion"] <= corte).all())

    def test_sin_fecha_programada_no_es_retraso(self):
        a = self.apl.copy()
        por = a["pacienteojoreingreso"].iloc[0]
        a.loc[a["pacienteojoreingreso"] == por, "fecha_programacion"] = pd.NaT
        app = LA.alertas(a, self.corte, 10).set_index("pacienteojoreingreso")
        ex = LA.alertas(a, self.corte, 10, modo_excel=True).set_index("pacienteojoreingreso")
        self.assertEqual(app.loc[por, "estado"], LA.SIN_FECHA)
        self.assertEqual(ex.loc[por, "estado"], LA.RETRASO)          # el Excel la ponía en 1950

    def test_kpis(self):
        prog = LA.dosis_programadas(self.apl, "2025-06-01", "2025-06-30")
        al = LA.alertas(self.apl, self.corte, 10)
        ret = al[al["estado"] == LA.RETRASO].iloc[0]
        k = LA.kpis_alertas(prog, al, {(ret["pacienteojoreingreso"], ret["ultima_programada"])})
        self.assertEqual(k["con_gestion"], 1)
        self.assertEqual(k["con_gestion"] + k["sin_gestion"], k["retraso"])
        self.assertAlmostEqual(k["pct_en_rango"], 100 * k["en_rango"] / (k["en_rango"] + k["retraso"]))


# =========================================================================== gestión
class TestGestion(unittest.TestCase):
    def test_registrar_leer_y_vigente(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            gestion.registrar("p2", "900001OD0", "2025-03-01", gestion.CAUSAS[0], "llamada", "Enfermera", raiz=raiz)
            gestion.registrar("p2", "900001OD0", "2025-03-01", "Cambio de IPS", "corrige", "Coordinación", raiz=raiz)
            gestion.registrar("p2", "900001OD0", "2025-06-01", "Fallecimiento", "", "Coordinación", raiz=raiz)
            todo = gestion.leer("p2", raiz=raiz)
            self.assertEqual(len(todo), 3)                                   # nada se borra
            vig = gestion.vigentes(todo)
            self.assertEqual(len(vig), 2)                                    # una por cita
            marzo = vig[vig["fecha_programada"] == pd.Timestamp("2025-03-01")].iloc[0]
            self.assertEqual(marzo["causa"], "Cambio de IPS")                # vale la más reciente
            self.assertEqual(marzo["gestionado_por"], "Coordinación")

    def test_validaciones(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                gestion.registrar("p2", "900001OD0", "2025-03-01", "Causa inventada", "", "Enfermera", raiz=Path(d))
            with self.assertRaises(ValueError):
                gestion.registrar("p2", "900001OD0", "2025-03-01", gestion.CAUSAS[0], "", "  ", raiz=Path(d))
            self.assertTrue(gestion.leer("p2", raiz=Path(d)).empty)

    def test_cifrado(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            llave = seguridad.crear_llave("clave-de-prueba", raiz)
            gestion.registrar("p2", "900001OD0", "2025-03-01", gestion.CAUSAS[0], "obs", "Enfermera", raiz=raiz, llave=llave)
            f = gestion.ruta("p2", raiz)
            self.assertFalse(f.exists())                                     # en claro no queda nada
            self.assertTrue(Path(str(f) + seguridad.SUFIJO).exists())
            self.assertFalse(any(p.suffix == ".tmp" for p in f.parent.iterdir()))
            self.assertEqual(len(gestion.leer("p2", raiz=raiz, llave=llave)), 1)
            self.assertTrue(gestion.leer("p2", raiz=raiz, llave=None).empty or os.getenv("VLM_CLAVE"))
            with self.assertRaises(ValueError):                              # cifrado activo y sin llave: no guarda en claro
                gestion.registrar("p2", "900001OD0", "2025-04-01", gestion.CAUSAS[0], "", "Enfermera", raiz=raiz, llave=None)


if __name__ == "__main__":
    unittest.main()
