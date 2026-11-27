import datetime as dt

import numpy as np
import pandas as pd

from ilpi import calibracion, reporte
from ilpi import fireindex as fi

META = {"lat": -34.9, "lon": -70.5, "alt": 1450}
TERR = {"slope": 7.0, "aspect": 230.0, "fuel_w": 0.85, "ndmi": np.nan}


def _horario(anios=3, semilla=1):
    r = np.random.default_rng(semilla)
    t = pd.date_range("2000-07-01", periods=24 * 365 * anios, freq="h")
    est = np.cos((t.dayofyear.to_numpy() - 15) / 365 * 2 * np.pi)          # verano = 1
    return pd.DataFrame({"Fecha_Local": t, "T": 14 + 10 * est + 6 * np.sin((t.hour - 9) / 24 * 2 * np.pi) + r.normal(0, 1, len(t)),
                         "RH": np.clip(55 - 25 * est + r.normal(0, 8, len(t)), 5, 100), "V": np.abs(r.normal(8, 4, len(t))),
                         "DIR": r.uniform(0, 360, len(t)), "PP": np.where(r.random(len(t)) < 0.02 * (1.5 - est), r.exponential(2, len(t)), 0.0)})


def test_serie_y_cortes_crecientes():
    s = calibracion.serie_indice(_horario(), 1500.0, META, TERR)
    assert s["Score"].between(0, 100).all()
    res = calibracion.armar_resultado({"A": s, "B": s}, "2000-07-01 a 2003-06-30")
    c = res["cortes"]
    assert len(c) == 4 and all(a < b for a, b in zip(c, c[1:])) and res["dias_temporada"] > 300


def test_cortes_solo_cuenta_temporada():
    f = pd.date_range("2001-01-01", periods=365)
    sc = np.where(f.month.isin(calibracion.MESES_TEMPORADA), 80.0, 0.0)       # invierno = 0 no debe bajar los percentiles
    c, n = calibracion.cortes(sc, f)
    assert c == [80.0] * 4 and n == int(f.month.isin(calibracion.MESES_TEMPORADA).sum())


def test_descargar_reintenta_429(monkeypatch):
    llamadas = []

    class R:
        def __init__(self, c): self.status_code = c
        def json(self): return {"elevation": 1234, "hourly": {"time": ["2000-07-01T00:00"], "temperature_2m": [5.0], "relative_humidity_2m": [60],
                                                              "wind_speed_10m": [3], "wind_direction_10m": [90], "precipitation": [0]}}

    def get(url, params=None, headers=None, timeout=None):
        llamadas.append(params["start_date"])
        if len(llamadas) == 1:
            raise calibracion.requests.exceptions.ReadTimeout()
        return R(429 if len(llamadas) == 2 else 200)

    monkeypatch.setattr(calibracion.requests, "get", get)
    d, z = calibracion.descargar_punto(-34.9, -70.5, dt.date(2000, 7, 1), dt.date(2001, 12, 31), dormir=lambda s: None)
    assert z == 1234 and len(d) == 2 and len(llamadas) == 4      # 1 timeout + 1 HTTP 429 + 2 tramos anuales


def test_pagina_muestra_clases_calibradas(monkeypatch):
    monkeypatch.setattr(fi, "CALIBRACION", {"periodo": "2000-07-01 a 2026-11-17", "dias_temporada": 4500, "cortes": [40, 52, 63, 71]})
    monkeypatch.setattr(fi, "PROV_BREAKS", [40.0, 52.0, 63.0, 71.0])
    assert reporte._umbral()["Extremo"] == "≥ 71" and "percentiles" in reporte._texto_clases()
    assert "3 %" in reporte._explicacion()


def test_sin_archivo_usa_cortes_base():
    assert fi.PROV_BREAKS_BASE == [30, 50, 65, 80]
