import os
import numpy as np
import pandas as pd
import pytest
from ilpi import grilla, fireindex as fi
from ilpi.config import PUNTOS

RUTA = os.path.join(os.path.dirname(__file__), "..", "datos", "terreno_90m.npz")
HOY = pd.Timestamp("2026-12-15")


def _clima(t=28.0, rh=25.0, v=15.0, pp=0.0, dias_pron=3, fuente="ECMWF"):
    fechas = pd.date_range(HOY - pd.Timedelta(days=40), HOY - pd.Timedelta(days=1))
    reg = pd.DataFrame([{"Punto": p, "Fecha": f, "T": t, "RH": rh, "V": v, "DIR": 270.0, "PP24": pp,
                         "z_ref": float(m["alt"]), "Fuente": fuente} for p, m in PUNTOS.items() for f in fechas])
    ff = pd.date_range(HOY, HOY + pd.Timedelta(days=dias_pron))
    pr = pd.DataFrame([{"Punto": p, "Fecha": f, "Modelo": "ECMWF", "T": t, "RH": rh, "V": v, "DIR": 270.0,
                        "PP24": pp, "z_ref": float(m["alt"])} for p, m in PUNTOS.items() for f in ff])
    return reg, pr


def test_terreno_coherente():
    t = grilla.cargar_terreno(RUTA)
    v = t["valido"]
    assert v.sum() > 100000
    assert 600 < t["elev"][v].min() < 900 and t["elev"][v].max() > 4000
    assert 0 <= t["fuel"][v].min() and t["fuel"][v].max() <= 1
    (s, o), (n, e) = grilla.limites(t)
    assert -35.1 < s < n < -34.5 and -70.8 < o < e < -70.2


def test_pesos_idw_normalizables_y_cercania():
    lat, lon = np.array([PUNTOS["HLH"]["lat"]]), np.array([PUNTOS["HLH"]["lon"]])
    nombres, w = grilla.pesos_idw(lat, lon)
    assert nombres[int(np.argmax(w[0]))] == "HLH"


def test_clima_seco_da_peligro_alto_y_lluvia_lo_baja():
    reg, pr = _clima()
    seco = grilla.calcular_mapa(reg, pr, HOY, RUTA)
    reg2, pr2 = _clima(t=8.0, rh=95.0, v=3.0, pp=12.0)
    humedo = grilla.calcular_mapa(reg2, pr2, HOY, RUTA)
    comb = seco["combustible"]
    assert len(seco["fechas"]) == 4 and seco["score"].shape[0] == 4
    assert np.nanmedian(seco["score"][0][comb]) > np.nanmedian(humedo["score"][0][comb]) + 20
    assert np.nanmax(humedo["score"][0][comb]) < 30     # lluvia persistente: todo "Bajo"


def test_celdas_sin_combustible_no_se_pintan_y_resumen_suma():
    reg, pr = _clima()
    m = grilla.calcular_mapa(reg, pr, HOY, RUTA)
    t = grilla.cargar_terreno(RUTA)
    assert not m["combustible"][t["fuel"] < grilla.FUEL_MIN].any()
    r = m["resumen"][0]
    assert sum(r[n] for n in fi.CLASS_NAMES) == pytest.approx(r["Ha_combustible"], abs=3)


def test_mas_alto_es_mas_humedo_para_mismo_combustible():
    reg, pr = _clima(t=24.0, rh=35.0, v=8.0)
    m = grilla.calcular_mapa(reg, pr, HOY, RUTA)
    t = grilla.cargar_terreno(RUTA)
    s, z = m["score"][0], t["elev"]
    pasto = np.isin(t["dom"], [11, 12]) & (t["fuel"] > 0.9) & m["combustible"]
    bajo, alto = pasto & (z < 1500), pasto & (z > 2300)
    assert bajo.sum() > 50 and alto.sum() > 50
    assert np.nanmean(s[bajo]) > np.nanmean(s[alto])


def test_faltantes_no_rompen_y_png():
    reg, pr = _clima()
    reg.loc[reg["Punto"] == "HLH", "T"] = np.nan
    reg.loc[reg["Fecha"] == HOY - pd.Timedelta(days=3), ["T", "RH"]] = np.nan   # dia sin ningun dato
    m = grilla.calcular_mapa(reg, pr, HOY, RUTA)
    assert np.isfinite(m["score"][0][m["combustible"]]).all()
    b = grilla.png_base64(m["score"][0], m["combustible"])
    assert len(b) > 100


def test_nieve_apaga_el_peligro_en_altura():
    reg, pr = _clima()
    fechas = pd.date_range(HOY - pd.Timedelta(days=3), HOY + pd.Timedelta(days=3))
    nieve = pd.DataFrame([{"Punto": p, "Fecha": f, "NIEVE": 0.5, "FZL": 2300.0} for p in PUNTOS for f in fechas])
    sin = grilla.calcular_mapa(reg, pr, HOY, RUTA)
    con = grilla.calcular_mapa(reg, pr, HOY, RUTA, nieve=nieve)
    assert sin["nieve"] is None and con["nieve"] is not None
    assert con["resumen"][0]["Ha_nieve"] > 0
    assert con["resumen"][0]["Ha_combustible"] < sin["resumen"][0]["Ha_combustible"]
    assert np.isnan(con["score"][0][con["nieve"][0]]).all()
    assert len(grilla.png_base64(con["score"][0], con["combustible"], con["nieve"][0])) > 100
