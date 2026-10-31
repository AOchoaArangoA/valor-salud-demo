"""Piezas compartidas por todas las páginas: estilos, «última actualización», fechas y pie de página."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st

import logic as L
from pipeline import registro

# El enrutador (app.py) deja aquí las páginas para que una página pueda llevar a otra con st.switch_page
PAGINAS: Dict[str, "st.Page"] = {}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

ESTILOS = """<style>
    .block-container {padding-top: 1.6rem; max-width: 1400px;}
    div[data-testid="stMetric"] {background:#fff; border:1px solid #E3E7ED; border-radius:10px; padding:8px 12px;}
    div[data-testid="stMetricValue"] {font-size:1.55rem;}
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *, [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {white-space: normal !important; overflow: visible !important; text-overflow: clip !important;}
    [data-testid="stMetricLabel"] p {line-height:1.15;}
    .nivel {border-left:6px solid var(--c); padding:2px 12px; margin:0 0 .6rem 0;}
    .nivel h3 {margin:0; color:var(--c);} .nivel p {margin:0; color:#5B6675;}
    .nd {color:#8A94A3; font-style:italic;}
    .dxn {display:inline-block; margin-right:22px; color:#33415C;} .dxn b {color:#1B2430;}
    .flujo {display:flex; align-items:stretch; gap:6px; margin:.4rem 0 1rem 0;}
    .etapa {flex:1; background:#fff; border:1px solid #E3E7ED; border-radius:12px; padding:10px 12px; text-align:center;}
    .etapa .num {color:#8A94A3; font-size:.75rem;} .etapa .tit {font-weight:700; letter-spacing:.04em; font-size:.8rem; color:#1B2430;}
    .etapa .val {font-size:1.45rem; font-weight:800; color:#1B2430; margin:.2rem 0;} .etapa .sub {color:#5B6675; font-size:.78rem;}
    .etapa .meta {color:#5B6675; font-size:.72rem; font-style:italic; margin-top:.25rem;}
    .flecha {align-self:center; color:#8A94A3; font-size:1.3rem;}
    </style>"""


def estilos() -> None:
    st.markdown(ESTILOS, unsafe_allow_html=True)


def fecha(iso: Optional[str], hora: bool = True) -> str:
    """'2026-10-27T21:28:19' -> '27-oct-2026 21:28'."""
    try:
        d = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return "—"
    return f"{d.day:02d}-{MESES[d.month - 1]}-{d.year}" + (f" {d:%H:%M}" if hora else "")


def ultima_actualizacion(corridas: Optional[List[Dict]] = None) -> Optional[Dict]:
    """La actualización de datos más reciente: la última ejecución exitosa de la bitácora o, si no hay bitácora
    (corridas anteriores a ella), la corrida generada más recientemente."""
    corridas = L.listar_corridas() if corridas is None else corridas
    candidatos = [{"cuando": c["generado"], "prestador": str(c["meta"].get("prestador", "")).upper(), "version": c["meta"].get("version"),
                   "por": c["meta"].get("cargado_por")} for c in corridas if c.get("generado")]
    candidatos += [{"cuando": r.get("fin") or r.get("inicio"), "prestador": str(r.get("prestador") or "").upper(), "version": r.get("version"),
                    "por": r.get("usuario")} for r in registro.leer() if r.get("estado") == "éxito"]
    return max(candidatos, key=lambda c: str(c["cuando"])) if candidatos else None


def aviso_actualizacion() -> None:
    """Va en la barra lateral de todas las páginas."""
    u = ultima_actualizacion()
    if u is None:
        st.sidebar.caption("Sin datos procesados todavía.")
        return
    detalle = " · ".join(x for x in (u["prestador"], f"v{u['version']}" if u.get("version") else "", u.get("por") or "") if x)
    st.sidebar.caption(f"Última actualización de datos: **{fecha(u['cuando'])}**" + (f"  \n{detalle}" if detalle else ""))


def pie() -> None:
    st.markdown('<div style="margin-top:2.5rem;padding-top:.8rem;border-top:1px solid #DDE2E8;text-align:center;color:#5B6675;font-size:.85rem">'
                'Proyecto Valor en Salud</div>', unsafe_allow_html=True)
