"""Correccion del viento del modelo con las estaciones propias.

El modelo (25 km) suele subestimar el viento de la tarde en el fondo del valle. Se compara, a las 15 h,
el viento medido en cada estacion con el del modelo (ECMWF, emision del mismo dia) y, con suficientes dias,
se multiplica el viento del modelo en ese punto por la razon mediana medido/modelo. El viento medido se lleva antes a 10 m
segun la altura del anemometro (config.ALTURA_ANEMOMETRO). La correccion representa el fondo del valle: se atenua con la distancia por la interpolacion. El efecto se extiende
a los demas puntos y celdas por la interpolacion normal del mapa. Sin dias suficientes no se corrige nada.
"""
import numpy as np
import pandas as pd

from . import pipeline as pl
from .config import ALTURA_ANEMOMETRO, ALTURA_ANEMOMETRO_DEFECTO

MIN_DIAS = 30            # dias con medicion y modelo para activar la correccion
VENTANA_DIAS = 60        # solo se usan los ultimos dias (la relacion cambia con la estacion del ano)
F_MIN, F_MAX = 0.7, 3.0  # limites del factor: una correccion extrema indica un problema de datos, no de modelo
V_MIN_MODELO = 1.0       # km/h: con viento de modelo casi nulo la razon no es estable y se descarta


def a_10m(v, altura_m):
    """Lleva el viento medido a `altura_m` hasta 10 m (perfil de potencia 1/7, terreno abierto)."""
    return np.asarray(v, float) * (10.0 / altura_m) ** (1.0 / 7.0)


def pares(obs, pron, punto, altura_m=None):
    """DataFrame [Fecha, obs, modelo] de un punto: viento a las 15 h de la estacion (llevado a 10 m) y del modelo ECMWF (lead 0)."""
    altura_m = ALTURA_ANEMOMETRO.get(punto, ALTURA_ANEMOMETRO_DEFECTO) if altura_m is None else altura_m
    if obs is None or obs.empty or pron is None or pron.empty:
        return pd.DataFrame(columns=["Fecha", "obs", "modelo"])
    o = pl.clima_15h(obs[obs["Punto"] == punto])
    if o.empty:
        return pd.DataFrame(columns=["Fecha", "obs", "modelo"])
    o = o.dropna(subset=["V"])[["Fecha", "V"]].rename(columns={"V": "obs"})
    o["obs"] = a_10m(o["obs"], altura_m)
    p = pron[(pron["Punto"] == punto) & (pron["Modelo"] == "ECMWF")].copy()
    p["Fecha"], p["Emision"] = pd.to_datetime(p["Fecha"]), pd.to_datetime(p["Emision"])
    p = p[p["Fecha"] == p["Emision"]][["Fecha", "V"]].rename(columns={"V": "modelo"})
    d = o.merge(p, on="Fecha").dropna()
    return d[d["modelo"] >= V_MIN_MODELO].sort_values("Fecha")


def factores(obs, pron, puntos, min_dias=MIN_DIAS, altura_m=None):
    """({punto: factor}, {punto: (dias, razon_mediana)}). Solo hay factor si el punto reune min_dias pares."""
    fac, info = {}, {}
    for pto in puntos:
        d = pares(obs, pron, pto, altura_m).tail(VENTANA_DIAS)
        if d.empty:
            continue
        razon = float(np.median(d["obs"] / d["modelo"]))
        info[pto] = (len(d), razon)
        if len(d) >= min_dias:
            fac[pto] = float(np.clip(razon, F_MIN, F_MAX))
    return fac, info


def aplicar(df, factores_por_punto):
    """Multiplica la columna V de las filas de modelo de cada punto con factor. No modifica el original."""
    d = df.copy()
    for pto, f in factores_por_punto.items():
        m = d["Punto"] == pto
        if "Fuente" in d:
            m &= d["Fuente"] != "ESTACION"
        d.loc[m, "V"] = d.loc[m, "V"] * f
    return d
