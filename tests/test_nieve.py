import numpy as np
import pandas as pd
from ilpi import nieve as nv, fireindex as fi
from ilpi.config import PUNTOS


def _json(snow, fzl, dia="2026-07-10"):
    t = [f"{dia}T{h:02d}:00" for h in range(24)]
    return {"hourly": {"time": t, "snow_depth": [snow] * 24, "freezing_level_height": [fzl] * 24}}


def test_diaria_toma_la_hora_de_referencia():
    d = nv.diaria(_json(0.1, 2200))
    assert len(d) == 1 and d.iloc[0]["NIEVE"] == 0.1 and d.iloc[0]["FZL"] == 2200


def test_diaria_tolera_sufijo_de_modelo_y_nulos():
    j = {"hourly": {"time": ["2026-07-10T15:00"], "snow_depth_gfs_seamless": [0.3], "freezing_level_height_gfs_seamless": [None]}}
    d = nv.diaria(j)
    assert d.iloc[0]["NIEVE"] == 0.3 and np.isnan(d.iloc[0]["FZL"])


def _df(fecha, snow, fzl):
    return pd.DataFrame([{"Punto": p, "Fecha": pd.Timestamp(fecha), "NIEVE": snow, "FZL": fzl} for p in PUNTOS])


def test_cubierta_depende_de_profundidad_y_altitud():
    prof, cota = nv.perfil(_df("2026-07-10", 0.2, 2000), ["2026-07-10"])
    assert cota[0] == 1700
    m = nv.cubierta(prof[0], cota[0], np.array([1000.0, 1700.0, 3000.0]))
    assert list(m) == [False, True, True]


def test_sin_nieve_o_sin_dato_no_cubre():
    prof, cota = nv.perfil(_df("2026-07-10", 0.0, 2000), ["2026-07-10"])
    assert not nv.cubierta(prof[0], cota[0], np.array([3000.0])).any()
    prof, cota = nv.perfil(_df("2026-07-10", 0.5, np.nan), ["2026-07-10"])
    assert not nv.cubierta(prof[0], cota[0], np.array([3000.0])).any()
    prof, cota = nv.perfil(None, ["2026-07-10"])
    assert not nv.cubierta(prof[0], cota[0], np.array([3000.0])).any()


def test_la_nieve_persiste_ventana_de_dias():
    d = pd.concat([_df("2026-07-09", 0.3, 1500), _df("2026-07-10", 0.3, 3500)])
    prof, cota = nv.perfil(d, ["2026-07-10"])
    assert cota[0] == 1200


def test_marcar_puntos_pone_cero_y_clase_baja():
    ilpi = pd.DataFrame([{"Punto": p, "Fecha_Valida": pd.Timestamp("2026-07-10"), "Score": 70.0, "Bruto": 0.7, "Clase": "Alto"} for p in PUNTOS])
    out = nv.marcar_puntos(ilpi, _df("2026-07-10", 0.4, 1800), PUNTOS)     # cota 1500: solo Termas del Flaco (1746 m)
    assert out["Nieve"].sum() == 1
    f = out[out["Nieve"]].iloc[0]
    assert f["Punto"] == "Termas del Flaco" and f["Score"] == 0 and f["Clase"] == fi.CLASS_NAMES[0]
    assert (out[~out["Nieve"]]["Score"] == 70).all()
