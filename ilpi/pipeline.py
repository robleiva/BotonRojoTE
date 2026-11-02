"""Logica del calculo diario (funciones puras, sin red ni archivos)."""
import numpy as np
import pandas as pd
from . import fireindex as fi
from .config import HORA_REF, F_INICIAL, DIAS_PRON, PUNTOS

COLS_CLIMA = ["T", "RH", "V", "DIR", "PP24"]


def clima_15h(df_h, hora=HORA_REF):
    """DataFrame horario [Fecha_Local,T,RH,V,DIR,PP] -> una fila por dia a la hora de referencia,
    con PP24 = lluvia de las 24 h que terminan a esa hora (exige serie completa)."""
    if df_h is None or df_h.empty:
        return pd.DataFrame(columns=["Fecha"] + COLS_CLIMA)
    d = df_h.sort_values("Fecha_Local").drop_duplicates("Fecha_Local").set_index("Fecha_Local").asfreq("h")
    d["PP24"] = d["PP"].rolling(24, min_periods=24).sum()
    s = d[d.index.hour == hora].copy()
    s["Fecha"] = s.index.normalize()
    return s.reset_index(drop=True)[["Fecha"] + COLS_CLIMA]


def aplicar_altitud(df, z_ref, alt_punto):
    """Corrige T y HR del modelo a la altitud del punto."""
    if df.empty or not np.isfinite(z_ref):
        return df
    d = df.copy()
    d["T"], d["RH"] = fi.downscale(d["T"], d["RH"], z_ref, alt_punto)
    return d


def _num(df, cols):
    """Fuerza columnas numericas (float) para evitar enteros/objetos al leer CSV o rellenar huecos."""
    d = df.copy()
    for c in cols:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float) if c in d else np.nan
    return d


def propagar(f_ini, clima):
    """Avanza el FFMC dia a dia. Si faltan datos de un dia, arrastra el estado y marca la calidad."""
    c = _num(clima.sort_values("Fecha").reset_index(drop=True), COLS_CLIMA)
    A = {k: c[k].to_numpy(float) for k in COLS_CLIMA}
    f, ffmc, m_out, cal = float(f_ini), [], [], []
    for i in range(len(c)):
        if all(np.isfinite(A[k][i]) for k in ("T", "RH", "V", "PP24")):
            f, m = fi.ffmc_step(f, A["T"][i], A["RH"][i], A["V"][i], A["PP24"][i])
            f, m, q = float(f), float(m), "ok"
        else:
            m, q = float(147.2 * (101 - f) / (59.5 + f)), "sin_dato"
        ffmc.append(f); m_out.append(m); cal.append(q)
    out = c.copy()
    out["FFMC"], out["M"], out["Calidad"] = ffmc, m_out, cal
    return out


def indice_fila(r, terreno):
    """r: fila con M (humedad %), V, DIR. terreno: dict slope, aspect, fuel_w, ndmi."""
    asp = terreno.get("aspect", np.nan)
    dry = float(fi.dryness(r["M"], asp))
    ndmi = terreno.get("ndmi", np.nan)
    live = 0.5 if not np.isfinite(ndmi) else float(fi.live_fuel_dryness(ndmi))
    fuel = float(fi.fuel_factor(terreno.get("fuel_w", 0.85), live))
    wind = r["V"] if np.isfinite(r["V"]) else 0.0
    wdir = r["DIR"] if np.isfinite(r["DIR"]) else 0.0
    spr = float(fi.spread(wind, wdir, terreno.get("slope", 10.0), asp if np.isfinite(asp) else 0.0))
    raw = float(fi.raw_index(dry, fuel, spr))
    score = float(fi.score_provisional(raw))
    return {"Seco": round(dry, 3), "Comb": round(fuel, 3), "Prop": round(spr, 3),
            "Bruto": round(raw, 3), "Score": round(score, 1), "Clase": str(fi.to_class(score, fi.PROV_BREAKS))}


def calcular(registrado, pron, estado, terreno, hoy, puntos=PUNTOS):
    """
    registrado: [Punto, Fecha, T,RH,V,DIR,PP24, z_ref, Fuente]  dias < hoy (T/HR del modelo SIN corregir altitud)
    pron:       [Punto, Fecha, Modelo, T,RH,V,DIR,PP24, z_ref]  dias hoy .. hoy+DIAS_PRON
    estado:     [Punto, Fecha, FFMC, M, Calidad, Fuente]
    terreno:    {punto: {slope, aspect, fuel_w, ndmi}}
    Devuelve (nuevas filas de estado, filas de indice emitidas).
    """
    hoy = pd.Timestamp(hoy).normalize()
    nuevo_estado, ilpi = [], []
    for pto, meta in puntos.items():
        reg = registrado[registrado["Punto"] == pto].copy()
        est = estado[estado["Punto"] == pto].sort_values("Fecha")
        if est.empty:
            f0, desde = F_INICIAL, (reg["Fecha"].min() if not reg.empty else hoy)
        else:
            f0, desde = float(est.iloc[-1]["FFMC"]), pd.Timestamp(est.iloc[-1]["Fecha"]) + pd.Timedelta(days=1)
        dias = pd.date_range(desde, hoy - pd.Timedelta(days=1), freq="D")
        if len(dias):
            r = reg.set_index("Fecha").reindex(dias)
            r.index.name = "Fecha"
            r = r.reset_index()
            for c in COLS_CLIMA:
                if c not in r:
                    r[c] = np.nan
            fuente = r["Fuente"].fillna("sin_dato") if "Fuente" in r else pd.Series("sin_dato", index=r.index)
            r = _num(r, COLS_CLIMA + ["z_ref"])
            # correccion de altitud solo a datos de modelo
            mod = fuente != "ESTACION"
            if mod.any():
                zr = r.loc[mod, "z_ref"].astype(float)
                t, rh = fi.downscale(r.loc[mod, "T"], r.loc[mod, "RH"], zr.fillna(meta["alt"]), meta["alt"])
                r.loc[mod, "T"], r.loc[mod, "RH"] = t, rh
            res = propagar(f0, r)
            res["Punto"], res["Fuente"] = pto, fuente.values
            nuevo_estado.append(res[["Punto", "Fecha", "FFMC", "M", "Calidad", "Fuente"]])
            f0 = float(res.iloc[-1]["FFMC"])
        # pronostico por modelo
        for modelo, g in pron[pron["Punto"] == pto].groupby("Modelo"):
            g = _num(g.sort_values("Fecha"), COLS_CLIMA + ["z_ref"])
            zr = g["z_ref"].fillna(meta["alt"])
            g["T"], g["RH"] = fi.downscale(g["T"], g["RH"], zr, meta["alt"])
            res = propagar(f0, g)
            for row in res.to_dict("records"):
                d = indice_fila(row, terreno.get(pto, {}))
                ilpi.append({"Emision": hoy, "Punto": pto, "Modelo": modelo, "Fecha_Valida": row["Fecha"],
                             "Lead": int((row["Fecha"] - hoy).days), "FFMC": round(row["FFMC"], 1),
                             "M": round(row["M"], 1), "T": round(row["T"], 1), "RH": round(row["RH"], 0),
                             "V": round(row["V"], 1), "PP24": round(row["PP24"], 1) if np.isfinite(row["PP24"]) else np.nan,
                             "Calidad": row["Calidad"], **d})
    ne = pd.concat(nuevo_estado, ignore_index=True) if nuevo_estado else pd.DataFrame(columns=["Punto", "Fecha", "FFMC", "M", "Calidad", "Fuente"])
    return ne, pd.DataFrame(ilpi)
