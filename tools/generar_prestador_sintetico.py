"""Genera un prestador SINTÉTICO con la mejor calidad de datos posible, para mostrar cómo se vería el tablero
cuando el insumo traiga todo lo que hoy falta (líquido intra y subretiniano, OCT completo, fecha de programación,
agudeza visual en cada visita, segunda encuesta de calidad de vida).

No contiene datos reales de ninguna persona: documentos desde 9.000.001, nombres genéricos y todo simulado con una
semilla fija (misma semilla = mismo conjunto de datos).  El libro resultante tiene las mismas hojas y columnas que el
formulario real, así que pasa por la misma carga y los mismos cálculos que un insumo verdadero.

Relaciones clínicas simuladas (para que los indicadores se comporten con sentido, no al azar):
  * cada paciente-ojo tiene una "respuesta" latente: a mayor respuesta, mayor ganancia de letras y menos líquido;
  * el líquido (IRF/SRF) baja con las inyecciones; sin líquido ("retina seca") el intervalo se extiende (treat & extend);
  * el espesor OCT cae hacia ~270 µm y sube cuando hay líquido;
  * la calidad de vida (ECV) mejora más en quienes ganan más letras;
  * la fecha programada de cada dosis existe siempre y la aplicación real la cumple ~70 % de las veces dentro de ±10 días;
  * la AV inicial tiene la forma de P1 (cuartiles ~30 / 50 / 65 letras) y quien tiene AV a S104 siempre tiene también AV a S52.

Uso:
    python tools/generar_prestador_sintetico.py [--seed 2026] [--pacientes 900] [--registrar]
Sin --registrar solo escribe los archivos en data/reference/sintetico/ ; con --registrar los carga como prestador p2.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CORTE = pd.Timestamp("2026-08-31")                 # fecha de corte del insumo
INICIO_MIN, INICIO_MAX = pd.Timestamp("2020-06-01"), pd.Timestamp("2024-10-31")
DX = [("DMREn", "H353", 0.52), ("EMD", "H360", 0.26), ("OVR", "H348", 0.13), ("MNV", "H442", 0.07), ("Desconocido/No revelado", "H360", 0.02)]
DX_EFECTO = {"DMREn": 0.0, "EMD": -0.5, "OVR": -1.5, "MNV": 1.0, "Desconocido/No revelado": -1.0}
MED_EFECTO = {1: 1.5, 2: 0.0, 3: 2.5, 4: -0.5}     # efecto sobre la ganancia de letras por medicamento (códigos 1-4, como el prestador base)
DENOMINADORES = np.array([20, 25, 30, 40, 50, 60, 70, 80, 100, 125, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 2000], float)
TIPO_DOC = "Cédula de ciudadanía"
SEDES, SEDES_P = ["Sede 1", "Sede 2", "Sede 3"], [.5, .3, .2]   # para poder probar el filtro de sede


# Desnivel de cada dimensión respecto al total (a partir del perfil observado en P1) y cuánto responde al cambio de AV.
DIM_OFFSET = {"Conducir": 2.0, "Funcion_Social": 5.0, "Vision_Cercana": -1.0, "Vision_Color": 13.0, "Vision_Lejana": 1.5,
              "Vision_periferica": 3.0, "Bienestar_Sufrimiento": -5.0, "Dolor_Ocular": 10.0, "Vision_General": -12.0,
              "Dependencia": -13.0, "Limitaciones_Rol": 0.0}
DIM_EFECTO = {"Conducir": 0.5, "Funcion_Social": 0.8, "Vision_Cercana": 2.5, "Vision_Color": 0.0, "Vision_Lejana": 2.0,
              "Vision_periferica": 1.2, "Bienestar_Sufrimiento": 1.2, "Dolor_Ocular": 0.3, "Vision_General": 2.8,
              "Dependencia": 2.4, "Limitaciones_Rol": 1.8}


# Número total de aplicaciones por paciente-ojo-reingreso: masa en 1, 2 y 3 dosis y cola larga (forma tomada de P1:
# ~17 % con una sola dosis, ~36 % con tres, y una minoría que llega a 10 o más). Cada valor es el total de la hoja `aplicaciones`.
NDOSIS = {1: .16, 2: .13, 3: .26, 4: .09, 5: .07, 6: .08, 7: .045, 8: .035, 9: .03, 10: .025, 11: .02, 12: .015, 13: .012, 14: .01,
          15: .008, 16: .006, 18: .005, 20: .004, 24: .003}
_NDOSIS_V = np.array(list(NDOSIS))
_NDOSIS_P = np.array(list(NDOSIS.values())) / sum(NDOSIS.values())


def letras_a_denominador(letras: float) -> float:
    """Letras ETDRS -> denominador Snellen más cercano (20/x), con la misma fórmula inversa que usa el proceso."""
    ideal = 20 * 10 ** ((85 - letras) / 50)
    return float(DENOMINADORES[np.abs(np.log(DENOMINADORES) - np.log(ideal)).argmin()])


def _sigmoide_t(t: float, escala: float) -> float:
    return 1 - np.exp(-t / escala)


def _ajustar_estructura(hojas: Dict[str, pd.DataFrame], rng: np.random.Generator) -> Dict[str, pd.DataFrame]:
    """Deja cada hoja con las MISMAS columnas, en el mismo orden, que el formulario real (tools/estructura_formulario.json):
    completa las llaves auxiliares (pac_ojo_*), deja vacías las que el formulario trae vacías y responde las 27 preguntas
    de calidad de vida con el vocabulario real, de forma coherente con el puntaje del paciente."""
    est = json.loads((ROOT / "tools" / "estructura_formulario.json").read_text(encoding="utf-8"))
    ap, co, ay, cv = hojas["aplicaciones"], hojas["consultas"], hojas["ayudas"], hojas["calidadvida"]
    f = lambda s: pd.to_datetime(s).dt.strftime("%Y-%m-%d 00:00:00")   # noqa: E731
    ap["pac_ojo_rei_tto_consec"] = ap["pacienteojoreingreso"] + ap["tipo_tto"] + ap["con_dosis"].astype(str)
    ap["pac_ojo_tto_fecha"] = ap["pacienteojo"] + ap["tipo_tto"] + f(ap["fecha_aplicacion"])
    co["pac_ojo_consulta_fecha"] = co["pacienteojo"] + co["tipo_consulta"] + f(co["fecha_consulta"])
    co["pac_ojo_rei_consulta"] = co["pacienteojoreingreso"] + co["tipo_consulta"]
    co["pac_ojo_rei_consulta_consec"] = co["pac_ojo_rei_consulta"] + co["con_consulta"].astype(str)
    ay["pac_ojo_ayuda_fecha"] = ay["pacienteojo"] + ay["tipo_ayuda"] + f(ay["fecha_ayuda"])
    ay["pac_ojo_rei_ayuda"] = ay["pacienteojoreingreso"] + ay["tipo_ayuda"]
    ay["pac_ojo_rei_ayuda_consec"] = ay["pac_ojo_rei_ayuda"] + ay["con_ayuda"].astype(str)
    # preguntas NEI VFQ-25: la opción cuyo puntaje real se acerca más al del paciente (con ruido)
    for i in range(1, 28):
        opciones = [(t, sc) for t, sc in est["vocabulario_calidadvida"].get(f"preg{i}", []) if sc is not None and sc == sc]
        vistos, unicas = set(), []
        for t, sc in opciones:
            if sc not in vistos:
                vistos.add(sc); unicas.append((t, sc))
        if i in (17, 18) or not unicas:
            cv[f"preg{i}"] = np.nan                        # se contestan solo si conducen; aquí se dejan vacías
            continue
        objetivo = np.clip(cv["_p"].to_numpy() + rng.normal(0, 14, len(cv)), 0, 100)
        cv[f"preg{i}"] = [min(unicas, key=lambda o: abs(o[1] - x))[0] for x in objetivo]
    voc = est["vocabulario_calidadvida"]
    op15, op16 = [t for t, _ in voc["preg15"]], [t for t, _ in voc["preg16"]]
    cv["preg14"] = np.where(rng.random(len(cv)) < 0.3, "Si", "No")
    cv["preg15"] = np.where(cv["preg14"] == "No", rng.choice(op15, len(cv)), None)
    cv["preg16"] = np.where(cv["preg15"] == op15[0], rng.choice(op16, len(cv)), None)
    hojas["calidadvida"] = cv.drop(columns=["_p"])
    for nombre, columnas in est["hojas"].items():       # mismas columnas y orden que el formulario; lo que no se simula, vacío
        hojas[nombre] = hojas[nombre].reindex(columns=columnas)
    return hojas


def construir(seed: int = 2026, n_pacientes: int = 900) -> Dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    rng_rein = np.random.default_rng(seed + 3)    # flujo aparte para los reingresos
    rng_cond = np.random.default_rng(seed + 1)   # flujo aparte: no altera lo demás
    rng_s52 = np.random.default_rng(seed + 4)    # flujo aparte para la fecha de la visita a S52 añadida
    rng_sede = np.random.default_rng(seed + 5)   # flujo aparte para la sede (31-oct-2026): no altera ningún otro dato
    pac, lb, ap, co, ay, cv, ecv = [], [], [], [], [], [], []
    ids = {"lb": 0, "ap": 0, "co": 0, "ay": 0, "cv": 0}
    dx_names, dx_cods, dx_p = zip(*DX)
    medicos = [f"Médico {i}" for i in range(1, 7)]
    eapbs = ["EAPB A", "EAPB B", "EAPB C", "EAPB D", "EAPB E"]

    for i in range(n_pacientes):
        doc = 9_000_001 + i
        edad = int(np.clip(rng.normal(66, 9), 38, 92))
        sexo = "Femenino" if rng.random() < 0.55 else "Masculino"
        dx_pac = rng.choice(len(DX), p=dx_p)
        f_dx = INICIO_MIN + pd.Timedelta(days=int(rng.integers(0, (INICIO_MAX - INICIO_MIN).days)))
        pac.append(dict(id_paciente=i + 1, fecha_dilig=f_dx, tipo_doc=TIPO_DOC, numero_doc=doc, nombres="Sintético", apellidos=f"Paciente {i + 1:04d}",
                        fecha_nac=f_dx - pd.Timedelta(days=edad * 365), edad=edad, sexo=sexo, peso=round(rng.normal(74, 12), 1),
                        talla=round(rng.normal(165, 9), 1), imc=round(rng.normal(27, 4), 1), eapb=rng.choice(eapbs), regimen="Contributivo",
                        sede=str(rng_sede.choice(SEDES, p=SEDES_P)), estatus_fumar=rng.choice(["Nunca he fumado", "Exfumador", "Fumador actual"], p=[.62, .28, .10]),
                        ant_diabetes=1 if DX[dx_pac][0] in ("DMREn", "EMD") else int(rng.random() < .3), ant_insulina=int(rng.random() < .25),
                        ant_hta=int(rng.random() < .62), ant_dislipidemia=int(rng.random() < .45), actividad_fisica=int(rng.random() < .4),
                        etnia="Mestizo", fecha_dx_dm=f_dx - pd.Timedelta(days=int(rng.integers(365, 365 * 18))), años_dm=int(rng.integers(1, 20)),
                        hba1c=round(float(np.clip(rng.normal(7.4, 1.2), 5.2, 12)), 1)))

        ojos = ["OD", "OI"] if rng.random() < 0.40 else [rng.choice(["OD", "OI"])]
        ganancias_ojos = []
        # episodios por ojo: ingreso y, en ~20 % de los casos, reingresos (el prestador cierra el episodio tras 6 meses sin inyección)
        episodios = []
        for ojo_ in ojos:
            episodios.append((ojo_, 0))
            if rng_rein.random() < 0.20:
                episodios.append((ojo_, 1))
                if rng_rein.random() < 0.18:
                    episodios.append((ojo_, 2))
        fin_previo: Dict[str, pd.Timestamp] = {}
        for j, (ojo, reingreso) in enumerate(episodios):
            dx_idx = dx_pac if rng.random() < 0.85 else rng.choice(len(DX), p=dx_p)
            dx, cod = dx_names[dx_idx], dx_cods[dx_idx]
            clave = f"{doc}{ojo}{reingreso}"
            if reingreso:
                inicio = fin_previo[ojo] + pd.Timedelta(days=int(rng_rein.integers(190, 600)))
                if inicio > CORTE - pd.Timedelta(days=60):
                    continue                                   # el reingreso caería fuera de la ventana de datos
            else:
                inicio = f_dx + pd.Timedelta(days=int(rng.integers(5, 40))) + (pd.Timedelta(days=int(rng.integers(0, 200))) if j else pd.Timedelta(0))
                if inicio > CORTE - pd.Timedelta(days=60):
                    inicio = CORTE - pd.Timedelta(days=int(rng.integers(60, 400)))
            f_dx_ojo = inicio - pd.Timedelta(days=int(min(rng.gamma(2.0, 9.0), 120)))
            med = int(rng.choice([1, 2, 3, 4], p=[.28, .22, .22, .28]))
            medico = rng.choice(medicos)

            # ----- respuesta latente y trayectoria de agudeza visual
            resp = float(np.clip(rng.normal(1.0, 0.38), 0.15, 1.8))
            resp_eff = min(resp, 1.5) / 1.5
            L0 = float(np.clip(rng.normal(52 if dx == "EMD" else 46, 27), 4, 85))   # forma de P1: cuartiles ~30 / 50 / 65 letras
            g16 = (resp - 0.45) * 11 + MED_EFECTO[med] + DX_EFECTO[dx] + rng.normal(0, 4.5)
            g52 = g16 * 0.95 + rng.normal(0, 4)
            g104 = g52 * 0.90 + rng.normal(-1.5, 5)
            if not reingreso:
                ganancias_ojos.append(g52)

            def av(t_sem: float) -> float:
                base = np.interp(t_sem, [0, 16, 52, 104], [L0, L0 + g16, L0 + g52, L0 + g104])
                return float(np.clip(base + rng.normal(0, 2.2), 5, 90))

            B = float(np.clip(rng.normal(440, 95), 250, 750))
            T = 265 + rng.normal(0, 28) + (55 if resp < 0.6 else 0)

            def examen(t_sem: float) -> Tuple[int, int, int, float]:
                # Respuesta anatómica rápida: con la dosis de carga la mayoría queda sin líquido hacia S16 (insumo de calidad óptima).
                liq = 0.78 + 0.22 * resp_eff
                p_irf = float(np.clip(0.88 - 1.02 * liq * _sigmoide_t(t_sem, 5), 0.03, 0.92))
                p_srf = float(np.clip(0.62 - 0.62 * liq * _sigmoide_t(t_sem, 5), 0.02, 0.70))
                irf, srf = int(rng.random() < p_irf), int(rng.random() < p_srf)
                esp = T + (B - T) * np.exp(-t_sem / 10) + irf * 35 + srf * 25 + rng.normal(0, 14)
                return irf, srf, int(rng.random() < max(0.02, (0.35 if dx == "MNV" else 0.12) * np.exp(-t_sem / 12))), float(np.clip(esp, 150, 800))

            # ----- calendario treat & extend
            n_total = int(rng.choice(_NDOSIS_V, p=_NDOSIS_P))      # cuántas aplicaciones recibe en total (puede ser 1)
            fecha, intervalo, k, molecula = inicio, 4, 0, med
            int_max = int(rng_rein.choice([4, 6, 8, 12, 16], p=[.12, .13, .20, .22, .33]))   # hay pacientes que no se extienden (cola de más inyecciones)
            primera_ay = None
            filas_ap = []
            n_co0 = len(co)                                   # consultas de este episodio empiezan aquí
            # consulta + OCT basal
            f_base = inicio - pd.Timedelta(days=int(rng.integers(0, 10)))
            irf0, srf0, hem0, esp0 = examen(0)
            irf0, srf0 = max(irf0, int(rng.random() < .7)), max(srf0, int(rng.random() < .35))   # al inicio casi todos tienen líquido
            den0 = letras_a_denominador(L0)
            ids["co"] += 1
            co.append(dict(id_registro=ids["co"], fecha_registro=f_base, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                           numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_consulta="Retina", con_consulta=1, fecha_consulta=f_base,
                           agu_vis=den0, agu_vis_num=den0, av_tipo="Corregido", cod_dx_ppal=cod, dx_ppal=dx, medico=medico, endoftalmitis=0,
                           tipo_endoftalmitis="No Aplica", com_ambliopia=0, com_maculopatia=0, com_opa_med=0, com_glau_neu=0, com_evr=0))
            ids["ay"] += 1
            ay.append(dict(id_registro=ids["ay"], fecha_registro=f_base, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                           numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_ayuda="OCT", con_ayuda=1, fecha_ayuda=f_base, oct=round(esp0),
                           oct_dep=int(rng.random() < .08), oct_irf=irf0, oct_srf=srf0, oct_hemorragia=hem0, oct_quistes=int(irf0 and rng.random() < .5),
                           oct_hrfs=int(rng.random() < .3), oct_atrofia=int(rng.random() < .05), oct_fibrosis=int(rng.random() < .04)))

            ultima = inicio
            while True:
                k += 1
                t_sem = (fecha - inicio).days / 7
                irf, srf, hem, esp = examen(t_sem)
                seca = irf == 0 and srf == 0
                if k > 3 and rng.random() < 0.08:                      # cambio de molécula (~8 %)
                    molecula = int(rng.choice([m for m in (1, 2, 3, 4) if m != molecula]))
                if k < 3:
                    intervalo = 4
                elif k == 3:
                    intervalo = min(8, max(4, int_max))
                else:
                    intervalo = int(np.clip(intervalo + (2 if seca else (-2 if rng.random() < .5 else 0)), 4, max(4, int_max)))
                planeada = fecha + pd.Timedelta(days=7 * intervalo)
                u = rng.random()
                demora = 0 if u < .62 else (int(rng.integers(-7, 8)) if u < .78 else (int(rng.integers(11, 41)) if u < .95 else int(rng.integers(41, 91))))
                proxima = planeada + pd.Timedelta(days=demora)
                ids["ap"] += 1
                filas_ap.append(dict(id_registro=ids["ap"], fecha_registro=fecha, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                                     numero_doc=doc, ojo=ojo, pac_ojo_rei_tto=f"{clave}Aplicación intravítrea", reingreso=reingreso,
                                     tipo_tto="Aplicación intravítrea", con_dosis=k, fecha_aplicacion=fecha, esquema="Treat & extend",
                                     molecula=molecula, semana_extension=intervalo, fecha_programacion=planeada, medico=medico, dx_ppal=cod,
                                     dx_ppal_desc=dx, plan_pago="Plan 1"))
                # consulta de control con AV y OCT el mismo día de la aplicación
                den = letras_a_denominador(av(t_sem))
                endo = 1 if (k > 1 and rng.random() < 0.0015) else 0
                ids["co"] += 1
                co.append(dict(id_registro=ids["co"], fecha_registro=fecha, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                               numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_consulta="Retina", con_consulta=k + 1, fecha_consulta=fecha,
                               agu_vis=den, agu_vis_num=den, av_tipo="Corregido", cod_dx_ppal=cod, dx_ppal=dx, medico=medico, endoftalmitis=endo,
                               tipo_endoftalmitis="Endoftalmitis infecciosa" if endo else "No Aplica", com_ambliopia=0, com_maculopatia=0,
                               com_opa_med=0, com_glau_neu=0, com_evr=0))
                if rng.random() < 0.97:
                    ids["ay"] += 1
                    ay.append(dict(id_registro=ids["ay"], fecha_registro=fecha, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                                   numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_ayuda="OCT", con_ayuda=k + 1, fecha_ayuda=fecha, oct=round(esp),
                                   oct_dep=int(rng.random() < .05), oct_irf=irf, oct_srf=srf, oct_hemorragia=hem, oct_quistes=int(irf and rng.random() < .5),
                                   oct_hrfs=int(rng.random() < .3), oct_atrofia=int(rng.random() < .05 + t_sem / 600), oct_fibrosis=int(rng.random() < .04 + t_sem / 700)))
                ultima = fecha
                if k >= n_total or proxima > CORTE:
                    break
                fecha = proxima
            ap.extend(filas_ap)
            # controles sin inyección (consulta + OCT): quien deja de inyectar sigue en observación hacia S16, S52 y S104
            for sem_c in (16, 52, 104):
                f_c = inicio + pd.Timedelta(days=7 * sem_c + int(rng.integers(-14, 15)))
                if f_c > ultima + pd.Timedelta(days=21) and f_c < CORTE and rng.random() < 0.55:
                    t_c = (f_c - inicio).days / 7
                    irf_c, srf_c, hem_c, esp_c = examen(t_c)
                    ids["co"] += 1
                    co.append(dict(id_registro=ids["co"], fecha_registro=f_c, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                                   numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_consulta="Retina", con_consulta=50 + sem_c, fecha_consulta=f_c,
                                   agu_vis=letras_a_denominador(av(t_c)), agu_vis_num=letras_a_denominador(av(t_c)), av_tipo="Corregido", cod_dx_ppal=cod,
                                   dx_ppal=dx, medico=medico, endoftalmitis=0, tipo_endoftalmitis="No Aplica", com_ambliopia=0, com_maculopatia=0,
                                   com_opa_med=0, com_glau_neu=0, com_evr=0))
                    ids["ay"] += 1
                    ay.append(dict(id_registro=ids["ay"], fecha_registro=f_c, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                                   numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_ayuda="OCT", con_ayuda=50 + sem_c, fecha_ayuda=f_c, oct=round(esp_c),
                                   oct_dep=int(rng.random() < .05), oct_irf=irf_c, oct_srf=srf_c, oct_hemorragia=hem_c, oct_quistes=int(irf_c and rng.random() < .5),
                                   oct_hrfs=int(rng.random() < .3), oct_atrofia=int(rng.random() < .05 + t_c / 600), oct_fibrosis=int(rng.random() < .04 + t_c / 700)))
            # coherencia longitudinal: con AV a S104 debe haber AV a S52 (ventana ±28 d, la misma con que el proceso busca la visita)
            dias_visita = [(c_["fecha_consulta"] - inicio).days for c_ in co[n_co0:] if c_["tipo_consulta"] == "Retina"]
            if any(abs(d_ - 728) <= 28 for d_ in dias_visita) and not any(abs(d_ - 364) <= 28 for d_ in dias_visita):
                f_c = inicio + pd.Timedelta(days=364 + int(rng_s52.integers(-14, 15)))
                t_c = (f_c - inicio).days / 7
                irf_c, srf_c, hem_c, esp_c = examen(t_c)
                den_c = letras_a_denominador(av(t_c))
                ids["co"] += 1
                co.append(dict(id_registro=ids["co"], fecha_registro=f_c, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                               numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_consulta="Retina", con_consulta=50 + 52, fecha_consulta=f_c,
                               agu_vis=den_c, agu_vis_num=den_c, av_tipo="Corregido", cod_dx_ppal=cod, dx_ppal=dx, medico=medico, endoftalmitis=0,
                               tipo_endoftalmitis="No Aplica", com_ambliopia=0, com_maculopatia=0, com_opa_med=0, com_glau_neu=0, com_evr=0))
                ids["ay"] += 1
                ay.append(dict(id_registro=ids["ay"], fecha_registro=f_c, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                               numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_ayuda="OCT", con_ayuda=50 + 52, fecha_ayuda=f_c, oct=round(esp_c),
                               oct_dep=int(rng.random() < .05), oct_irf=irf_c, oct_srf=srf_c, oct_hemorragia=hem_c, oct_quistes=int(irf_c and rng.random() < .5),
                               oct_hrfs=int(rng.random() < .3), oct_atrofia=int(rng.random() < .05 + t_c / 600), oct_fibrosis=int(rng.random() < .04 + t_c / 700)))
            if rng.random() < 0.10:                                       # algunas consultas de oftalmología general
                f_of = inicio + pd.Timedelta(days=int(rng.integers(20, 300)))
                if f_of < CORTE:
                    ids["co"] += 1
                    co.append(dict(id_registro=ids["co"], fecha_registro=f_of, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                                   numero_doc=doc, ojo=ojo, reingreso=reingreso, tipo_consulta="Oftalmología", con_consulta=99, fecha_consulta=f_of,
                                   agu_vis=letras_a_denominador(av((f_of - inicio).days / 7)), agu_vis_num=np.nan, av_tipo="Corregido", cod_dx_ppal=cod,
                                   dx_ppal=dx, medico=medico, endoftalmitis=0, tipo_endoftalmitis="No Aplica", com_ambliopia=0, com_maculopatia=0,
                                   com_opa_med=0, com_glau_neu=0, com_evr=0))
            fin_previo[ojo] = ultima
            inactivo = (CORTE - ultima).days > 180 or (ojo, reingreso + 1) in episodios
            lb.append(dict(id_registro=len(lb) + 1, fecha_registro=f_dx_ojo, pacienteojoreingreso=clave, pacienteojo=f"{doc}{ojo}", tipo_doc=TIPO_DOC,
                           numero_doc=doc, ojo=ojo, medico=medico, tipo_paciente="Reingreso" if reingreso else "Nuevo", medicamento=med, reingreso=reingreso, dx_fecha=f_dx_ojo,
                           dx_cod_ppal=cod, dx_ppal=dx, av_agu_vis=den0, av_cartilla="Snellen", av_distancia=6, av_tipo="Corregido", oct_ecr=round(esp0),
                           oct_equipo="Equipo # 1", oct_dep=0, oct_irf=irf0, oct_srf=srf0, oct_hemorragia=hem0, oct_quistes=int(irf0 and rng.random() < .5),
                           oct_hrfs=int(rng.random() < .3), oct_atrofia=int(rng.random() < .05), oct_fibrosis=int(rng.random() < .04), com_opa_med=0,
                           com_ambliopia=0, com_maculopatia=0, com_glau_neu=0, com_evr=0,
                           egreso_fecha=ultima + pd.Timedelta(days=180) if inactivo else pd.NaT,
                           egreso_causa="Inactividad por no control de retina" if inactivo else None, av_num=den0))

        # ----- calidad de vida: encuesta basal para ~65 % y segunda a ~1 año para ~70 % de ellos
        if rng.random() < 0.65:
            g = float(np.mean(ganancias_ojos))
            base = float(np.clip(rng.normal(60, 12) + 15, 20, 98))   # nivel parecido al de P1 (~75)
            segunda = base + 2.0 + 0.30 * max(g, -10) + rng.normal(0, 5)
            f1 = f_dx + pd.Timedelta(days=int(rng.integers(0, 15)))
            enc = [(1, f1, base)]
            if rng.random() < 0.70 and f1 + pd.Timedelta(days=380) < CORTE:
                enc.append((2, f1 + pd.Timedelta(days=int(rng.integers(330, 400))), float(np.clip(segunda, 15, 100))))
            for nro, f, puntaje in enc:
                ids["cv"] += 1
                cv.append(dict(id_encuesta=ids["cv"], fecharegistro=f, encuestapac=f"{doc} - {nro}", fechaencuesta=f, tipo_doc=TIPO_DOC,
                               numero_doc=doc, nro_encuesta=nro, idencuestador=f"E{int(rng.integers(1, 6)):02d}", Costo=np.nan, _p=puntaje))
                fila = dict(id_encuesta=ids["cv"], numero_doc=doc, nro_encuesta=nro)
                # Dimensiones NEI VFQ-25: cada una parte del puntaje del paciente con el desnivel típico de esa
                # dimensión (p. ej. dependencia y visión general puntúan más bajo, color y dolor más alto) y mejora
                # más o menos entre encuestas. El ruido sale del mismo flujo aleatorio de siempre (no mueve el resto).
                dims = {}
                for dim in DIM_OFFSET:
                    ruido = float(rng.normal(0, 8))
                    if dim == "Conducir" and rng_cond.random() > 0.35:   # solo quien conduce responde conducción
                        continue
                    efecto = DIM_EFECTO[dim] * (g / 5.0 if nro == 2 else 0.0)
                    dims[dim] = round(float(np.clip(puntaje + DIM_OFFSET[dim] + efecto + ruido * 0.9, 0, 100)), 2)
                    fila[f"{dim}_prom"] = dims[dim]
                fila["Total_prom"] = round(float(np.mean(list(dims.values()))), 2)
                ecv.append(fila)

    # ----- hoja de costos (la misma referencia del proyecto, año 2025) y ensamblado
    ref = pd.read_excel(ROOT / "data" / "reference" / "maestra_costos_por_anio_DUMMY.xlsx", sheet_name="maestra_costos")
    maestra = ref[ref["Año"] == 2025][["BaseDatos", "Menu", "Grupo", "Describe", "Costo promedio unitario", "Año"]].assign(**{"Periodo costo": "Trimestre IV"})
    hojas = {"pacientes": pd.DataFrame(pac), "lineabase": pd.DataFrame(lb), "aplicaciones": pd.DataFrame(ap), "consultas": pd.DataFrame(co),
             "ayudas": pd.DataFrame(ay), "calidadvida": pd.DataFrame(cv), "maestra_costos": maestra.reset_index(drop=True)}
    hojas["_ecv"] = pd.DataFrame(ecv)
    return _ajustar_estructura(hojas, np.random.default_rng(seed + 2))


def a_bytes(hojas: Dict[str, pd.DataFrame]) -> Tuple[bytes, bytes]:
    libro = io.BytesIO()
    with pd.ExcelWriter(libro, engine="openpyxl") as w:
        for nombre, df in hojas.items():
            if not nombre.startswith("_"):
                df.to_excel(w, sheet_name=nombre, index=False)
        pd.DataFrame({"Nota": ["Datos SINTÉTICOS generados con tools/generar_prestador_sintetico.py (semilla fija). No corresponden a personas reales."]}
                     ).to_excel(w, sheet_name="DatosSinteticos", index=False)
    ecv = io.BytesIO()
    hojas["_ecv"].to_excel(ecv, index=False)
    return libro.getvalue(), ecv.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--pacientes", type=int, default=900)
    ap.add_argument("--version", default="5.4.0")
    ap.add_argument("--prestador", default="p2")
    ap.add_argument("--registrar", action="store_true", help="cargarlo en la carpeta de datos como un prestador más")
    args = ap.parse_args()

    hojas = construir(args.seed, args.pacientes)
    libro, ecv = a_bytes(hojas)
    print({k: len(v) for k, v in hojas.items()})
    if args.registrar:
        import sys
        sys.path.insert(0, str(ROOT))
        from pipeline import ingest
        res = ingest.registrar_entrega(
            prestador=args.prestador, version=args.version, usuario="Generador sintético", libro=libro, libro_nombre="Formulario_sintetico.xlsx",
            ecv=ecv, ecv_nombre="ecv_prom_dimensiones.xlsx", costos_modo="dummy", progreso=print,
            meta_extra={"es_demo": True, "sintetico": True, "semilla": args.seed,
                        "descripcion": "Datos sintéticos de calidad óptima (tools/generar_prestador_sintetico.py); sin personas reales."})
        print("Cargado:", res)
    else:
        destino = ROOT / "data" / "reference" / "sintetico"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "Formulario_sintetico.xlsx").write_bytes(libro)
        (destino / "ecv_prom_dimensiones.xlsx").write_bytes(ecv)
        print("Escrito en", destino)


if __name__ == "__main__":
    main()
