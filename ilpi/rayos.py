"""Posibilidad de tormenta electrica a partir de la inestabilidad atmosferica del modelo (CAPE e indice de elevacion).

No existe un pronostico abierto de rayos para Chile. Esto es una aproximacion: indica dias con atmosfera inestable
en la tarde, que es cuando se forman las tormentas de verano en la cordillera. NO es un pronostico de rayos ni esta calibrada.
Los umbrales son provisorios (practica general de pronostico convectivo) y deben ajustarse con rayos observados (GOES GLM).
"""
import numpy as np
import pandas as pd
import requests

from .config import ZONA

URL = "https://api.open-meteo.com/v1/forecast"
HORAS_TARDE = range(12, 21)       # ventana convectiva local: 12-20 h
POSIBLE_CAPE = 300.0              # J/kg
PROBABLE_CAPE = 800.0             # J/kg
PROBABLE_LI = -2.0                # indice de elevacion (K) o menor
NIVELES = ["Sin señal", "Posible", "Probable"]
COLS = ["Punto", "Fecha", "CAPE", "LI"]


def _serie(h, nombre, n):
    for k, v in h.items():
        if k.startswith(nombre) and v and any(x is not None for x in v):
            return np.array([np.nan if x is None else x for x in v], float)
    return np.full(n, np.nan)


def diaria(j):
    """JSON de Open-Meteo -> [Fecha, CAPE (maximo de la tarde), LI (minimo de la tarde)]."""
    h = j.get("hourly", {})
    t = pd.to_datetime(h.get("time", []))
    d = pd.DataFrame({"t": t, "CAPE": _serie(h, "cape", len(t)), "LI": _serie(h, "lifted_index", len(t))})
    d = d[d["t"].dt.hour.isin(HORAS_TARDE)]
    d["Fecha"] = d["t"].dt.normalize()
    return d.groupby("Fecha").agg(CAPE=("CAPE", "max"), LI=("LI", "min")).reset_index()


def fetch(lat, lon, past_days=2, forecast_days=4):
    vacio = pd.DataFrame(columns=["Fecha", "CAPE", "LI"])
    params = {"latitude": lat, "longitude": lon, "hourly": "cape,lifted_index", "timezone": ZONA,
              "past_days": past_days, "forecast_days": forecast_days}
    try:
        r = requests.get(URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[rayos] HTTP {r.status_code}")
            return vacio
        return diaria(r.json())
    except Exception as e:
        print(f"[rayos] {e}")
        return vacio


def nivel(cape, li):
    """0 sin senal, 1 posible, 2 probable. Sin CAPE no hay senal (ante la duda no se alerta)."""
    if not np.isfinite(cape):
        return 0
    if cape >= PROBABLE_CAPE and (not np.isfinite(li) or li <= PROBABLE_LI):
        return 2
    return 1 if cape >= POSIBLE_CAPE else 0


def por_dia(df, desde=None):
    """[Punto, Fecha, CAPE, LI] -> una fila por dia para toda la cuenca (el peor punto): [Fecha, CAPE, LI, Nivel]."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["Fecha", "CAPE", "LI", "Nivel"])
    g = df.copy()
    g["Fecha"] = pd.to_datetime(g["Fecha"])
    if desde is not None:
        g = g[g["Fecha"] >= pd.Timestamp(desde)]
    g = g.groupby("Fecha").agg(CAPE=("CAPE", "max"), LI=("LI", "min")).reset_index()
    g["Nivel"] = [nivel(c, l) for c, l in zip(g["CAPE"], g["LI"])]
    return g
