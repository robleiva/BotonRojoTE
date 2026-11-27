import pandas as pd

from ilpi import alerta, boton_rojo as b

FILAS = [
    {"com": "Pozo Almonte", "reg": "Tarapacá", "date": "2026-11-27", "horas": 1, "SUM_br_ha": 10.0, "proportion": 0.01},
    {"com": "Chimbarongo", "reg": "O'Higgins", "date": "2026-11-28", "horas": 3, "SUM_br_ha": 500.0, "proportion": 0.2},
    {"com": "Chimbarongo", "reg": "O'Higgins", "date": "2026-11-28", "horas": 4, "SUM_br_ha": 800.0, "proportion": 0.35},
]


def _df():
    return pd.DataFrame({"Punto": ["BT Portillo"] * 2, "Fecha_Valida": pd.to_datetime(["2026-11-27", "2026-11-28"]),
                         "Score": [40.0, 41.0], "Clase": ["Bajo", "Bajo"], "Modelo": ["ECMWF"] * 2})


def test_comuna_ausente_es_sin_boton_rojo_si_la_fecha_esta_publicada():
    r = b.resumir(FILAS, ["San Fernando", "Chimbarongo"], ["2026-11-27", "2026-11-28"])
    assert r["2026-11-27"]["San Fernando"] == {"activo": False, "horas": 0, "prop": 0.0}
    assert r["2026-11-28"]["Chimbarongo"]["activo"] and r["2026-11-28"]["Chimbarongo"]["horas"] == 2
    assert r["2026-11-28"]["Chimbarongo"]["prop"] == 0.35


def test_fecha_no_publicada_es_sin_dato_nunca_sin_boton_rojo():
    r = b.resumir(FILAS, ["San Fernando"], ["2026-12-05"])
    assert r["2026-12-05"]["San Fernando"] is None


def test_nombres_con_tildes_y_mayusculas():
    filas = [{"com": "CHIMBARONGO", "date": "2026-11-27", "horas": 1, "proportion": 0.1}]
    assert b.resumir(filas, ["Chimbarongo"], ["2026-11-27"])["2026-11-27"]["Chimbarongo"]["activo"]


def test_consultar_nunca_lanza():
    def malo(url): raise OSError("sin red")
    assert b.consultar(["San Fernando"], ["2026-11-27"], http_get=malo) is None
    assert b.consultar(["San Fernando"], ["2026-11-27"], http_get=lambda u: {"error": {}}) is None
    ok = b.consultar(["San Fernando"], ["2026-11-27"], http_get=lambda u: {"features": [{"attributes": FILAS[0]}]})
    assert ok["2026-11-27"]["San Fernando"]["activo"] is False


def test_correo_muestra_estado_y_asunto_cuando_hay_boton_rojo():
    br = b.resumir(FILAS, ["San Fernando", "Chimbarongo"], ["2026-11-27", "2026-11-28"])
    asunto, cuerpo = alerta.construir(_df(), "hoy", br=br)
    assert "Botón Rojo CONAF" in asunto
    assert "Sin Botón Rojo" in cuerpo and "2 de 5 h" in cuerpo and "San Fernando" in cuerpo


def test_correo_sin_boton_rojo_no_cambia_asunto():
    br = b.resumir(FILAS[:1], ["San Fernando"], ["2026-11-27"])
    asunto, cuerpo = alerta.construir(_df(), "hoy", br=br)
    assert asunto.endswith("Bajo") and "Sin Botón Rojo" in cuerpo


def test_correo_avisa_si_no_se_pudo_consultar():
    _, cuerpo = alerta.construir(_df(), "hoy", br=None)
    assert "no se pudo consultar" in cuerpo


def test_modo_alerta_se_dispara_por_boton_rojo_aunque_el_indice_sea_bajo():
    br = b.resumir(FILAS, ["Chimbarongo"], ["2026-11-27", "2026-11-28"])
    assert alerta.debe_enviar(_df(), "alerta", None, br) is True
    assert alerta.debe_enviar(_df(), "alerta", None, None) is False


def test_pagina_muestra_boton_rojo_por_comuna():
    from ilpi import reporte
    fechas = list(pd.to_datetime(["2026-11-27", "2026-11-28", "2026-12-05"]))
    br = b.resumir(FILAS, ["San Fernando", "Chimbarongo"], ["2026-11-27", "2026-11-28", "2026-12-05"])
    h = reporte._boton_rojo(br, fechas)
    assert "Botón Rojo oficial de CONAF" in h and "San Fernando" in h and "Chimbarongo" in h
    assert "2 de 5 h" in h and "35 % de la comuna" in h and "Sin Botón Rojo" in h and "sin dato" in h
    assert "C92A2A" in h and "🔴" in h


def test_pagina_sin_boton_rojo_activo_y_con_consulta_fallida():
    from ilpi import reporte
    fechas = list(pd.to_datetime(["2026-11-27"]))
    h = reporte._boton_rojo(b.resumir(FILAS[:1], ["San Fernando"], ["2026-11-27"]), fechas)
    assert "🔴" not in h and "Sin Botón Rojo" in h
    assert "No se pudo consultar" in reporte._boton_rojo(None, fechas)
    assert reporte._boton_rojo(False, fechas) == ""
