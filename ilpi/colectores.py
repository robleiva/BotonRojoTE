"""Recolectores de datos: estaciones Ambient, Open-Meteo (ECMWF IFS y GFS) y WRF-SMN.
Las funciones parse_* son puras (se prueban sin red). Las fetch_* hacen la llamada de red."""
import datetime as dt
import time
import numpy as np
import pandas as pd
import requests
from .config import ZONA, PUNTOS

KMH_POR_MPH = 1.609344
COLS = ["T", "RH", "V", "DIR", "PP"]   # T C, HR %, viento km/h, direccion (de donde sopla) grados, PP mm/h


# ------------------------------------------------------------------ Ambient Weather
def formatear_mac(mac_raw):
    limpia = (mac_raw or "").replace(":", "").replace("-", "").strip().lower()
    if len(limpia) == 12:
        return ":".join(limpia[i:i + 2] for i in range(0, 12, 2))
    return (mac_raw or "").strip().lower()


def parse_ambient(data, nombre):
    """Lista de registros de la API de Ambient -> DataFrame horario [Punto, Fecha_Local, T, RH, V, DIR, PP]."""
    filas = []
    for r in data or []:
        if r.get("dateutc") is None:
            continue
        ts = pd.to_datetime(r["dateutc"], unit="ms", utc=True).tz_convert(ZONA).tz_localize(None)
        tf, hum, ws, wd, rain = r.get("tempf"), r.get("humidity"), r.get("windspeedmph"), r.get("winddir"), r.get("dailyrainin")
        filas.append({
            "Fecha_Local": ts,
            "T": round((tf - 32) * 5 / 9, 2) if tf is not None else np.nan,
            "RH": float(hum) if hum is not None else np.nan,
            "V": round(ws * KMH_POR_MPH, 2) if ws is not None else np.nan,
            "DIR": float(wd) if wd is not None else np.nan,
            "Daily": round(rain * 25.4, 2) if rain is not None else np.nan,
        })
    if not filas:
        return pd.DataFrame(columns=["Punto", "Fecha_Local"] + COLS)
    d = pd.DataFrame(filas).sort_values("Fecha_Local").reset_index(drop=True)
    # lluvia: la API entrega acumulado diario (se reinicia a medianoche) -> incremento por registro
    inc = d["Daily"].diff().fillna(0)
    inc = inc.where(inc >= 0, d["Daily"])
    d["PP"] = inc.fillna(0)
    # direccion: promedio vectorial por hora
    rad = np.deg2rad(d["DIR"])
    d["sin"], d["cos"] = np.sin(rad), np.cos(rad)
    h = d.resample("1h", on="Fecha_Local").agg(
        {"T": "mean", "RH": "mean", "V": "mean", "PP": "sum", "sin": "mean", "cos": "mean"}).reset_index()
    h["DIR"] = (np.rad2deg(np.arctan2(h["sin"], h["cos"])) % 360).where(h["sin"].notna())
    h["Punto"] = nombre
    h[["T", "RH", "V", "DIR", "PP"]] = h[["T", "RH", "V", "DIR", "PP"]].round(2)
    return h[["Punto", "Fecha_Local"] + COLS]


def fetch_ambient(mac, nombre, api_key, app_key, limit=576):
    """576 registros de 5 min = 48 h."""
    if not (api_key and app_key and mac):
        return pd.DataFrame(columns=["Punto", "Fecha_Local"] + COLS)
    try:
        time.sleep(2)  # la API limita a ~1 consulta por segundo
        r = requests.get(f"https://rt.ambientweather.net/v1/devices/{mac}",
                         params={"apiKey": api_key, "applicationKey": app_key, "limit": limit}, timeout=20)
        if r.status_code != 200:
            print(f"[Ambient] {nombre}: HTTP {r.status_code}")
            return pd.DataFrame(columns=["Punto", "Fecha_Local"] + COLS)
        return parse_ambient(r.json(), nombre)
    except Exception as e:
        print(f"[Ambient] {nombre}: {e}")
        return pd.DataFrame(columns=["Punto", "Fecha_Local"] + COLS)


# ------------------------------------------------------------------ Open-Meteo
MODELOS_OM = {"ECMWF": "ecmwf_ifs025", "GFS": "gfs_seamless"}
VARS_OM = {"T": "temperature_2m", "RH": "relative_humidity_2m", "V": "wind_speed_10m",
           "DIR": "wind_direction_10m", "PP": "precipitation"}


def parse_openmeteo(j):
    """Respuesta JSON -> ({modelo: DataFrame horario}, elevacion_modelo_m)."""
    h = j.get("hourly", {})
    t = pd.to_datetime(h.get("time", []))
    out = {}
    for nombre, code in MODELOS_OM.items():
        d = pd.DataFrame({"Fecha_Local": t})
        for k, v in VARS_OM.items():
            d[k] = h.get(f"{v}_{code}", [np.nan] * len(t))
        out[nombre] = d
    return out, j.get("elevation", np.nan)


def fetch_openmeteo(lat, lon, past_days, forecast_days=4):
    params = {"latitude": lat, "longitude": lon, "hourly": list(VARS_OM.values()),
              "models": list(MODELOS_OM.values()), "timezone": ZONA, "wind_speed_unit": "kmh",
              "past_days": past_days, "forecast_days": forecast_days}
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
        if r.status_code != 200:
            print(f"[Open-Meteo] HTTP {r.status_code}")
            return {}, np.nan
        return parse_openmeteo(r.json())
    except Exception as e:
        print(f"[Open-Meteo] {e}")
        return {}, np.nan


# ------------------------------------------------------------------ WRF-SMN (AWS S3 abierto)
# Nombres candidatos de variables (NO verificados: el log imprime las variables reales en cada corrida).
WRF_CANDIDATOS = {
    "T": ["T2"], "PP": ["PP"],
    "RH": ["HR2", "RH2", "HR", "rh2"],
    "V": ["magViento10", "WSPD10", "mag10", "viento10"],
    "DIR": ["dirViento10", "WDIR10", "dir10"],
}


def _primera(ds, nombres):
    for n in nombres:
        if n in ds.data_vars:
            return n
    return None


def fetch_wrf(fecha_corrida, max_lead=72):
    """Extrae T, PP y, si existen, HR y viento del WRF-SMN en los PUNTOS. Devuelve DataFrame horario por punto."""
    import s3fs
    import xarray as xr
    import cartopy.crs as ccrs
    fs = s3fs.S3FileSystem(anon=True)
    filas, coords, crs, avisado = [], {}, None, False
    for lead in range(1, max_lead + 1):
        ruta = f"smn-ar-wrf/DATA/WRF/DET/{fecha_corrida:%Y/%m/%d/%H}/WRFDETAR_01H_{fecha_corrida:%Y%m%d_%H}_{lead:03d}.nc"
        try:
            if not fs.exists(ruta):
                continue
            with fs.open(ruta) as f, xr.open_dataset(f, decode_coords="all", engine="h5netcdf") as ds:
                if crs is None:
                    lc = ds["Lambert_Conformal"].attrs
                    crs = ccrs.LambertConformal(central_longitude=lc["longitude_of_central_meridian"],
                                                central_latitude=lc["latitude_of_projection_origin"],
                                                standard_parallels=lc["standard_parallel"])
                    coords = {n: crs.transform_point(c["lon"], c["lat"], src_crs=ccrs.PlateCarree()) for n, c in PUNTOS.items()}
                nombres = {k: _primera(ds, v) for k, v in WRF_CANDIDATOS.items()}
                if not avisado:
                    print("[WRF] variables del archivo:", list(ds.data_vars))
                    print("[WRF] variables usadas:", nombres)
                    avisado = True
                valida = (pd.Timestamp(fecha_corrida, tz="UTC") + pd.Timedelta(hours=lead)).tz_convert(ZONA).tz_localize(None)
                for pto, (x, y) in coords.items():
                    nodo = ds.sel(x=x, y=y, method="nearest")
                    fila = {"Punto": pto, "Fecha_Local": valida}
                    for k, n in nombres.items():
                        fila[k] = float(nodo[n].values) if n else np.nan
                    filas.append(fila)
        except Exception as e:
            print(f"[WRF] lead +{lead}: {e}")
    return pd.DataFrame(filas, columns=["Punto", "Fecha_Local"] + COLS)
