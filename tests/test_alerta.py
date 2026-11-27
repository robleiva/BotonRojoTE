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
