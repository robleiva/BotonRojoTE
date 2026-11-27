"""Nieve: cobertura aproximada a partir del modelo (profundidad de nieve y altura de la isoterma 0 C).

Regla (aproximada, ver README): una celda esta cubierta de nieve el dia D si
  1) la profundidad de nieve del modelo, promediada en los puntos, supera UMBRAL_M, y
  2) la celda esta sobre la cota de nieve: la menor altura de la isoterma 0 C de los ultimos
     VENTANA_DIAS dias (incluido D) menos DESCUENTO_M.
Donde hay nieve el peligro es 0 y la celda no se colorea. Si falta el dato, la nieve no se considera:
ante la duda no se apaga el peligro.
"""
import numpy as np
import pandas as pd
import requests

from .config import ZONA, HORA_REF

UMBRAL_M = 0.02          # profundidad minima para considerar el suelo cubierto
DESCUENTO_M = 300.0      # la cota de nieve queda ~300 m bajo la isoterma 0 C
VENTANA_DIAS = 3         # la nieve persiste algunos dias aunque suba la isoterma
URL = "https://api.open-meteo.com/v1/forecast"
COLS = ["Punto", "Fecha", "NIEVE", "FZL"]


def _serie(h, nombre, n):
    """Primera serie del JSON cuyo nombre empieza por `nombre` y trae datos (tolera el sufijo del modelo)."""
    for k, v in h.items():
        if k.startswith(nombre) and v and any(x is not None for x in v):
            return np.array([np.nan if x is None else x for x in v], float)
    return np.full(n, np.nan)


def diaria(j):
    """Respuesta JSON de Open-Meteo -> DataFrame diario [Fecha, NIEVE (m), FZL (m)] a la hora de referencia."""
    h = j.get("hourly", {})
    t = pd.to_datetime(h.get("time", []))
    d = pd.DataFrame({"Fecha_Local": t, "NIEVE": _serie(h, "snow_depth", len(t)), "FZL": _serie(h, "freezing_level_height", len(t))})
    d = d[d["Fecha_Local"].dt.hour == HORA_REF]
    d["Fecha"] = d["Fecha_Local"].dt.normalize()
    return d[["Fecha", "NIEVE", "FZL"]].reset_index(drop=True)


def fetch(lat, lon, past_days=3, forecast_days=4):
    """Descarga profundidad de nieve e isoterma 0 C. Devuelve DataFrame vacio si falla (nunca rompe el calculo)."""
    params = {"latitude": lat, "longitude": lon, "hourly": "snow_depth,freezing_level_height",
              "timezone": ZONA, "past_days": past_days, "forecast_days": forecast_days}
    try:
        r = requests.get(URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[nieve] HTTP {r.status_code}")
            return pd.DataFrame(columns=["Fecha", "NIEVE", "FZL"])
        return diaria(r.json())
    except Exception as e:
        print(f"[nieve] {e}")
        return pd.DataFrame(columns=["Fecha", "NIEVE", "FZL"])


def perfil(nieve, fechas):
    """nieve: [Punto, Fecha, NIEVE, FZL]. Devuelve (profundidad_m, cota_m) por fecha; NaN si no hay dato."""
    fechas = pd.DatetimeIndex(fechas)
    if nieve is None or len(nieve) == 0:
        return np.full(len(fechas), np.nan), np.full(len(fechas), np.nan)
    g = nieve.copy()
    g["Fecha"] = pd.to_datetime(g["Fecha"])
    g = g.groupby("Fecha")[["NIEVE", "FZL"]].mean()
    rango = pd.date_range(min(fechas.min(), g.index.min()) - pd.Timedelta(days=VENTANA_DIAS), max(fechas.max(), g.index.max()), freq="D")
    g = g.reindex(rango)
    cota = g["FZL"].rolling(VENTANA_DIAS, min_periods=1).min() - DESCUENTO_M
    return g["NIEVE"].reindex(fechas).to_numpy(float), cota.reindex(fechas).to_numpy(float)


def cubierta(prof, cota, z):
    """Mascara booleana de celdas (o puntos) con nieve, dada la profundidad y la cota del dia y la altitud z."""
    z = np.asarray(z, float)
    if not (np.isfinite(prof) and np.isfinite(cota)) or prof <= UMBRAL_M:
        return np.zeros(z.shape, bool)
    return z >= cota


def marcar_puntos(ilpi, nieve, puntos):
    """Agrega la columna Nieve a las filas por punto; donde hay nieve el puntaje y la clase pasan a 0 / la mas baja."""
    from . import fireindex as fi
    out = ilpi.copy()
    out["Nieve"] = False
    if out.empty or nieve is None or len(nieve) == 0:
        return out
    fechas = pd.DatetimeIndex(sorted(pd.to_datetime(out["Fecha_Valida"]).unique()))
    prof, cota = perfil(nieve, fechas)
    for i, f in enumerate(fechas):
        for pto, m in puntos.items():
            if cubierta(prof[i], cota[i], m["alt"]):
                sel = (out["Punto"] == pto) & (pd.to_datetime(out["Fecha_Valida"]) == f)
                out.loc[sel, "Nieve"] = True
                for c in ("Bruto", "Score"):
                    if c in out:
                        out.loc[sel, c] = 0.0
                out.loc[sel, "Clase"] = fi.CLASS_NAMES[0]
    return out
