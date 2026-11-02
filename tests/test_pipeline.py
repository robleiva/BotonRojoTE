import numpy as np, pandas as pd
from ilpi import pipeline as pl, fireindex as fi

HOY = pd.Timestamp("2026-11-10")
PUNTOS = {"P1": {"lat": -34.8, "lon": -70.5, "alt": 800}}
TERR = {"P1": {"slope": 15.0, "aspect": 0.0, "fuel_w": 0.85, "ndmi": np.nan}}


def _horario(dias, t=25, rh=25, v=20, pp=0.0):
    idx = pd.date_range("2026-11-01", periods=24 * dias, freq="h")
    return pd.DataFrame({"Fecha_Local": idx, "T": t, "RH": rh, "V": v, "DIR": 180.0, "PP": pp})


def test_clima_15h_pp24_requires_full_series():
    h = _horario(3, pp=0.5)
    c = pl.clima_15h(h)
    assert len(c) == 3
    assert np.isnan(c.iloc[0]["PP24"])                    # primer dia: no hay 24 h previas completas
    assert abs(c.iloc[1]["PP24"] - 12.0) < 1e-9


def _reg(n_dias=8, **kw):
    f = pl.clima_15h(_horario(n_dias + 1, **kw))
    f = f.dropna(subset=["PP24"])
    f = f[f["Fecha"] < HOY].tail(n_dias) if len(f) >= n_dias else f
    # reubica las fechas para que terminen el dia antes de HOY
    f = f.copy(); f["Fecha"] = pd.date_range(HOY - pd.Timedelta(days=len(f)), periods=len(f))
    f["Punto"], f["Fuente"], f["z_ref"] = "P1", "ECMWF", 800.0
    return f


def _pron(**kw):
    f = pl.clima_15h(_horario(6, **kw)).dropna(subset=["PP24"]).head(4).copy()
    f["Fecha"] = pd.date_range(HOY, periods=len(f))
    f["Punto"], f["z_ref"], f["Modelo"] = "P1", 800.0, "ECMWF"
    return f


EST0 = pd.DataFrame(columns=["Punto", "Fecha", "FFMC", "M", "Calidad", "Fuente"])


def test_calcular_sale_completo():
    est, ilpi = pl.calcular(_reg(), _pron(), EST0, TERR, HOY, PUNTOS)
    assert len(est) == 8 and (est["Calidad"] == "ok").all()
    assert len(ilpi) == 4 and list(ilpi["Lead"]) == [0, 1, 2, 3]
    assert ilpi["Score"].between(0, 100).all()
    assert set(ilpi["Clase"]) <= set(fi.CLASS_NAMES)


def test_dia_seco_mas_peligroso_que_humedo():
    _, seco = pl.calcular(_reg(rh=20, t=30, v=25), _pron(rh=20, t=30, v=25), EST0, TERR, HOY, PUNTOS)
    _, hum = pl.calcular(_reg(rh=85, t=12, v=5, pp=0.4), _pron(rh=85, t=12, v=5, pp=0.4), EST0, TERR, HOY, PUNTOS)
    assert seco["Score"].mean() > hum["Score"].mean() + 15


def test_estado_persistente_equivale_a_corrida_continua():
    reg = _reg(10)
    est_full, _ = pl.calcular(reg, _pron(), EST0, TERR, HOY, PUNTOS)
    # corrida en dos partes: primero con 6 dias, luego el resto usando el estado guardado
    parte1 = reg.head(6)
    est1, _ = pl.calcular(parte1, _pron(), EST0, TERR, parte1["Fecha"].max() + pd.Timedelta(days=1), PUNTOS)
    est2, _ = pl.calcular(reg, _pron(), est1, TERR, HOY, PUNTOS)
    union = pd.concat([est1, est2]).drop_duplicates("Fecha")
    assert np.allclose(union.sort_values("Fecha")["FFMC"].values, est_full.sort_values("Fecha")["FFMC"].values)


def test_dia_sin_dato_arrastra_estado():
    reg = _reg(8)
    reg = reg[reg["Fecha"] != reg["Fecha"].iloc[3]]
    est, _ = pl.calcular(reg, _pron(), EST0, TERR, HOY, PUNTOS)
    assert (est["Calidad"] == "sin_dato").sum() == 1
    i = est.index[est["Calidad"] == "sin_dato"][0]
    assert est.loc[i, "FFMC"] == est.loc[i - 1, "FFMC"]


def test_pronostico_con_faltantes_no_rompe():
    p = _pron()
    p.loc[p.index[1], ["V", "RH"]] = np.nan          # el modelo no trae viento/HR un dia
    _, ilpi = pl.calcular(_reg(), p, EST0, TERR, HOY, PUNTOS)
    assert len(ilpi) == 4
    assert (ilpi["Calidad"] == "sin_dato").sum() == 1
    assert ilpi["Score"].notna().all()
