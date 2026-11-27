"""Correo diario con el resumen del indice (opcional: se activa solo si estan definidas las variables SMTP_*).

Variables de entorno (secretos del repositorio):
  SMTP_HOST, SMTP_PORT (465 por defecto, SSL), SMTP_USER, SMTP_PASS   cuenta que envia
  EMAIL_DESTINO   direcciones separadas por coma (p. ej. el listado de difusion)
  EMAIL_REMITENTE (opcional, por defecto SMTP_USER)
  EMAIL_MODO      'diario' (por defecto) o 'alerta' (solo si algun punto llega a Alto o mas, o hay tormenta electrica probable)
"""
import html as _h
import os
import smtplib
import ssl
from email.message import EmailMessage

ORDEN = ["Bajo", "Moderado", "Alto", "Muy alto", "Extremo"]
COLOR = {"Bajo": "#2f9e44", "Moderado": "#d9a900", "Alto": "#f08c00", "Muy alto": "#e03131", "Extremo": "#7b1fa2"}
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _tabla(ilpi_hoy):
    e = ilpi_hoy[ilpi_hoy["Modelo"] == "ECMWF"]
    fechas = sorted(e["Fecha_Valida"].unique())
    return e, fechas


def clase_maxima(ilpi_hoy):
    e, _ = _tabla(ilpi_hoy)
    if e.empty:
        return None
    return max(e["Clase"], key=ORDEN.index)


def _texto_tormenta(tormenta):
    """Linea de texto con los dias de tormenta electrica posible o probable; vacio si no hay."""
    if tormenta is None or len(tormenta) == 0:
        return ""
    niv = ["Sin señal", "Posible", "Probable"]
    dias = [f"{niv[int(r.Nivel)].lower()} el {DIAS[r.Fecha.weekday()]} {r.Fecha:%d-%m}" for r in tormenta.itertuples() if r.Nivel >= 1]
    return "Tormenta eléctrica " + ", ".join(dias) if dias else ""


def debe_enviar(ilpi_hoy, modo="diario", tormenta=None):
    if modo != "alerta":
        return True
    c = clase_maxima(ilpi_hoy)
    if c is not None and ORDEN.index(c) >= ORDEN.index("Alto"):
        return True
    return tormenta is not None and len(tormenta) > 0 and bool((tormenta["Nivel"] >= 2).any())


def construir(ilpi_hoy, actualizado, url="", tormenta=None):
    e, fechas = _tabla(ilpi_hoy)
    c = clase_maxima(ilpi_hoy) or "sin datos"
    cab = "".join(f"<th style='padding:6px 10px;background:#E5F5FD'>{DIAS[f.weekday()]} {f:%d-%m}</th>" for f in fechas)
    filas = ""
    for pto in e["Punto"].unique():
        celdas = ""
        for f in fechas:
            g = e[(e["Punto"] == pto) & (e["Fecha_Valida"] == f)]
            if g.empty:
                celdas += "<td style='text-align:center'>–</td>"
            else:
                r = g.iloc[0]
                celdas += (f"<td style='text-align:center;padding:6px 10px'><span style='background:{COLOR[r['Clase']]};color:#fff;"
                           f"border-radius:10px;padding:2px 9px;font-size:12px'>{r['Clase']}</span> {r['Score']:.0f}</td>")
        filas += f"<tr><td style='padding:6px 10px'><b>{_h.escape(str(pto))}</b></td>{celdas}</tr>"
    tt = _texto_tormenta(tormenta)
    bloque_t = (f"<p style='background:#FFF4D6;border-radius:8px;padding:8px 12px'>⚡ <b>{_h.escape(tt)}.</b> Aproximación con la inestabilidad "
                f"del modelo, no un pronóstico de rayos. Una tormenta con combustible seco puede iniciar un fuego.</p>") if tt else ""
    enlace = f"<p><a href='{url}'>Ver el mapa y el detalle</a></p>" if url else ""
    cuerpo = (f"<div style='font-family:Nunito,Arial,sans-serif;color:#414042;max-width:640px'>"
              f"<h2 style='color:#00ABE5;font-weight:400'>Peligro de incendios forestales: máximo {c}</h2>"
              f"<p>Cuenca del río Tinguiririca. Actualizado {actualizado}.</p>{bloque_t}"
              f"<table style='border-collapse:collapse;width:100%;font-size:14px'><tr><th style='text-align:left;padding:6px 10px;background:#E5F5FD'>Punto</th>{cab}</tr>{filas}</table>"
              f"{enlace}"
              f"<p style='font-size:12px;color:#7F7F7F'><b>Experimental.</b> Índice relativo, aún sin calibrar con incendios reales. "
              f"No es un pronóstico oficial; la referencia oficial es CONAF y SENAPRED.</p></div>")
    return f"Peligro de incendios Tinguiririca: {c}", cuerpo


def enviar_si_corresponde(ilpi_hoy, actualizado, env=os.environ, smtp_cls=smtplib.SMTP_SSL, tormenta=None):
    """Devuelve un texto con lo ocurrido (para el log). Nunca lanza: el correo no debe romper la emision."""
    host, destino = env.get("SMTP_HOST", "").strip(), env.get("EMAIL_DESTINO", "").strip()
    if not host or not destino:
        return "sin SMTP_HOST o EMAIL_DESTINO: se omite"
    try:
        modo = env.get("EMAIL_MODO", "diario").strip().lower()
        if not debe_enviar(ilpi_hoy, modo, tormenta):
            return "modo alerta: ningun punto en Alto o superior, no se envia"
        repo = env.get("GITHUB_REPOSITORY", "")
        url = f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if "/" in repo else ""
        asunto, cuerpo = construir(ilpi_hoy, actualizado, url, tormenta)
        usuario = env.get("SMTP_USER", "").strip()
        m = EmailMessage()
        m["Subject"], m["From"] = asunto, env.get("EMAIL_REMITENTE", usuario) or usuario
        m["To"] = ", ".join(x.strip() for x in destino.split(",") if x.strip())
        m.set_content("Este correo requiere un lector con formato HTML.")
        m.add_alternative(cuerpo, subtype="html")
        with smtp_cls(host, int(env.get("SMTP_PORT", "465") or 465), context=ssl.create_default_context()) as s:
            s.login(usuario, env.get("SMTP_PASS", ""))
            s.send_message(m)
        return f"enviado a {m['To'].count('@')} destinatario(s): {asunto}"
    except Exception as e:
        return f"error al enviar: {type(e).__name__}"
