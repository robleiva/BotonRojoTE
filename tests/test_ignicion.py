import numpy as np

from ilpi import ignicion

ORIGEN, CELDA = (-70.5, -34.8), 0.0008083   # ~90 m


def _json():
    lin = {"elements": [
        {"type": "way", "tags": {"highway": "primary"}, "geometry": [{"lat": -34.8 - 0.0008 * 10.5, "lon": -70.5 + CELDA * i} for i in range(5, 35)]},
        {"type": "way", "tags": {"highway": "footway"}, "geometry": [{"lat": -34.801, "lon": -70.5}, {"lat": -34.802, "lon": -70.5}]},
        {"type": "way", "tags": {"power": "line"}, "geometry": [{"lat": -34.8 - CELDA * i, "lon": -70.5 + CELDA * 30.5} for i in range(5, 35)]}]}
    edi = {"elements": [{"type": "way", "center": {"lat": -34.8 - CELDA * 40.5, "lon": -70.5 + CELDA * 40.5}},
                        {"type": "node", "lat": -34.8 - CELDA * 41.5, "lon": -70.5 + CELDA * 41.5}]}
    return lin, edi


def test_parsear_ignora_sendas_y_cuenta_fuentes():
    c, l, e = ignicion.parsear(*_json())
    assert len(c) == 1 and len(l) == 1 and len(e) == 2


def test_exposicion_cae_con_la_distancia():
    c, l, e = ignicion.parsear(*_json())
    exp, (pc, pl, pe) = ignicion.exposicion((60, 60), ORIGEN, CELDA, c, l, e)
    assert exp.dtype == np.uint8
    assert pc[10, 20] > 0.7 and pc[10, 20] > pc[10 + 4, 20] > pc[10 + 10, 20]    # sobre el camino y alejandose
    assert pl[20, 30] > 0.5 and pe[40, 40] > 0.9
    assert exp[10, 20] > exp[55, 5]                                            # lejos de todo: casi cero
    assert exp.max() <= 100


def test_capa_en_el_mapa_y_en_la_pagina(tmp_path):
    import pandas as pd
    from ilpi import grilla, reporte
    ter = grilla.cargar_terreno("datos/terreno_90m.npz")
    e = np.zeros(ter["valido"].shape, np.uint8)
    e[200:210, 200:210] = 90
    f = tmp_path / "ign.npz"
    np.savez_compressed(f, exposicion=e)
    assert grilla.cargar_ignicion(str(f), ter["valido"]).max() == 90
    assert grilla.cargar_ignicion(str(tmp_path / "no.npz"), ter["valido"]) is None
    assert grilla.png_ignicion_base64(e)
