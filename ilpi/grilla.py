"""Indice por celda (90 m) sobre la cuenca: mapa de peligro relativo.

Flujo: clima de los puntos (ya corregido a su altitud) -> reducido a una altitud comun ->
interpolado por distancia inversa -> corregido a la altitud de cada celda -> FFMC por celda
(ventana de HIST_DIAS dias) -> indice con pendiente, exposicion y combustible de la celda.
Mismos componentes y pesos que el indice por punto (ver fireindex.py).
"""
import base64
import io

import numpy as np
import pandas as pd
from PIL import Image

from . import fireindex as fi, nieve as nv
from .config import PUNTOS, F_INICIAL

HIST_DIAS = 30          # dias de clima registrado para reconstruir el FFMC de cada celda
Z_COMUN = 1500.0        # altitud a la que se interpola el clima
POT_IDW = 2.0
FUEL_MIN = 0.15         # celdas con menos combustible (roca, nieve, agua) no se colorean
COLORES = {"Bajo": (47, 158, 68), "Moderado": (242, 194, 0), "Alto": (240, 140, 0),
           "Muy alto": (224, 49, 49), "Extremo": (123, 31, 162)}
COLS = ["T", "RH", "V", "DIR", "PP24"]


def cargar_terreno(ruta):
    d = np.load(ruta)
    asp = d["aspect"].astype(float)
    asp[asp < 0] = np.nan
    return {"elev": d["elev"].astype(float), "slope": d["slope"].astype(float), "aspect": asp,
            "fuel": d["fuel"].astype(float) / 100.0, "dom": d["dom"], "valido": d["valido"],
            "origen": d["origen"], "celda": float(d["celda"][0])}


def limites(ter):
    """[[sur, oeste], [norte, este]] para la capa de imagen."""
    h, w = ter["valido"].shape
    lon0, lat0 = ter["origen"]
    return [[lat0 - h * ter["celda"], lon0], [lat0, lon0 + w * ter["celda"]]]


def _coords(ter):
    h, w = ter["valido"].shape
    lon0, lat0 = ter["origen"]
    c = ter["celda"]
    r, k = np.nonzero(ter["valido"])
    return r, k, lat0 - (r + 0.5) * c, lon0 + (k + 0.5) * c


def pesos_idw(lat, lon, puntos=PUNTOS):
    """Matriz [celda, punto] de pesos normalizados por distancia inversa (km)."""
    nombres = list(puntos)
    d = np.empty((lat.size, len(nombres)))
    for j, n in enumerate(nombres):
        dy = (lat - puntos[n]["lat"]) * 111.32
        dx = (lon - puntos[n]["lon"]) * 111.32 * np.cos(np.radians(lat))
        d[:, j] = np.maximum(np.hypot(dx, dy), 0.5)
    w = 1.0 / d ** POT_IDW
    return nombres, w


def clima_puntos(registrado, pron, hoy, puntos=PUNTOS, dias_hist=HIST_DIAS, modelo="ECMWF"):
    """Arreglos [dia, punto] con el clima a la altitud de cada punto: historia + pronostico.
    registrado: [Punto, Fecha, T,RH,V,DIR,PP24, z_ref, Fuente]; pron: [Punto, Fecha, Modelo, ..., z_ref]."""
    hoy = pd.Timestamp(hoy).normalize()
    dias_pron = max(0, int((pd.Timestamp(pron["Fecha"].max()).normalize() - hoy).days))
    fechas = pd.date_range(hoy - pd.Timedelta(days=dias_hist), hoy + pd.Timedelta(days=dias_pron), freq="D")
    nombres = list(puntos)
    out = {c: np.full((len(fechas), len(nombres)), np.nan) for c in COLS}
    pr = pron[pron["Modelo"] == modelo]
    for j, n in enumerate(nombres):
        a = registrado[registrado["Punto"] == n].copy()
        a["Fuente"] = a["Fuente"] if "Fuente" in a else "ECMWF"
        b = pr[pr["Punto"] == n].assign(Fuente=modelo)
        g = pd.concat([a[a["Fecha"] < hoy], b[b["Fecha"] >= hoy]], ignore_index=True)
        g = g.drop_duplicates("Fecha", keep="last").set_index("Fecha").reindex(fechas)
        for c in COLS:
            g[c] = pd.to_numeric(g[c], errors="coerce").astype(float)
        zr = pd.to_numeric(g["z_ref"], errors="coerce").astype(float)
        modelo_ok = (g["Fuente"] != "ESTACION") & g["T"].notna()
        t, rh = g["T"].to_numpy(), g["RH"].to_numpy()
        if modelo_ok.any():
            t2, rh2 = fi.downscale(t, rh, zr.fillna(puntos[n]["alt"]).to_numpy(), puntos[n]["alt"])
            t = np.where(modelo_ok.to_numpy(), t2, t)
            rh = np.where(modelo_ok.to_numpy(), rh2, rh)
        out["T"][:, j], out["RH"][:, j] = t, rh
        for c in ("V", "DIR", "PP24"):
            out[c][:, j] = g[c].to_numpy()
    return fechas, out


def _idw(valores, w):
    """valores [dia, punto] (NaN = sin dato), w [celda, punto] -> [dia, celda]; NaN si ningun punto tiene dato."""
    ok = np.isfinite(valores)
    num = np.where(ok, valores, 0.0) @ w.T
    den = ok.astype(float) @ w.T
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def clima_celdas(clima, w, z_celda, puntos=PUNTOS):
    """Clima [dia, celda] a la altitud de cada celda."""
    nombres = list(puntos)
    alt = np.array([puntos[n]["alt"] for n in nombres], float)
    # cada punto -> altitud comun (T y punto de rocio)
    t_c, rh_c = fi.downscale(clima["T"], clima["RH"], alt[None, :], Z_COMUN)
    td_c = fi.dewpoint(t_c, rh_c)
    t_m, td_m = _idw(t_c, w), _idw(td_c, w)
    rh_m = np.clip(100 * fi.esat(np.minimum(td_m, t_m)) / fi.esat(t_m), 1, 100)
    t, rh = fi.downscale(t_m, rh_m, Z_COMUN, z_celda[None, :])
    v = _idw(clima["V"], w)
    u_, vv_ = _idw(clima["V"] * np.sin(np.deg2rad(clima["DIR"])), w), _idw(clima["V"] * np.cos(np.deg2rad(clima["DIR"])), w)
    direc = np.where(np.isfinite(u_) & np.isfinite(vv_), np.degrees(np.arctan2(u_, vv_)) % 360, 0.0)
    return {"T": t, "RH": rh, "V": v, "DIR": direc, "PP24": _idw(clima["PP24"], w)}


def calcular_mapa(registrado, pron, hoy, ruta_terreno, puntos=PUNTOS, modelo="ECMWF", ruta_ignicion=None, nieve=None):
    """Devuelve dict: fechas (de hoy en adelante), score [dia, h, w], clase_idx, mascara de combustible y resumen."""
    ter = cargar_terreno(ruta_terreno)
    r, k, lat, lon = _coords(ter)
    nombres, w = pesos_idw(lat, lon, puntos)
    fechas, clima = clima_puntos(registrado, pron, hoy, puntos, modelo=modelo)
    z = ter["elev"][r, k]
    cc = clima_celdas(clima, w, z, puntos)
    f = np.full(z.shape, float(F_INICIAL))
    hoy = pd.Timestamp(hoy).normalize()
    asp = np.where(np.isfinite(ter["aspect"][r, k]), ter["aspect"][r, k], 0.0)
    asp_dry = ter["aspect"][r, k]
    slope, fuel = ter["slope"][r, k], ter["fuel"][r, k]
    fuel_f = fi.fuel_factor(fuel, 0.5)          # sin NDMI: neutro (igual que el indice por punto)
    prof, cota = nv.perfil(nieve, fechas)
    dias, scores, cubs = [], [], []
    for i, fe in enumerate(fechas):
        ok = np.isfinite(cc["T"][i]) & np.isfinite(cc["RH"][i]) & np.isfinite(cc["V"][i]) & np.isfinite(cc["PP24"][i])
        f_new, m_new = fi.ffmc_step(f, np.nan_to_num(cc["T"][i]), np.nan_to_num(cc["RH"][i], nan=50.0),
                                    np.nan_to_num(cc["V"][i]), np.nan_to_num(cc["PP24"][i]))
        f = np.where(ok, f_new, f)               # sin dato: se arrastra el estado
        m = np.where(ok, m_new, 147.2 * (101 - f) / (59.5 + f))
        if fe >= hoy:
            dry = fi.dryness(m, asp_dry)
            spr = fi.spread(np.nan_to_num(cc["V"][i]), cc["DIR"][i], slope, asp)
            cub = nv.cubierta(prof[i], cota[i], z)
            raw = fi.raw_index(dry, fuel_f, spr, snow_m=np.where(cub, 1.0, 0.0))
            sc = fi.score_provisional(raw)
            scores.append(np.where(cub, np.nan, sc))
            cubs.append(cub)
            dias.append(fe)
    h, wd = ter["valido"].shape
    S = np.full((len(dias), h, wd), np.nan)
    for i, s in enumerate(scores):
        S[i][r, k] = s
    comb = np.zeros((h, wd), bool)
    comb[r, k] = fuel >= FUEL_MIN
    N = np.zeros((len(dias), h, wd), bool)
    for i, c in enumerate(cubs):
        N[i][r, k] = c
    resumen = []
    for i, fe in enumerate(dias):
        s = scores[i][(fuel >= FUEL_MIN) & ~cubs[i]]
        cl = np.searchsorted(fi.PROV_BREAKS, s, side="right")
        ha = 0.81  # 90 m x 90 m
        resumen.append({"Fecha": fe, "Ha_combustible": round(float(s.size * ha)),
                        "Ha_nieve": round(float(cubs[i].sum() * ha)),
                        **{n: round(float((cl == j).sum() * ha)) for j, n in enumerate(fi.CLASS_NAMES)}})
    return {"fechas": dias, "score": S, "combustible": comb, "limites": limites(ter), "resumen": resumen,
            "nieve": N if N.any() else None,
            "ignicion": cargar_ignicion(ruta_ignicion, ter["valido"]) if ruta_ignicion else None}


def cargar_ignicion(ruta, valido):
    """Exposicion a ignicion humana (0-100) si el archivo existe y calza con la grilla; si no, None."""
    try:
        e = np.load(ruta)["exposicion"]
    except Exception:
        return None
    return np.where(valido, e, 0).astype(np.uint8) if e.shape == valido.shape else None


def png_ignicion_base64(exp, minimo=8):
    """PNG RGBA: de cian claro (poca exposicion) a gris oscuro (mucha); bajo el minimo = transparente."""
    t = np.clip((exp.astype(float) - minimo) / (100 - minimo), 0, 1)[..., None]
    a, b = np.array([0, 171, 229, 110.0]), np.array([65, 64, 66, 225.0])
    img = (a + (b - a) * t).astype(np.uint8)
    img[exp < minimo] = 0
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


COLOR_NIEVE = (196, 224, 242, 215)


def png_base64(score2d, combustible, nieve2d=None):
    """PNG RGBA (paleta por clase; sin combustible = transparente; nieve en celeste claro)."""
    h, w = score2d.shape
    img = np.zeros((h, w, 4), np.uint8)
    if nieve2d is not None:
        img[nieve2d] = COLOR_NIEVE
    cl = np.searchsorted(fi.PROV_BREAKS, np.nan_to_num(score2d, nan=0.0), side="right")
    for j, n in enumerate(fi.CLASS_NAMES):
        m = combustible & np.isfinite(score2d) & (cl == j)
        img[m] = (*COLORES[n], 190)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()
