import json, os
import numpy as np, pandas as pd
from ilpi import run_daily as rd, colectores as col


def _horario(ini, fin, semilla=0):
    r = np.random.default_rng(semilla)
    idx = pd.date_range(ini, fin, freq="h")
    h = idx.hour.values
    d = pd.DataFrame({"Fecha_Local": idx})
    d["T"] = 18 + 9 * np.sin((h - 9) / 24 * 2 * np.pi) + r.normal(0, 1, len(d))
    d["RH"] = np.clip(45 - 20 * np.sin((h - 9) / 24 * 2 * np.pi) + r.normal(0, 5, len(d)), 10, 100)
    d["V"] = np.abs(r.normal(12, 5, len(d)))
    d["DIR"] = r.uniform(0, 360, len(d))
    d["PP"] = np.where(r.random(len(d)) < 0.01, r.exponential(2, len(d)), 0.0)
    return d


def _preparar(monkeypatch, tmp_path):
    for nom, sub in [("HIST", "historico"), ("DOCS", "docs"), ("DATOS", "datos")]:
        os.makedirs(tmp_path / sub, exist_ok=True)
        monkeypatch.setattr(rd, nom, str(tmp_path / sub))
    monkeypatch.setattr(rd, "F_OBS", str(tmp_path / "historico/obs_estaciones.csv"))
    monkeypatch.setattr(rd, "F_REG", str(tmp_path / "historico/clima_registrado.csv"))
    monkeypatch.setattr(rd, "F_PRON", str(tmp_path / "historico/clima_pronostico.csv"))
    monkeypatch.setattr(rd, "F_ESTADO", str(tmp_path / "historico/estado_ffmc.csv"))
    monkeypatch.setattr(rd, "F_ILPI", str(tmp_path / "historico/ilpi_diario.csv"))
    monkeypatch.setattr(rd, "F_TERRENO", str(tmp_path / "datos/puntos_terreno.csv"))
    pd.DataFrame({"Punto": list(rd.PUNTOS), "slope": 12.0, "aspect": np.nan, "fuel_class": "matorral", "ndmi": np.nan}
                 ).to_csv(tmp_path / "datos/puntos_terreno.csv", index=False)
    hoy = pd.Timestamp.now(tz=rd.ZONA).tz_localize(None).normalize()

    def fake_om(lat, lon, past_days, forecast_days=4):
        d = _horario(hoy - pd.Timedelta(days=past_days), hoy + pd.Timedelta(days=forecast_days) - pd.Timedelta(hours=1), 1)
        return {"ECMWF": d, "GFS": d.assign(T=d["T"] + 1.0)}, 1500.0

    def fake_amb(mac, nombre, api, app, limit=576):
        d = _horario(hoy - pd.Timedelta(days=5), hoy - pd.Timedelta(hours=1), 2)
        d.insert(0, "Punto", nombre)
        return d

    monkeypatch.setattr(rd.col, "fetch_openmeteo", fake_om)
    monkeypatch.setattr(rd.col, "fetch_ambient", fake_amb)
    monkeypatch.setenv("USAR_WRF", "0")
    monkeypatch.setenv("MAC_PORTILLO", "AA:BB:CC:DD:EE:01")
    monkeypatch.setenv("MAC_TINGUIRIRICA", "AA:BB:CC:DD:EE:02")
    return hoy


def test_corrida_completa_e_idempotente(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    rd.main()
    h = tmp_path / "historico"
    for f in ["obs_estaciones", "clima_registrado", "clima_pronostico", "estado_ffmc", "ilpi_diario"]:
        assert (h / f"{f}.csv").exists(), f
    ilpi = pd.read_csv(h / "ilpi_diario.csv")
    assert set(ilpi["Modelo"]) == {"ECMWF", "GFS"} and set(ilpi["Lead"]) == {0, 1, 2, 3}
    assert ilpi["Score"].between(0, 100).all() and ilpi["Punto"].nunique() == len(rd.PUNTOS)
    reg = pd.read_csv(h / "clima_registrado.csv")
    assert set(reg.loc[reg.Punto == "BT Portillo", "Fuente"]) >= {"ESTACION"}      # la estacion prima sobre el modelo
    assert (reg.loc[reg.Punto == "HLH", "Fuente"] == "ECMWF").all()
    est1 = pd.read_csv(h / "estado_ffmc.csv")
    assert est1.groupby("Punto").size().min() >= 55                                  # spin-up de ~60 dias
    html = (tmp_path / "docs/index.html").read_text()
    assert "EXPERIMENTAL" in html and "Mi Casa" not in html
    js = json.loads((tmp_path / "docs/ilpi_ultimo.json").read_text())
    assert js["experimental"] and len(js["indice"]) == len(ilpi)
    # segunda corrida el mismo dia: no duplica nada y el estado no cambia
    rd.main()
    assert len(pd.read_csv(h / "ilpi_diario.csv")) == len(ilpi)
    est2 = pd.read_csv(h / "estado_ffmc.csv")
    assert len(est2) == len(est1) and np.allclose(est1["FFMC"], est2["FFMC"])


def test_sin_openmeteo_no_modifica_estado(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    monkeypatch.setattr(rd.col, "fetch_openmeteo", lambda *a, **k: ({}, np.nan))
    try:
        rd.main(); ok = False
    except SystemExit:
        ok = True
    assert ok and not (tmp_path / "historico/estado_ffmc.csv").exists()
