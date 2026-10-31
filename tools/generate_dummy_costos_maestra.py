"""Genera una tabla DUMMY de costo unitario por año (2020-2026) para TODOS los conceptos de
costo que usa el proceso (los mismos "puntos" que pidió el experto: tipo de tratamiento,
medicamentos, consultas, ayudas diagnósticas y encuesta de calidad de vida).

No son costos reales: son números aleatorios para poder construir y probar la lógica de
costeo por año mientras se define/consigue la tabla de costos oficial (ver
data/reference/README.md). Reemplaza a costos_medicamentos_DUMMY.xlsx (que solo cubría
medicamentos) por una tabla con el mismo catálogo que trae la hoja "maestra_costos" del
formulario (BaseDatos, Menu, Grupo, Describe), repetido para cada año.

Uso:
    python tools/generate_dummy_costos_maestra.py [--seed 42]

La semilla fija (42 por defecto) hace la tabla reproducible: volver a correr el script sin
cambiar los parámetros da exactamente los mismos números. Cambie --seed si quiere otra muestra.
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DESTINO = ROOT / "data" / "reference" / "maestra_costos_por_anio_DUMMY.xlsx"
ANIOS = list(range(2020, 2027))  # 2020 a 2026 inclusive

# Mismo catálogo que la hoja "maestra_costos" del formulario (BaseDatos, Menu, Grupo, Describe),
# visto igual en las entregas de P1 y de otro prestador. (min, max) en COP: solo para que el número
# inventado quede en un orden de magnitud parecido al de cada concepto; no viene de ninguna
# fuente real.
CATALOGO = [
    # BaseDatos,        Menu,                   Grupo,                  Describe,                 (min, max)
    ("Visitaclinica", "Procedimientos",       "Tipo de tratamiento", "Aplicación intravítrea", (250_000, 500_000)),
    ("Visitaclinica", "Procedimientos",       "Tipo de tratamiento", "Esteroide intravítreo",  (200_000, 700_000)),
    ("Visitaclinica", "Procedimientos",       "Tipo de tratamiento", "Fotocoagulación",        (300_000, 900_000)),
    ("Visitaclinica", "Procedimientos",       "Tipo de tratamiento", "Cirugía de retina",      (1_800_000, 5_000_000)),
    ("Visitaclinica", "Procedimientos",       "Tipo de tratamiento", "Capsulotomía",           (300_000, 900_000)),
    ("Visitaclinica", "Procedimientos",       "Tipo de tratamiento", "CxCatarata",             (500_000, 1_600_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Aflibercept",            (200_000, 3_000_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Ranibizumab",            (200_000, 3_000_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Bevacizumab",            (200_000, 3_000_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Brolucizumab",           (200_000, 3_000_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Faricimab",              (200_000, 3_000_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Dexametasona",           (200_000, 3_000_000)),
    ("Visitaclinica", "Procedimientos",       "Medicamentos",         "Aflibercept 8",          (200_000, 3_000_000)),
    ("Visitaclinica", "Consultas",            "Consultas",            "Retina",                 (20_000, 100_000)),
    ("Visitaclinica", "Consultas",            "Consultas",            "Oftalmología",           (20_000, 100_000)),
    ("Visitaclinica", "Consultas",            "Consultas",            "Optometría",             (20_000, 100_000)),
    ("Visitaclinica", "Consultas",            "Consultas",            "Otros",                  (20_000, 100_000)),
    ("Visitaclinica", "Ayudas diagnósticas",  "Tipo de ayuda",        "OCT",                    (50_000, 250_000)),
    ("Visitaclinica", "Ayudas diagnósticas",  "Tipo de ayuda",        "Angiografía",             (50_000, 250_000)),
    ("Visitaclinica", "Ayudas diagnósticas",  "Tipo de ayuda",        "Fondo de ojo",            (50_000, 250_000)),
    ("Visitaclinica", "Ayudas diagnósticas",  "Tipo de ayuda",        "Otros",                   (50_000, 250_000)),
    ("Calidad de vida", "ECV",                "Aplicación encuesta",  "Aplicación encuesta",     (5_000, 30_000)),
]


def generar(seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    filas = []
    for base_datos, menu, grupo, describe, (minimo, maximo) in CATALOGO:
        for anio in ANIOS:
            costo = rng.randint(minimo // 5_000, maximo // 5_000) * 5_000
            filas.append({
                "BaseDatos": base_datos, "Menu": menu, "Grupo": grupo, "Describe": describe,
                "Año": anio, "Costo promedio unitario": costo,
            })
    df = pd.DataFrame(filas)
    df["moneda"] = "COP"
    df["es_dummy"] = True
    df["fuente"] = "DUMMY -- costo inventado (aleatorio), NO usar en reportes ni decisiones reales"
    df["semilla_aleatoria"] = seed
    df["generado_en"] = datetime.now().isoformat(timespec="seconds")
    return df


def guardar(df: pd.DataFrame, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    aviso = pd.DataFrame([{"": "*** TABLA DE COSTOS FICTICIA (DUMMY) -- valores aleatorios, no reales -- "
                              "cubre todos los conceptos de costo del proceso (tipo de tratamiento, "
                              "medicamentos, consultas, ayudas diagnósticas y ECV), por año 2020-2026 ***"}])
    with pd.ExcelWriter(destino, engine="openpyxl") as w:
        aviso.to_excel(w, sheet_name="DUMMY-leer primero", index=False, header=False)
        # Nombre de hoja "maestra_costos": el pipeline la lee igual que la hoja del formulario.
        df.to_excel(w, sheet_name="maestra_costos", index=False)
    df.to_csv(destino.with_suffix(".csv"), index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DESTINO)
    args = ap.parse_args()

    df = generar(args.seed)
    guardar(df, args.out)
    print(f"Generado {args.out} y {args.out.with_suffix('.csv')} -- {len(df)} filas "
          f"({len(CATALOGO)} conceptos x {len(ANIOS)} años), semilla={args.seed}")
    print(df.pivot(index=["Grupo", "Describe"], columns="Año", values="Costo promedio unitario").to_string())


if __name__ == "__main__":
    main()
