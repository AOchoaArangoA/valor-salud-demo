"""Abre la aplicación con streamlit.testing (sin navegador) y recorre cada pestaña de «Análisis de adherencia» con cada
semana, más un filtro que no deja pacientes, y cada nivel del Tablero. Falla si aparece una excepción o un error.

Ejecutar:  python -m unittest tests.test_paginas -v      (tarda ~1-2 minutos)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "dashboard" / "app.py")
sys.path.insert(0, str(ROOT / "dashboard"))
PESTANAS = ["1 · Población", "2 · Adherencia y AV", "3 · Resultados", "4 · Adherencia y resultados", "5 · Carga de tratamiento"]
SEMANA = {"2 · Adherencia y AV": ("sel-clase-av", [16, 52, 104]), "3 · Resultados": ("sem-res", [16, 52, 104]),
          "4 · Adherencia y resultados": ("sem-cruce", [16, 52, 104]), "5 · Carga de tratamiento": ("sem-ext", [52, 104])}
NIVELES = ["1 · Visión ejecutiva", "2 · Cohortes", "3 · Gestión de la atención", "4 · Paciente-ojo", "5 · Calidad de vida", "6 · Valor", "7 · Metodología"]


def abrir(pagina: str | None = None, **estado) -> AppTest:
    """Una sola ejecución con el estado ya puesto. La página se abre directamente (no con switch_page): AppTest no sabe
    volver a ejecutar una app con un segmented_control activo (falla al leer su valor)."""
    at = AppTest.from_file(str(ROOT / "dashboard" / pagina) if pagina else APP, default_timeout=240)
    for k, v in estado.items():
        at.session_state[k] = v
    at.run()
    return at


def problemas(at: AppTest) -> list:
    return [str(e.value)[:400] for e in at.exception] + [str(e.body)[:400] for e in at.error]


class TestAdherencia(unittest.TestCase):
    def test_cada_pestana_y_semana(self):
        for p in PESTANAS:
            clave, semanas = SEMANA.get(p, (None, [None]))
            for s in semanas:
                with self.subTest(pestana=p, semana=s):
                    estado = {"vista-adh": p, **({clave: s} if clave else {})}
                    at = abrir("paginas/adherencia.py", **estado)
                    self.assertEqual(problemas(at), [])
                    self.assertGreater(len(at.get("plotly_chart")), 0, "la pestaña no dibujó gráficos")

    def test_filtro_sin_pacientes(self):
        at = abrir("paginas/adherencia.py", **{"vista-adh": PESTANAS[0], "f-dx": []})
        self.assertEqual(problemas(at), [])
        self.assertTrue(any("ningún paciente-ojo" in w.body for w in at.warning))

    def test_filtro_de_un_solo_diagnostico_pequeno(self):
        for p in PESTANAS:
            with self.subTest(pestana=p):
                at = abrir("paginas/adherencia.py", **{"vista-adh": p, "f-dx": ["Desconocido/No revelado"]})
                self.assertEqual(problemas(at), [])


class TestSeguimientoAplicaciones(unittest.TestCase):
    SECCIONES = ["A · Reporte de aplicaciones", "B · Alertas de aplicaciones"]
    PBI = ["1 · Dosis aplicadas", "2 · Dosis programadas", "3 · Cumplimiento", "4 · Visor de pacientes"]
    EXCEL = ["1 · Programación", "2 · Cumplen", "3 · No cumplen y gestión", "4 · Reportes", "5 · Gestión y causas"]

    def test_cada_pestana_del_pbi(self):
        for p in self.PBI:
            for extra in ({}, {"ap-dx": []}, {"ver-identificacion": True}):
                with self.subTest(pestana=p, estado=extra):
                    at = abrir("paginas/aplicaciones.py", **{"apl-seccion": self.SECCIONES[0], "vista-apl": p, **extra})
                    self.assertEqual(problemas(at), [])

    def test_cada_hoja_del_excel(self):
        for p in self.EXCEL:
            for extra in ({}, {"ap-egreso": False}, {"ver-identificacion": True}):
                with self.subTest(hoja=p, estado=extra):
                    at = abrir("paginas/aplicaciones.py", **{"apl-seccion": self.SECCIONES[1], "vista-alertas": p, **extra})
                    self.assertEqual(problemas(at), [])

    def test_graficos_en_las_pestanas_del_pbi(self):
        for p in self.PBI[:3]:
            with self.subTest(pestana=p):
                at = abrir("paginas/aplicaciones.py", **{"apl-seccion": self.SECCIONES[0], "vista-apl": p})
                self.assertGreaterEqual(len(at.get("plotly_chart")), 5)


class TestTablero(unittest.TestCase):
    def test_cada_nivel(self):
        for n in NIVELES:
            with self.subTest(nivel=n):
                at = abrir(vista=n)
                self.assertEqual(problemas(at), [])


if __name__ == "__main__":
    unittest.main()
