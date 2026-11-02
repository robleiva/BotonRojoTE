"""Calcula pendiente y exposicion de cada punto con el DEM de Open-Meteo (Copernicus 90 m).
Ejecutar UNA VEZ con internet:  python scripts/calcular_terreno.py
Actualiza las columnas slope y aspect de datos/puntos_terreno.csv (conserva clase de combustible y NDMI)."""
import os, sys, time
import numpy as np, pandas as pd, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ilpi.config import PUNTOS, F_TERRENO

D = 0.005  # ~500 m


def elevaciones(lat, lon):
    r = requests.get("https://api.open-meteo.com/v1/elevation",
                     params={"latitude": ",".join(map(str, lat)), "longitude": ",".join(map(str, lon))}, timeout=30)
    r.raise_for_status()
    return np.array(r.json()["elevation"], float)


nombres = list(PUNTOS)
la = np.array([PUNTOS[n]["lat"] for n in nombres]); lo = np.array([PUNTOS[n]["lon"] for n in nombres])
z = {k: elevaciones(a, b) for k, (a, b) in {"n": (la + D, lo), "s": (la - D, lo), "e": (la, lo + D), "w": (la, lo - D)}.items()}
dy = 2 * D * 111_320.0; dx = dy * np.cos(np.deg2rad(la))
dzdx, dzdy = (z["e"] - z["w"]) / dx, (z["n"] - z["s"]) / dy
slope = np.rad2deg(np.arctan(np.hypot(dzdx, dzdy)))
aspect = np.where(slope < 1, np.nan, np.rad2deg(np.arctan2(-dzdx, -dzdy)) % 360)   # direccion hacia donde mira la ladera (0 = N)

t = pd.read_csv(F_TERRENO).set_index("Punto")
for n, s, a in zip(nombres, slope, aspect):
    t.loc[n, "slope"], t.loc[n, "aspect"] = round(float(s), 1), (round(float(a), 0) if np.isfinite(a) else np.nan)
t.reset_index().to_csv(F_TERRENO, index=False)
print(t[["slope", "aspect", "fuel_class"]])
