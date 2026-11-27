"""
Indice local de peligro de incendios - Cuenca del Tinguiririca (prototipo v0.1)

Peligro relativo 0-100 como media geometrica ponderada de tres factores 0-1:
  sequedad del combustible muerto  x  estado/tipo de combustible  x  potencial de propagacion
Los pesos son A PRIORI y deben calibrarse con focos de calor / incendios (ver backtest.py).
"""
import numpy as np

LAPSE = 0.0065        # K/m, gradiente termico
DEW_LAPSE = 0.002     # K/m, gradiente del punto de rocio (aprox.)

# Peso por tipo de combustible (a priori; reemplazar por catastro vegetacional CONAF)
FUEL_WEIGHT = {
    "pastizal": 1.00, "matorral": 0.85, "plantacion": 0.90,
    "bosque_nativo": 0.50, "agricola": 0.40, "sin_combustible": 0.0,
}
WEIGHTS = {"dry": 0.45, "fuel": 0.35, "spread": 0.20}
CLASS_BREAKS = [50, 75, 90, 97]       # por percentil (cuando exista distribucion historica de referencia)
PROV_BREAKS_BASE = [30, 50, 65, 80]   # PROVISORIO sobre 100*raw, usado mientras no exista calibracion por percentiles


def _cargar_cortes():
    """Cortes de clase por percentiles del clima historico (datos/calibracion_percentiles.json), si existen y son validos."""
    import json
    import os
    if os.environ.get("ILPI_SIN_CALIBRACION") == "1":
        return list(PROV_BREAKS_BASE), None
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datos", "calibracion_percentiles.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
        c = [float(x) for x in d["cortes"]]
        if len(c) == 4 and all(a < b for a, b in zip(c, c[1:])):
            return c, d
    except Exception:
        pass
    return list(PROV_BREAKS_BASE), None


PROV_BREAKS, CALIBRACION = _cargar_cortes()
CLASS_NAMES = ["Bajo", "Moderado", "Alto", "Muy alto", "Extremo"]


# ---------- 1. Meteorologia a la altura del sitio ----------
def esat(t_c):
    """Presion de vapor de saturacion (hPa), Magnus."""
    return 6.112 * np.exp(17.62 * t_c / (243.12 + t_c))


def dewpoint(t_c, rh):
    g = np.log(np.clip(rh, 1, 100) / 100.0) + 17.62 * t_c / (243.12 + t_c)
    return 243.12 * g / (17.62 - g)


def downscale(t_ref, rh_ref, z_ref, z_site):
    """Corrige T y HR de la celda del modelo (z_ref) a la altitud del sitio (z_site)."""
    t_ref, rh_ref = np.asarray(t_ref, float), np.asarray(rh_ref, float)
    dz = np.asarray(z_site, float) - np.asarray(z_ref, float)
    t_site = t_ref - LAPSE * dz
    td_site = dewpoint(t_ref, rh_ref) - DEW_LAPSE * dz
    td_site = np.minimum(td_site, t_site)
    rh_site = np.clip(100 * esat(td_site) / esat(t_site), 1, 100)
    return t_site, rh_site


# ---------- 2. Humedad del combustible fino muerto (Van Wagner 1987, FFMC) ----------
def ffmc_step(f0, t, rh, wind_kmh, rain_mm):
    """Un paso diario. Devuelve (FFMC, humedad del combustible en %)."""
    f0, t, h, w, r = (np.asarray(x, float) for x in (f0, t, rh, wind_kmh, rain_mm))
    h = np.clip(h, 0, 100)
    mo = 147.2 * (101 - f0) / (59.5 + f0)
    rf = np.maximum(r - 0.5, 0.0)
    wet = rf > 0
    rfs = np.where(wet, rf, 1.0)
    add = 42.5 * rfs * np.exp(-100 / (251 - mo)) * (1 - np.exp(-6.93 / rfs))
    add = add + np.where(mo > 150, 0.0015 * (mo - 150) ** 2 * np.sqrt(rfs), 0.0)
    mo = np.where(wet, np.minimum(mo + add, 250.0), mo)

    tt = 0.18 * (21.1 - t) * (1 - np.exp(-0.115 * h))
    ed = 0.942 * h ** 0.679 + 11 * np.exp((h - 100) / 10) + tt
    ew = 0.618 * h ** 0.753 + 10 * np.exp((h - 100) / 10) + tt
    kd = (0.424 * (1 - (h / 100) ** 1.7) + 0.0694 * np.sqrt(w) * (1 - (h / 100) ** 8)) * 0.581 * np.exp(0.0365 * t)
    kw = (0.424 * (1 - ((100 - h) / 100) ** 1.7) + 0.0694 * np.sqrt(w) * (1 - ((100 - h) / 100) ** 8)) * 0.581 * np.exp(0.0365 * t)
    m = np.where(mo > ed, ed + (mo - ed) / 10 ** kd,
                 np.where(mo < ew, ew - (ew - mo) / 10 ** kw, mo))
    f = np.clip(59.5 * (250 - m) / (147.2 + m), 0, 101)
    return f, m


def ffmc_series(t, rh, wind, rain, f_init=85.0):
    """Serie diaria (arrays 1-D o [dia, celda]). Devuelve FFMC y humedad %."""
    t, rh, wind, rain = (np.asarray(x, float) for x in (t, rh, wind, rain))
    f = np.full(t.shape[1:], f_init) if t.ndim > 1 else np.float64(f_init)
    F, M = np.empty_like(t), np.empty_like(t)
    for i in range(t.shape[0]):
        f, m = ffmc_step(f, t[i], rh[i], wind[i], rain[i])
        F[i], M[i] = f, m
    return F, M


# ---------- 3. Componentes 0-1 ----------
def dryness(m_pct, aspect_deg=None):
    """Sequedad del combustible muerto. Exposicion norte (hemisferio sur) = mas insolacion."""
    d = np.clip((30.0 - np.asarray(m_pct, float)) / (30.0 - 6.0), 0, 1)
    if aspect_deg is None:
        return d
    a = np.asarray(aspect_deg, float)
    a = np.where(np.isnan(a), 90.0, a)          # terreno plano -> neutro
    sun = 0.5 * (1 + np.cos(np.deg2rad(a)))     # 1 = cara norte, 0 = cara sur
    return np.clip(d * (0.90 + 0.20 * sun), 0, 1)


def live_fuel_dryness(ndmi, lo=-0.10, hi=0.40):
    """0 = vegetacion verde/humeda, 1 = vegetacion seca (NDMI Sentinel-2/MODIS)."""
    return 1 - np.clip((np.asarray(ndmi, float) - lo) / (hi - lo), 0, 1)


def fuel_factor(fuel_weight, live_dry):
    return np.asarray(fuel_weight, float) * (0.6 + 0.4 * np.asarray(live_dry, float))


def spread(wind_kmh, wind_from_deg, slope_deg, aspect_deg):
    """Propagacion: viento y pendiente (alineada con el viento) combinados como 'O' probabilistico."""
    fw = 1 - np.exp(-np.asarray(wind_kmh, float) / 25.0)
    wind_to = (np.asarray(wind_from_deg, float) + 180) % 360
    upslope = (np.asarray(aspect_deg, float) + 180) % 360
    align = np.cos(np.deg2rad(wind_to - upslope))
    align = np.where(np.isnan(align), 0.0, align)
    fs = np.clip(np.tan(np.deg2rad(np.asarray(slope_deg, float))), 0, 1) * (0.6 + 0.4 * align)
    return 1 - (1 - fw) * (1 - np.clip(fs, 0, 1))


# ---------- 4. Indice ----------
def raw_index(dry, fuel, spr, weights=WEIGHTS, snow_m=None):
    eps = 1e-6
    spr_f = 0.25 + 0.75 * np.asarray(spr, float)     # sin viento ni pendiente el fuego igual puede avanzar
    raw = np.exp(weights["dry"] * np.log(np.asarray(dry, float) + eps)
                 + weights["fuel"] * np.log(np.asarray(fuel, float) + eps)
                 + weights["spread"] * np.log(spr_f))
    if snow_m is not None:
        raw = np.where(np.asarray(snow_m, float) > 0.02, 0.0, raw)
    return raw


def to_score(raw, reference):
    """Score 0-100 = percentil de 'raw' dentro de la distribucion historica de referencia."""
    ref = np.sort(np.asarray(reference, float).ravel())
    return 100.0 * np.searchsorted(ref, np.asarray(raw, float), side="right") / ref.size


def score_provisional(raw):
    """Score provisorio = 100 x indice bruto (0-1). Se reemplaza por percentiles al calibrar."""
    return 100.0 * np.clip(np.asarray(raw, float), 0, 1)


def to_class(score, breaks=None):
    breaks = CLASS_BREAKS if breaks is None else breaks
    return np.array(CLASS_NAMES)[np.searchsorted(breaks, np.asarray(score, float), side="right")]
