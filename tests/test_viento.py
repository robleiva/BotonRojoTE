import numpy as np
import pandas as pd
from ilpi import viento as vi


def _datos(n, obs_v, mod_v, punto="BT Tinguiririca"):
    dias = pd.date_range("2026-10-01", periods=n)
    horas = pd.date_range(dias[0], dias[-1] + pd.Timedelta(hours=23), freq="h")
    obs = pd.DataFrame({"Punto": punto, "Fecha_Local": horas, "T": 10.0, "RH": 50.0, "V": obs_v, "DIR": 270.0, "PP": 0.0})
    pron = pd.DataFrame({"Punto": punto, "Fecha": dias, "Emision": dias, "Modelo": "ECMWF", "V": mod_v})
    return obs, pron


def test_con_30_dias_da_la_razon_mediana():
    obs, pron = _datos(35, 30.0, 10.0)
    fac, info = vi.factores(obs, pron, ["BT Tinguiririca"], altura_m=10.0)
    assert abs(fac["BT Tinguiririca"] - 3.0) < 1e-9 and info["BT Tinguiririca"][0] >= 30


def test_con_pocos_dias_no_corrige_pero_informa():
    obs, pron = _datos(10, 30.0, 10.0)
    fac, info = vi.factores(obs, pron, ["BT Tinguiririca"], altura_m=10.0)
    assert fac == {} and info["BT Tinguiririca"][0] == 10


def test_factor_acotado():
    obs, pron = _datos(40, 100.0, 10.0)
    assert vi.factores(obs, pron, ["BT Tinguiririca"], altura_m=10.0)[0]["BT Tinguiririca"] == vi.F_MAX


def test_sin_datos_o_sin_viento_de_estacion():
    assert vi.factores(pd.DataFrame(), pd.DataFrame(), ["BT Portillo"]) == ({}, {})
    obs, pron = _datos(40, np.nan, 10.0)
    assert vi.factores(obs, pron, ["BT Tinguiririca"], altura_m=10.0) == ({}, {})


def test_aplicar_no_toca_estaciones_ni_otros_puntos_ni_el_original():
    df = pd.DataFrame({"Punto": ["A", "A", "B"], "Fuente": ["ECMWF", "ESTACION", "ECMWF"], "V": [10.0, 10.0, 10.0]})
    out = vi.aplicar(df, {"A": 2.0})
    assert list(out["V"]) == [20.0, 10.0, 10.0] and list(df["V"]) == [10.0] * 3


def test_lleva_el_viento_de_2_m_a_10_m():
    assert abs(float(vi.a_10m(10.0, 2.0)) - 10.0 * 5 ** (1 / 7)) < 1e-9
    assert float(vi.a_10m(10.0, 10.0)) == 10.0
    obs, pron = _datos(40, 20.0, 10.0)
    f10 = vi.factores(obs, pron, ["BT Tinguiririca"], altura_m=10.0)[0]["BT Tinguiririca"]
    f2 = vi.factores(obs, pron, ["BT Tinguiririca"], altura_m=2.0)[0]["BT Tinguiririca"]
    assert abs(f2 / f10 - 5 ** (1 / 7)) < 1e-9
