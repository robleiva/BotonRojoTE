import pandas as pd
from ilpi import firms

CSV = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
       "-34.80,-70.50,330.1,0.4,0.4,2026-12-01,1342,N,VIIRS,n,2.0NRT,290.0,3.2,D\n"
       "-34.81,-70.51,340.0,0.4,0.4,2026-12-01,0215,N,VIIRS,h,2.0NRT,291.0,8.9,N\n")


def test_parse_csv_ok_y_vacios():
    d = firms.parse_csv(CSV, "VIIRS_SNPP_NRT")
    assert len(d) == 2 and list(d.columns) == firms.COLS and (d["Fuente"] == "VIIRS_SNPP_NRT").all()
    assert firms.parse_csv("", "X").empty
    assert firms.parse_csv("Invalid MAP_KEY", "X").empty                       # respuesta de error no es CSV
    assert firms.parse_csv("latitude,longitude,acq_date\n", "X").empty        # sin focos


def test_acumular_no_duplica_y_conserva_ceros_de_hora():
    a = firms.parse_csv(CSV, "VIIRS_SNPP_NRT")
    b = firms.acumular(a, pd.DataFrame())
    c = firms.acumular(a, b)
    assert len(c) == 2 and (c["acq_time"].str.len() == 4).all()


def test_fuente_que_falla_no_impide_las_demas(monkeypatch):
    def falso(key, fuente, hoy, dias=5, **k):
        if fuente == "MODIS_NRT":
            raise RuntimeError("boom")
        return firms.parse_csv(CSV, fuente)
    monkeypatch.setattr(firms, "fetch", falso)
    d, errores = firms.fetch_todas("k", pd.Timestamp("2026-12-01"))
    assert len(errores) == 1 and "MODIS_NRT" in errores[0] and len(d) == 6
