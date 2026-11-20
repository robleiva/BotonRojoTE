"""Focos de calor de NASA FIRMS (VIIRS y MODIS, tiempo casi real) para verificar y calibrar el indice.

API de area: https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{FUENTE}/{oeste,sur,este,norte}/{dias}/{fecha}
Los focos se acumulan en historico/focos_firms.csv. Un foco es una anomalia termica detectada por satelite:
no siempre es un incendio forestal (puede ser quema agricola, industria, etc.) y los satelites pasan solo algunas veces al dia.
"""
import io
import datetime as dt
import pandas as pd
import requests

URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{fuente}/{bbox}/{dias}/{fecha}"
FUENTES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"]
BBOX = (-70.80, -35.05, -70.20, -34.55)      # oeste, sur, este, norte: cuenca alta y media del Tinguiririca
COLS = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument", "confidence", "frp", "daynight", "Fuente"]
CLAVE = ["latitude", "longitude", "acq_date", "acq_time", "satellite"]


def parse_csv(texto, fuente):
    """Texto CSV de FIRMS -> DataFrame con columnas COLS. Devuelve vacio si no hay focos o la respuesta no es CSV."""
    vacio = pd.DataFrame(columns=COLS)
    if not texto or "latitude" not in texto.splitlines()[0]:
        return vacio
    d = pd.read_csv(io.StringIO(texto))
    if d.empty:
        return vacio
    d["Fuente"] = fuente
    for c in COLS:
        if c not in d:
            d[c] = None
    d["confidence"] = d["confidence"].astype(str)      # VIIRS: l/n/h ; MODIS: 0-100
    return d[COLS]


def fetch(key, fuente, hoy, dias=5, bbox=BBOX, timeout=60):
    url = URL.format(key=key, fuente=fuente, bbox=",".join(str(x) for x in bbox), dias=dias, fecha=f"{hoy:%Y-%m-%d}")
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return parse_csv(r.text, fuente)


def fetch_todas(key, hoy, dias=5, fuentes=FUENTES):
    """Descarga las fuentes; una fuente que falla no impide las demas. Devuelve (DataFrame, lista de errores)."""
    partes, errores = [], []
    for f in fuentes:
        try:
            partes.append(fetch(key, f, hoy, dias))
        except Exception as e:
            errores.append(f"{f}: {e}")
    partes = [p for p in partes if not p.empty]
    return (pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLS)), errores


def acumular(nuevo, previo):
    """Agrega focos nuevos al historico sin duplicar (mismo foco visto en descargas solapadas)."""
    if previo is None or previo.empty:
        out = nuevo
    else:
        out = pd.concat([previo, nuevo], ignore_index=True)
    if out.empty:
        return out
    out["acq_time"] = out["acq_time"].astype(str).str.zfill(4)
    return out.drop_duplicates(CLAVE, keep="last").sort_values(["acq_date", "acq_time"]).reset_index(drop=True)
