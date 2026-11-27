import numpy as np
import pandas as pd
from ilpi import rayos as ry, alerta, reporte


def _json(cape_tarde, li_tarde=None, dia="2026-12-20"):
    t = [f"{dia}T{h:02d}:00" for h in range(24)]
    cape = [cape_tarde if 12 <= h <= 20 else 0.0 for h in range(24)]
    li = [li_tarde if 12 <= h <= 20 else 5.0 for h in range(24)]
    return {"hourly": {"time": t, "cape": cape, "lifted_index": li if li_tarde is not None else [None] * 24}}


def test_diaria_toma_la_ventana_de_la_tarde():
    d = ry.diaria(_json(650.0, -1.0))
    assert d.iloc[0]["CAPE"] == 650.0 and d.iloc[0]["LI"] == -1.0


def test_niveles():
    assert ry.nivel(100, 3) == 0
    assert ry.nivel(400, 0) == 1
    assert ry.nivel(900, -3) == 2
    assert ry.nivel(900, 1) == 1            # CAPE alta pero atmosfera estable segun el indice de elevacion
    assert ry.nivel(900, np.nan) == 2       # sin indice de elevacion se decide solo por CAPE
    assert ry.nivel(np.nan, -5) == 0        # sin CAPE no se alerta


def test_por_dia_toma_el_peor_punto_y_filtra_fechas():
    df = pd.DataFrame([{"Punto": "A", "Fecha": "2026-12-20", "CAPE": 100.0, "LI": 2.0},
                       {"Punto": "B", "Fecha": "2026-12-20", "CAPE": 900.0, "LI": -3.0},
                       {"Punto": "A", "Fecha": "2026-12-10", "CAPE": 900.0, "LI": -3.0}])
    d = ry.por_dia(df, desde="2026-12-15")
    assert len(d) == 1 and d.iloc[0]["Nivel"] == 2
    assert ry.por_dia(None).empty


def test_correo_no_incluye_tormenta_ni_el_modo_alerta_la_considera():
    t = pd.DataFrame({"Fecha": [pd.Timestamp("2026-12-20")], "CAPE": [900.0], "LI": [-3.0], "Nivel": [2]})
    assert "probable" in alerta._texto_tormenta(t)
    bajo = pd.DataFrame([{"Modelo": "ECMWF", "Clase": "Bajo", "Punto": "A", "Fecha_Valida": pd.Timestamp("2026-12-20"), "Score": 10.0}])
    assert not alerta.debe_enviar(bajo, "alerta")
    assert not alerta.debe_enviar(bajo, "alerta", t)
    asunto, cuerpo = alerta.construir(bajo, "x", "", t)
    assert "tormenta" not in cuerpo.lower()


def test_seccion_de_pagina():
    t = pd.DataFrame({"Fecha": [pd.Timestamp("2026-12-20"), pd.Timestamp("2026-12-21")], "CAPE": [900.0, 50.0], "LI": [-3.0, 4.0], "Nivel": [2, 0]})
    h = reporte._tormenta(t)
    assert "Probable" in h and "Sin señal" in h and "class='torm'" in h
    assert reporte._tormenta(None) == "" and "class='torm'" not in reporte._tormenta(t.iloc[1:])
