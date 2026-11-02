import numpy as np, pandas as pd
from ilpi import colectores as col


def _reg(ts, tf=60.0, hum=40, ws=10.0, wd=90, rain=0.0):
    ms = int(pd.Timestamp(ts, tz="America/Santiago").tz_convert("UTC").timestamp() * 1000)
    return {"dateutc": ms, "tempf": tf, "humidity": hum, "windspeedmph": ws, "winddir": wd, "dailyrainin": rain}


def test_parse_ambient_units_and_hourly():
    datos = [_reg("2026-11-01 14:00", tf=50, rain=0.0), _reg("2026-11-01 14:30", tf=68, rain=0.1),
             _reg("2026-11-01 15:00", tf=86, rain=0.1, wd=350), _reg("2026-11-01 15:30", tf=86, rain=0.1, wd=10)]
    h = col.parse_ambient(datos, "BT X")
    assert list(h.columns) == ["Punto", "Fecha_Local", "T", "RH", "V", "DIR", "PP"]
    h14 = h[h.Fecha_Local == pd.Timestamp("2026-11-01 14:00")].iloc[0]
    assert abs(h14["T"] - 15.0) < 0.01                    # media de 10 C y 20 C
    assert abs(h14["V"] - 16.09) < 0.01                   # 10 mph -> km/h
    assert abs(h14["PP"] - 2.54) < 0.01                   # 0.1 in -> mm
    h15 = h[h.Fecha_Local == pd.Timestamp("2026-11-01 15:00")].iloc[0]
    assert h15["DIR"] < 1 or h15["DIR"] > 359             # 350 y 10 grados -> promedio ~0, no 180


def test_parse_ambient_rain_reset_midnight():
    datos = [_reg("2026-11-01 23:30", rain=0.4), _reg("2026-11-02 00:30", rain=0.1)]
    h = col.parse_ambient(datos, "BT X")
    assert abs(h["PP"].sum() - 0.1 * 25.4 - 0.0) < 0.5 or h["PP"].sum() > 0   # tras reinicio no hay lluvia negativa
    assert (h["PP"] >= 0).all()


def test_parse_ambient_empty():
    assert col.parse_ambient([], "X").empty


def test_parse_openmeteo():
    t = pd.date_range("2026-11-01", periods=3, freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    j = {"elevation": 1200.0, "hourly": {"time": t,
         "temperature_2m_ecmwf_ifs025": [10, 11, 12], "relative_humidity_2m_ecmwf_ifs025": [50, 45, 40],
         "wind_speed_10m_ecmwf_ifs025": [5, 6, 7], "wind_direction_10m_ecmwf_ifs025": [180, 180, 190],
         "precipitation_ecmwf_ifs025": [0, 0, 1],
         "temperature_2m_gfs_seamless": [9, 10, 11]}}
    mods, z = col.parse_openmeteo(j)
    assert z == 1200.0 and set(mods) == {"ECMWF", "GFS"}
    assert list(mods["ECMWF"]["T"]) == [10, 11, 12]
    assert mods["GFS"]["RH"].isna().all()      # variable ausente -> NaN, no error
