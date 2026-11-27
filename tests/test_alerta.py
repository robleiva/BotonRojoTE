import pandas as pd

from ilpi import alerta


def _df(clase="Alto"):
    return pd.DataFrame({"Punto": ["BT Portillo"] * 2, "Fecha_Valida": pd.to_datetime(["2026-11-26", "2026-11-27"]),
                         "Score": [55.0, 20.0], "Clase": [clase, "Bajo"], "Modelo": ["ECMWF"] * 2})


class _SMTP:
    enviados = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, u, p): self.u = u
    def send_message(self, m): _SMTP.enviados.append(m)


ENV = {"SMTP_HOST": "x", "SMTP_USER": "a@b.cl", "SMTP_PASS": "p", "EMAIL_DESTINO": "lista@empresa.cl, otro@empresa.cl",
       "GITHUB_REPOSITORY": "robleiva/BotonRojoTE"}


def test_sin_configuracion_no_envia():
    assert "omite" in alerta.enviar_si_corresponde(_df(), "hoy", env={}, smtp_cls=_SMTP)


def test_envia_diario_con_aviso_y_enlace():
    _SMTP.enviados.clear()
    r = alerta.enviar_si_corresponde(_df(), "hoy", env=ENV, smtp_cls=_SMTP)
    assert r.startswith("enviado") and len(_SMTP.enviados) == 1
    cuerpo = _SMTP.enviados[0].get_body(("html",)).get_content()
    assert "Experimental" in cuerpo and "robleiva.github.io/BotonRojoTE" in cuerpo


def test_modo_alerta_solo_con_alto():
    _SMTP.enviados.clear()
    env = dict(ENV, EMAIL_MODO="alerta")
    assert "no se envia" in alerta.enviar_si_corresponde(_df("Moderado"), "hoy", env=env, smtp_cls=_SMTP)
    assert alerta.enviar_si_corresponde(_df("Muy alto"), "hoy", env=env, smtp_cls=_SMTP).startswith("enviado")


# ---------------------------------------------------------------- fuente RSS (Power Automate)
def _feed_df(clase="Alto"):
    import pandas as pd
    return pd.DataFrame([{"Modelo": "ECMWF", "Clase": clase, "Punto": "A", "Fecha_Valida": pd.Timestamp("2026-12-20"), "Score": 70.0}])


def test_feed_agrega_un_aviso_por_dia_y_no_duplica(tmp_path):
    import datetime as dt
    import pandas as pd
    import xml.etree.ElementTree as ET
    ruta = str(tmp_path / "alertas.xml")
    hoy = pd.Timestamp("2026-12-20")
    t0 = dt.datetime(2026, 12, 20, 8, 30, tzinfo=dt.timezone.utc)
    r1 = alerta.actualizar_feed(_feed_df(), "x", ruta, hoy, env={}, ahora=t0)
    assert r1.startswith("aviso agregado")
    r2 = alerta.actualizar_feed(_feed_df(), "x", ruta, hoy, env={}, ahora=t0 + dt.timedelta(hours=1))
    assert "no se duplica" in r2
    items = list(ET.parse(ruta).getroot().iter("item"))
    assert len(items) == 1 and "Alto" in items[0].findtext("title") and "<table" in items[0].findtext("description")


def test_feed_fechas_estrictamente_crecientes_y_limite(tmp_path):
    import datetime as dt
    import pandas as pd
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as ET
    ruta = str(tmp_path / "alertas.xml")
    t = dt.datetime(2026, 12, 1, 8, 30, tzinfo=dt.timezone.utc)
    for d in range(12):
        # misma hora exacta cada dia no importa; incluso con reloj retrasado la fecha debe crecer
        alerta.actualizar_feed(_feed_df(), "x", ruta, pd.Timestamp("2026-12-01") + pd.Timedelta(days=d), env={}, ahora=t)
    fechas = [parsedate_to_datetime(i.findtext("pubDate")) for i in ET.parse(ruta).getroot().iter("item")]
    assert len(fechas) == 10 and all(a > b for a, b in zip(fechas, fechas[1:]))


def test_feed_respeta_modo_alerta_y_forzar(tmp_path):
    import datetime as dt
    import pandas as pd
    ruta = str(tmp_path / "alertas.xml")
    hoy, t0 = pd.Timestamp("2026-12-20"), dt.datetime(2026, 12, 20, 8, 30, tzinfo=dt.timezone.utc)
    assert "no se agrega" in alerta.actualizar_feed(_feed_df("Bajo"), "x", ruta, hoy, env={"EMAIL_MODO": "alerta"}, ahora=t0)
    assert not (tmp_path / "alertas.xml").exists()
    alerta.actualizar_feed(_feed_df(), "x", ruta, hoy, env={}, ahora=t0)
    r = alerta.actualizar_feed(_feed_df(), "x", ruta, hoy, env={"ALERTA_FORZAR": "1"}, ahora=t0 + dt.timedelta(minutes=5))
    assert r.startswith("aviso agregado")
