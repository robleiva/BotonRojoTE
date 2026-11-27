"""Calibracion por percentiles: clases del indice segun el clima historico de la propia cuenca (sin necesitar incendios).

Se corre el mismo indice (FFMC + terreno de cada punto) sobre una serie larga de reanalisis (Open-Meteo, ERA5-Land)
y se fijan los cortes de clase como percentiles del puntaje en temporada de incendios:
Bajo < P50 | Moderado P50-P75 | Alto P75-P90 | Muy alto P90-P97 | Extremo >= P97.
Resultado: datos/calibracion_percentiles.json (lo lee fireindex al importarse).
"""
import datetime as dt
import json
import time

import numpy as np
import pandas as pd
import requests

from . import pipeline as pl
from .config import PUNTOS, ZONA

URL = "https://archive-api.open-meteo.com/v1/archive"
VARS = {"T": "temperature_2m", "RH": "relative_humidity_2m", "V": "wind_speed_10m", "DIR": "wind_direction_10m", "PP": "precipitation"}
PERCENTILES = (50, 75, 90, 97)
MESES_TEMPORADA = (10, 11, 12, 1, 2, 3, 4)
CABECERAS = {"User-Agent": "BotonRojoTE/0.3 (calibracion por percentiles, Tinguiririca Energia; uso interno)"}


def parsear(j):
    h = j.get("hourly", {})
    d = pd.DataFrame({"Fecha_Local": pd.to_datetime(h.get("time", []))})
    for k, v in VARS.items():
        d[k] = h.get(v, [np.nan] * len(d))
    return d, j.get("elevation", np.nan)


def descargar_punto(lat, lon, ini, fin, anios_por_llamada=3, espera=30, dormir=time.sleep):
    """Serie horaria [ini, fin] en tramos; reintenta ante HTTP 429. Devuelve (DataFrame, elevacion del modelo)."""
    trozos, elev = [], np.nan
    a = ini
    while a <= fin:
        b = min(dt.date(a.year + anios_por_llamada - 1, 12, 31), fin)
        params = {"latitude": lat, "longitude": lon, "start_date": a.isoformat(), "end_date": b.isoformat(),
                  "hourly": ",".join(VARS.values()), "timezone": ZONA, "wind_speed_unit": "kmh"}
        for intento in range(6):
            r = requests.get(URL, params=params, headers=CABECERAS, timeout=120)
            if r.status_code == 200:
                d, elev = parsear(r.json())
                trozos.append(d)
                break
            print(f"[calibracion] HTTP {r.status_code} en {a}..{b} (intento {intento + 1}/6)", flush=True)
            dormir(espera * (intento + 1))
        else:
            raise RuntimeError(f"Open-Meteo no respondio para {a}..{b}")
        a = b + dt.timedelta(days=1)
        dormir(2)
    return pd.concat(trozos, ignore_index=True), elev


def serie_indice(horario, elevacion, meta, terreno, f_ini=85.0):
    """Indice diario (a las 15:00) para un punto: [Fecha, Score]."""
    c = pl.clima_15h(horario)
    c["z_ref"] = elevacion
    c = pl.aplicar_altitud(c, elevacion, meta["alt"]) if np.isfinite(elevacion) else c
    res = pl.propagar(f_ini, c)
    filas = [pl.indice_fila(r, terreno)["Score"] for _, r in res.iterrows()]
    return pd.DataFrame({"Fecha": res["Fecha"], "Score": filas})


def cortes(scores, fechas, pct=PERCENTILES, meses=MESES_TEMPORADA):
    """Percentiles del puntaje en temporada de incendios, sobre un vector de puntajes con sus fechas."""
    s = pd.Series(np.asarray(scores, float), index=pd.to_datetime(fechas))
    s = s[s.index.month.isin(meses)].dropna()
    return [round(float(np.percentile(s, p)), 1) for p in pct], int(s.size)


def armar_resultado(series, periodo):
    """series: {punto: DataFrame[Fecha, Score]} -> dict listo para guardar."""
    todo = pd.concat(series.values())
    c, n = cortes(todo["Score"], todo["Fecha"])
    if not all(x < y for x, y in zip(c, c[1:])):
        raise ValueError(f"cortes no crecientes: {c}")
    return {"cortes": c, "percentiles": list(PERCENTILES), "periodo": periodo, "dias_temporada": n,
            "meses_temporada": list(MESES_TEMPORADA), "generado": dt.date.today().isoformat(),
            "fuente": "Open-Meteo archive (ERA5-Land / ERA5)", "por_punto": {p: cortes(d["Score"], d["Fecha"])[0] for p, d in series.items()}}
