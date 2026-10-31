"""Formularios de PRUEBA (datos sintéticos, ninguna persona real) para ensayar el pipeline como en producción.

Simula una cohorte de pacientes de retina desde 2020 (diagnóstico, inyecciones, consultas con agudeza visual,
OCT, encuestas de calidad de vida, sede y EAPB) y la corta en varias fechas: cada corte es una VERSIÓN del
formulario que trae todo lo registrado hasta ese día, como las entregas reales que crecen mes a mes.
Opcionalmente un corte trae faltantes y registros sin cruce, para ver cómo los detecta la completitud.

Cada versión queda como una entrega en  <DATA_ROOT>/raw/<prestador>/v<versión>_<corte>/  con su manifest:
el libro (7 hojas, incluida 'maestra_costos'), el resultado de calidad de vida y la tabla de costos.
Luego se procesa desde la app (página «Pipeline de datos» → «Reprocesar una entrega guardada») o con --procesar.

Uso:
    python tools/generar_formularios_prueba.py                       # 4 cortes, el 3.º con faltantes
    python tools/generar_formularios_prueba.py --cortes 2026-03-31 2026-09-30 --faltantes ninguno --procesar
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import config  # noqa: E402

INICIO, FIN = pd.Timestamp("2020-01-01"), pd.Timestamp("2026-09-30")
VERSION_FORMULARIO = "5.4.0"
DX = [("DMREn", "H353", 0.55), ("EMD", "H360", 0.30), ("OVR", "H348", 0.10), ("MNV", "H442", 0.05)]
MEDICAMENTOS = ["Aflibercept", "Ranibizumab", "Bevacizumab", "Faricimab"]   # código 1..4 = orden en la maestra de costos
# letras ETDRS -> denominador Snellen (inverso de config.SNELLEN_A_ETDRS, de 20/20 a 20/800; 0 letras = cuenta dedos)
LETRAS_A_SNELLEN = {letras: den for den, letras in config.SNELLEN_A_ETDRS.items() if 20 <= den <= 800}
LETRAS_A_SNELLEN[0] = 2000.0
ECV_DIMS = [k for k, _, _ in config.ECV_DIMENSIONES]


def _snellen(letras: float) -> float:
    paso = int(min(85, max(0, round(letras / 5) * 5)))
    return LETRAS_A_SNELLEN.get(paso, 2000.0)


def simular_cohorte(n_pacientes: int, rng: np.random.Generator) -> Dict[str, pd.DataFrame]:
    """La historia completa hasta FIN; los cortes se sacan después filtrando por fecha."""
    pac, lb, apl, cons, ayu, enc, prom = [], [], [], [], [], [], []
    dias_total = (FIN - pd.Timestamp("2026-08-31")).days
    for i in range(n_pacientes):
        doc = 9500001 + i
        dx, dx_cod, _ = DX[rng.choice(len(DX), p=[d[2] for d in DX])]
        edad = int(np.clip(rng.normal(70, 10), 40, 95))
        sexo = rng.choice(["Femenino", "Masculino"], p=[0.55, 0.45])
        pac.append({"id_paciente": i + 1, "fecha_dilig": None, "tipo_doc": "Cédula de ciudadanía", "numero_doc": doc,
                    "fecha_nac": pd.Timestamp("2026-01-01") - pd.Timedelta(days=int(edad * 365.25)), "edad": edad, "sexo": sexo,
                    "peso": round(float(rng.normal(70, 12)), 1), "talla": round(float(rng.normal(1.63, 0.08)), 2),
                    "eapb": f"EAPB {rng.choice(list('ABCDE'))}", "regimen": rng.choice(["Contributivo", "Subsidiado"], p=[0.7, 0.3]),
                    "sede": rng.choice(["Sede 1", "Sede 2", "Sede 3"], p=[0.5, 0.3, 0.2]),
                    "estatus_fumar": rng.choice(["Nunca", "Exfumador", "Actual"], p=[0.6, 0.3, 0.1]),
                    "ant_diabetes": int(dx == "EMD" or rng.random() < 0.3), "ant_insulina": int(rng.random() < 0.15),
                    "ant_hta": int(rng.random() < 0.55), "ant_dislipidemia": int(rng.random() < 0.35),
                    "actividad_fisica": int(rng.random() < 0.4), "etnia": "Ninguna",
                    "hba1c": round(float(rng.normal(7.4, 1.1)), 1) if dx == "EMD" else None})
        pac[-1]["imc"] = round(pac[-1]["peso"] / pac[-1]["talla"] ** 2, 1)
        dx_fecha = INICIO + pd.Timedelta(days=int(rng.integers(0, (FIN - INICIO).days - dias_total)))
        pac[-1]["fecha_dilig"] = dx_fecha
        med = int(rng.integers(1, 5))
        for ojo in (["OD", "OI"] if rng.random() < 0.3 else [rng.choice(["OD", "OI"])]):
            _simular_ojo(doc, ojo, dx, dx_cod, med, dx_fecha, rng, lb, apl, cons, ayu)
        # Calidad de vida (por paciente): encuesta 1 al inicio y encuesta 2 un año después
        if rng.random() < 0.65:
            total1 = float(np.clip(rng.normal(72, 12), 20, 100))
            delta = float(rng.normal(5, 8))
            for n, (f, total) in enumerate(((dx_fecha + pd.Timedelta(days=int(rng.integers(5, 40))), total1),
                                            (dx_fecha + pd.Timedelta(days=int(rng.normal(400, 30))), np.clip(total1 + delta, 0, 100))), start=1):
                if f > FIN or (n == 2 and rng.random() < 0.25):
                    continue
                enc.append({"numero_doc": doc, "nro_encuesta": n, "fechaencuesta": f, "fecharegistro": f})
                prom.append({"numero_doc": doc, "nro_encuesta": n, "fechaencuesta": f, "Total_prom": round(float(total), 1),
                             **{f"{k}_prom": round(float(np.clip(total + rng.normal(0, 9), 0, 100)), 1) for k in ECV_DIMS}})
    return {"pacientes": pd.DataFrame(pac), "lineabase": pd.DataFrame(lb), "aplicaciones": pd.DataFrame(apl),
            "consultas": pd.DataFrame(cons), "ayudas": pd.DataFrame(ayu), "calidadvida": pd.DataFrame(enc), "_ecv": pd.DataFrame(prom)}


def _hallazgos_oct(rng: np.random.Generator) -> Dict[str, int]:
    """Hallazgos de la OCT que el pipeline lee en cada ayuda diagnóstica (además de grosor, IRF y SRF)."""
    return {c: int(rng.random() < p) for c, p in (("oct_quistes", .25), ("oct_hrfs", .2), ("oct_atrofia", .1), ("oct_fibrosis", .08))}


def _simular_ojo(doc, ojo, dx, dx_cod, med, dx_fecha, rng, lb, apl, cons, ayu) -> None:
    poj, por = f"{doc}{ojo}", f"{doc}{ojo}0"
    base = {"pacienteojoreingreso": por, "pacienteojo": poj, "tipo_doc": "Cédula de ciudadanía", "numero_doc": doc, "ojo": ojo, "reingreso": 0}
    letras0 = float(np.clip(rng.normal(48, 20), 0, 85))
    ganancia = float(rng.normal(9 if dx == "EMD" else 7, 8))
    grosor0, baja = float(rng.normal(470, 90)), float(np.clip(rng.normal(190, 60), 20, 400))
    fin_tto = min(FIN, dx_fecha + pd.Timedelta(days=int(rng.choice([rng.integers(90, 200), rng.integers(300, 1100)], p=[0.15, 0.85]))))
    primera = dx_fecha + pd.Timedelta(days=int(min(rng.gamma(2.2, 7), 90)))
    seco = rng.random() < 0.85

    def letras(f) -> float:
        t = (f - primera).days
        return letras0 + (ganancia * (1 - np.exp(-max(t, 0) / 60)) if t > 0 else 0) - 1.5 * max(t, 0) / 365 + rng.normal(0, 3)

    lb.append({"id_registro": len(lb) + 1, "fecha_registro": dx_fecha, **base, "medico": f"Médico {rng.integers(1, 9)}", "tipo_paciente": "Nuevo",
               "medicamento": med, "dx_fecha": dx_fecha, "dx_cod_ppal": dx_cod, "dx_ppal": dx, "av_num": _snellen(letras0),
               "av_cartilla": "Snellen", "av_tipo": "Corregida", "oct_equipo": "Cirrus",
               **{c: int(rng.random() < p) for c, p in (("oct_dep", .3), ("oct_irf", .85), ("oct_srf", .7), ("oct_hemorragia", .1))},
               "egreso_fecha": pd.NaT, "egreso_causa": None})
    # Consulta de línea base y OCT inicial
    cons.append({**base, "tipo_consulta": "Retina", "fecha_consulta": dx_fecha, "agu_vis": _snellen(letras0), "endoftalmitis": 0, "dx_ppal": dx})
    ayu.append({**base, "tipo_ayuda": "OCT", "fecha_ayuda": dx_fecha, "oct": round(grosor0), "oct_irf": 1, "oct_srf": int(rng.random() < .7),
                "oct_dep": int(rng.random() < .3), "oct_hemorragia": int(rng.random() < .1), **_hallazgos_oct(rng)})
    # Inyecciones: carga mensual (3) y luego tratar y extender (8 a 16 semanas); la fecha real se desvía de la programada
    fecha, n, molecula, intervalo = primera, 0, med, 4
    while fecha <= fin_tto:
        n += 1
        if n == 7 and rng.random() < 0.1:
            molecula = int(rng.integers(1, 5))
        intervalo = 4 if n < 3 else int(min(16, max(6, intervalo + rng.choice([-2, 0, 2, 2]))) if n > 3 else 8)
        programada = fecha + pd.Timedelta(weeks=intervalo)
        apl.append({**base, "tipo_tto": "Aplicación intravítrea", "con_dosis": n, "fecha_aplicacion": fecha, "molecula": molecula,
                    "semana_extension": intervalo, "fecha_programacion": programada, "dx_ppal": dx_cod, "dx_ppal_desc": dx})
        cons.append({**base, "tipo_consulta": "Retina", "fecha_consulta": fecha, "agu_vis": _snellen(letras(fecha)),
                     "endoftalmitis": int(rng.random() < 0.003), "dx_ppal": dx})
        desvio = rng.choice([rng.integers(-7, 8), rng.integers(11, 31), rng.integers(31, 75)], p=[0.8, 0.12, 0.08])
        fecha = programada + pd.Timedelta(days=int(desvio))
    # OCT de control en las semanas del tablero (± unos días) y alguna consulta de oftalmología general
    for semanas in (12, 16, 20, 52, 104):
        f = primera + pd.Timedelta(days=semanas * 7 + int(rng.integers(-10, 11)))
        if f > fin_tto:
            break
        humedo = not seco and rng.random() < 0.6
        ayu.append({**base, "tipo_ayuda": "OCT", "fecha_ayuda": f, "oct": round(grosor0 - baja * (1 - np.exp(-semanas / 6)) + rng.normal(0, 15)),
                    "oct_irf": int(humedo), "oct_srf": int(humedo and rng.random() < .5), "oct_dep": int(rng.random() < .2), "oct_hemorragia": 0, **_hallazgos_oct(rng)})
        if rng.random() < 0.08:
            cons.append({**base, "tipo_consulta": "Oftalmología", "fecha_consulta": f, "agu_vis": _snellen(letras(f)), "endoftalmitis": 0, "dx_ppal": dx})
    if fin_tto < FIN:
        lb[-1]["egreso_fecha"], lb[-1]["egreso_causa"] = fin_tto, "Inactividad por no control de retina"


def maestra_costos() -> pd.DataFrame:
    filas = [("Tipo de tratamiento", "Aplicación intravítrea", 350000)] + \
            [("Medicamentos", m, c) for m, c in zip(MEDICAMENTOS, (1900000, 1500000, 250000, 2300000))] + \
            [("Consultas", "Retina", 120000), ("Consultas", "Oftalmología", 80000), ("Tipo de ayuda", "OCT", 180000), ("Tipo de ayuda", "Otros", 90000)]
    return pd.DataFrame(filas, columns=["Grupo", "Describe", "Costo promedio unitario"])


def cortar(cohorte: Dict[str, pd.DataFrame], corte: pd.Timestamp) -> Dict[str, pd.DataFrame]:
    """Lo que el prestador habría registrado hasta `corte`."""
    lb = cohorte["lineabase"][cohorte["lineabase"]["dx_fecha"] <= corte].copy()
    lb["egreso_fecha"] = pd.to_datetime(lb["egreso_fecha"])
    posterior = lb["egreso_fecha"] > corte          # a la fecha del corte ese egreso todavía no había ocurrido
    lb.loc[posterior, "egreso_fecha"], lb.loc[posterior, "egreso_causa"] = pd.NaT, None
    ojos, docs = set(lb["pacienteojoreingreso"]), set(lb["numero_doc"])
    out = {"pacientes": cohorte["pacientes"][cohorte["pacientes"]["numero_doc"].isin(docs)].copy(), "lineabase": lb}
    for hoja, col in (("aplicaciones", "fecha_aplicacion"), ("consultas", "fecha_consulta"), ("ayudas", "fecha_ayuda")):
        d = cohorte[hoja]
        out[hoja] = d[d["pacienteojoreingreso"].isin(ojos) & (d[col] <= corte)].copy()
    for hoja in ("calidadvida", "_ecv"):
        d = cohorte[hoja]
        out[hoja] = d[d["numero_doc"].isin(docs) & (d["fechaencuesta"] <= corte)].copy()
    return out


def degradar(hojas: Dict[str, pd.DataFrame], rng: np.random.Generator) -> List[str]:
    """Faltantes y registros sin cruce típicos de una entrega real. Devuelve la lista de lo que se dañó."""
    def vaciar(hoja, col, frac):
        d = hojas[hoja]
        idx = d.sample(frac=frac, random_state=int(rng.integers(1e9))).index
        d[col] = d[col].astype(object)
        d.loc[idx, col] = None
        return f"{hoja}.{col}: {len(idx)} celdas vacías ({frac:.0%})"
    notas = [vaciar("consultas", "agu_vis", .08), vaciar("aplicaciones", "fecha_programacion", .15),
             vaciar("pacientes", "eapb", .05), vaciar("pacientes", "sede", .05), vaciar("ayudas", "oct_srf", .1)]
    huerfanas = hojas["aplicaciones"].sample(20, random_state=int(rng.integers(1e9))).copy()
    huerfanas["pacienteojoreingreso"] = [f"99{i:05d}OD0" for i in range(len(huerfanas))]
    hojas["aplicaciones"] = pd.concat([hojas["aplicaciones"], huerfanas], ignore_index=True)
    notas.append("aplicaciones: 20 registros de paciente-ojo que no existen en la línea base")
    return notas


def escribir_entrega(hojas: Dict[str, pd.DataFrame], corte: pd.Timestamp, prestador: str, raiz: Path, notas: List[str], semilla: int) -> Path:
    carpeta = raiz / "raw" / prestador / f"v{VERSION_FORMULARIO}_{corte:%Y-%m-%d}"
    carpeta.mkdir(parents=True, exist_ok=True)
    libro = f"Formulario_prueba_{corte:%Y-%m-%d}.xlsx"
    with pd.ExcelWriter(carpeta / libro) as w:
        for hoja in config.HOJAS_REQUERIDAS:
            (maestra_costos() if hoja == "maestra_costos" else hojas[hoja]).to_excel(w, sheet_name=hoja, index=False)
    hojas["_ecv"].to_excel(carpeta / "ecv_prom_dimensiones.xlsx", index=False)
    manifest = {
        "prestador": prestador, "version_formulario": VERSION_FORMULARIO, "fecha_recepcion": f"{corte:%Y-%m-%d}",
        "cargado_por": "Generador de formularios de prueba", "cargado_en": f"{corte:%Y-%m-%d}T08:00:00",
        "formato": "formulario de prueba (tools/generar_formularios_prueba.py)",
        "archivos": {libro: {"descripcion": "libro del formulario (insumo principal)"},
                     "ecv_prom_dimensiones.xlsx": {"descripcion": "resultado de calidad de vida (ECV)"}},
        "filas_por_hoja": {h: int(len(hojas[h])) for h in config.HOJAS_REQUERIDAS if h in hojas} | {"maestra_costos": len(maestra_costos())},
        "costos_modo": "libro", "ecv_incluida": True, "es_demo": True, "sintetico": True, "semilla": semilla,
        "descripcion": f"Formulario de PRUEBA con corte al {corte:%Y-%m-%d}: datos sintéticos, sin personas reales.",
        "notas": notas or ["Sin faltantes provocados."],
    }
    (carpeta / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return carpeta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genera formularios de prueba (varias versiones por corte de fecha)")
    ap.add_argument("--prestador", default="prueba")
    ap.add_argument("--pacientes", type=int, default=400)
    ap.add_argument("--cortes", nargs="+", default=["2025-06-30", "2025-12-31", "2026-06-30", "2026-09-30"])
    ap.add_argument("--faltantes", default="2026-06-30", help="corte que trae faltantes y registros sin cruce ('ninguno' para omitir)")
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--raiz", type=Path, default=config.DATA_ROOT)
    ap.add_argument("--procesar", action="store_true", help="además corre el pipeline sobre cada versión")
    args = ap.parse_args(argv)
    rng = np.random.default_rng(args.semilla)
    cohorte = simular_cohorte(args.pacientes, rng)
    for c in sorted(args.cortes):
        corte = pd.Timestamp(c)
        hojas = cortar(cohorte, corte)
        notas = degradar(hojas, np.random.default_rng(args.semilla + 1)) if c == args.faltantes else []
        carpeta = escribir_entrega(hojas, corte, args.prestador, Path(args.raiz), notas, args.semilla)
        print(f"{carpeta.name}: " + ", ".join(f"{h} {len(hojas[h])}" for h in config.HOJAS_REQUERIDAS if h in hojas) + (" · CON FALTANTES" if notas else ""))
        if args.procesar:
            from pipeline import ingest
            destino = ingest.reprocesar(carpeta, raiz=Path(args.raiz), usuario="Generador de formularios de prueba")
            print(f"   procesada -> {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
