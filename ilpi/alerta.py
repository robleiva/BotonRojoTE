"""Correo diario con el resumen del indice (opcional: se activa solo si estan definidas las variables SMTP_*).

Variables de entorno (secretos del repositorio):
  SMTP_HOST, SMTP_PORT (465 por defecto, SSL), SMTP_USER, SMTP_PASS   cuenta que envia
  EMAIL_DESTINO   direcciones separadas por coma (p. ej. el listado de difusion)
  EMAIL_REMITENTE (opcional, por defecto SMTP_USER)
  EMAIL_MODO      'diario' (por defecto) o 'alerta' (solo si algun punto llega a Alto o mas, )
"""
import datetime as _dt
import html as _h
import os
import xml.etree.ElementTree as ET
from email.utils import format_datetime, parsedate_to_datetime
import smtplib
import ssl
from email.message import EmailMessage

ORDEN = ["Bajo", "Moderado", "Alto", "Muy alto", "Extremo"]
COLOR = {"Bajo": "#2f9e44", "Moderado": "#d9a900", "Alto": "#f08c00", "Muy alto": "#e03131", "Extremo": "#7b1fa2"}
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _cortes():
    from . import fireindex as fi
    return [f"{x:g}" for x in fi.PROV_BREAKS]


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


def debe_enviar(ilpi_hoy, modo="diario", tormenta=None, br=None):
    if modo != "alerta":
        return True
    from . import boton_rojo
    if boton_rojo.hay_boton_rojo(br):
        return True      # Boton Rojo oficial de CONAF en las comunas de interes
    c = clase_maxima(ilpi_hoy)
    if c is not None and ORDEN.index(c) >= ORDEN.index("Alto"):
        return True
    return False   # la tormenta electrica solo se informa en la pagina, no dispara ni aparece en el correo


def _bloque_br(br, fechas, comunas_txt=""):
    """Estado oficial de Boton Rojo (CONAF) para las comunas configuradas; texto de respaldo si no hay dato."""
    gris, base = "#7F7F7F", "font-size:12px;margin:12px 0 0;color:#5b6b76"
    if br is None:
        return (f"<p style='{base}'><b style='font-weight:600'>Botón Rojo CONAF:</b> no se pudo consultar hoy; "
                f"revisar en conaf.cl (Incendios Forestales, Botón Rojo).</p>")
    comunas = sorted({c for d in br.values() for c in d})
    if not comunas:
        return ""
    cab = "".join(f"<th style='font-weight:400;color:#5b6b76;padding:4px 10px;background:#E5F5FD'>{DIAS[f.weekday()]} {f:%d-%m}</th>" for f in fechas)
    filas = ""
    for c in comunas:
        celdas = ""
        for f in fechas:
            v = br.get(f"{f:%Y-%m-%d}", {}).get(c, "x")
            if v == "x" or v is None:
                celdas += f"<td style='text-align:center;padding:4px 10px;color:{gris}'>sin dato</td>"
            elif v["activo"]:
                celdas += (f"<td style='text-align:center;padding:4px 10px'><span style='background:#c92a2a;color:#fff;border-radius:10px;"
                           f"padding:2px 9px;font-size:12px'>Botón Rojo</span> <span style='font-size:11px;color:{gris}'>{v['horas']} de 5 h</span></td>")
            else:
                celdas += f"<td style='text-align:center;padding:4px 10px;color:#2f9e44'>Sin Botón Rojo</td>"
        filas += f"<tr><td style='padding:4px 10px'>{_h.escape(c)}</td>{celdas}</tr>"
    return (f"<p style='{base}'><b style='font-weight:600'>Botón Rojo oficial de CONAF</b> (probabilidad de ignición ≥ 70 % y viento ≥ 20 km/h entre las 14:00 y las 18:59):</p>"
            f"<table style='border-collapse:collapse;width:100%;font-size:13px'><tr><th style='text-align:left;font-weight:400;color:#5b6b76;padding:4px 10px;background:#E5F5FD'>Comuna</th>{cab}</tr>{filas}</table>")


def turno_del_dia(ahora):
    """'manana' si el aviso se genera antes de las 12:00 hora de Chile, 'tarde' si es despues (para planificar el dia siguiente)."""
    from zoneinfo import ZoneInfo
    return "manana" if ahora.astimezone(ZoneInfo("America/Santiago")).hour < 12 else "tarde"


def construir(ilpi_hoy, actualizado, url="", tormenta=None, turno="", br=False):
    e, fechas = _tabla(ilpi_hoy)
    c = clase_maxima(ilpi_hoy) or "sin datos"
    cab = "".join(f"<th style='font-weight:400;color:#5b6b76;padding:6px 10px;background:#E5F5FD'>{DIAS[f.weekday()]} {f:%d-%m}</th>" for f in fechas)
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
        filas += f"<tr><td style='padding:6px 10px'>{_h.escape(str(pto))}</td>{celdas}</tr>"
    # La tormenta electrica (aproximacion por inestabilidad) se muestra solo en la pagina; en el correo puede llevar a confusion.
    bloque_br = "" if br is False else _bloque_br(br, fechas)
    enlace = f"<p style='margin:14px 0 0'><a href='{url}'>Ver el mapa y el detalle</a></p>" if url else ""
    cortes = _cortes()
    rangos = [f"menos de {cortes[0]}", f"{cortes[0]} a {cortes[1]}", f"{cortes[1]} a {cortes[2]}", f"{cortes[2]} a {cortes[3]}", f"{cortes[3]} o más"]
    leyenda = "".join(
        f"<span style='display:inline-block;margin:2px 10px 2px 0;white-space:nowrap'><span style='background:{COLOR[n]};color:#fff;"
        f"border-radius:10px;padding:1px 8px;font-size:11px'>{n}</span> <span style='font-size:11px;color:#7F7F7F'>{r}</span></span>"
        for n, r in zip(ORDEN, rangos))
    bloque_l = (f"<p style='margin:12px 0 0;font-size:11px;color:#7F7F7F'>Índice de 0 a 100: mientras más alto, más favorables son las "
                f"condiciones para que un fuego se inicie y se propague.</p><div style='margin:4px 0 0'>{leyenda}</div>")
    cuerpo = (f"<div style='font-family:Nunito,Arial,sans-serif;color:#414042;max-width:640px'>"
              f"<h2 style='color:#00ABE5;font-weight:400;margin:0 0 4px'>Peligro de incendios forestales: máximo {c}</h2>"
              f"<p style='margin:0 0 12px;color:#7F7F7F;font-size:13px'>Cuenca del río Tinguiririca. Actualizado {actualizado}.</p>"
              f"<table style='border-collapse:collapse;width:100%;font-size:14px'><tr><th style='text-align:left;font-weight:400;color:#5b6b76;padding:6px 10px;background:#E5F5FD'>Punto</th>{cab}</tr>{filas}</table>"
              f"{bloque_br}{bloque_l}{enlace}"
              f"<p style='font-size:11px;color:#7F7F7F;margin:14px 0 0'>Experimental: índice relativo, aún sin calibrar con incendios reales. "
              f"No es un pronóstico oficial; la referencia oficial es CONAF y SENAPRED.</p></div>")
    from . import boton_rojo
    asunto = f"Peligro de incendios Tinguiririca: {c}" + (" · Botón Rojo CONAF" if boton_rojo.hay_boton_rojo(br or None) else "")
    return asunto, cuerpo


def url_pagina(env=os.environ):
    repo = env.get("GITHUB_REPOSITORY", "")
    return f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if "/" in repo else ""


# ------------------------------------------------------------------ fuente RSS para Power Automate
def _leer_items(ruta):
    try:
        raiz = ET.parse(ruta).getroot()
    except (OSError, ET.ParseError):
        return []
    out = []
    for it in raiz.iter("item"):
        d = {k: (it.findtext(k) or "") for k in ("title", "link", "guid", "pubDate", "description")}
        out.append(d)
    return out


def actualizar_feed(ilpi_hoy, actualizado, ruta, hoy, env=os.environ, tormenta=None, ahora=None, max_items=10, br=False):
    """Agrega al archivo RSS (docs/alertas.xml) el aviso del dia si corresponde segun EMAIL_MODO.
    Dos avisos por dia (manana y tarde): repetir la corrida el mismo dia no lo duplica (salvo ALERTA_FORZAR=1, para pruebas).
    Power Automate lee esta fuente y envia el correo desde la cuenta de Outlook de la organizacion. Devuelve texto para el log."""
    try:
        modo = env.get("EMAIL_MODO", "diario").strip().lower() or "diario"
        if not debe_enviar(ilpi_hoy, modo, tormenta, br or None):
            return "modo alerta: ningun punto en Alto o superior ni Boton Rojo, no se agrega aviso"
        ahora = ahora or _dt.datetime.now(_dt.timezone.utc)
        url = url_pagina(env)
        turno = turno_del_dia(ahora)
        asunto, cuerpo = construir(ilpi_hoy, actualizado, url, tormenta, turno, br)
        guid = f"ilpi-{hoy:%Y-%m-%d}-{turno}" + (f"-{ahora:%H%M%S}" if env.get("ALERTA_FORZAR", "").strip() == "1" else "")
        items = _leer_items(ruta)
        if any(i["guid"] == guid for i in items):
            return f"ya hay un aviso para hoy ({guid}): no se duplica"
        # el disparador de Power Automate exige una fecha estrictamente mayor a la del aviso anterior
        if items:
            try:
                previa = parsedate_to_datetime(items[0]["pubDate"])
                if ahora <= previa:
                    ahora = previa + _dt.timedelta(seconds=1)
            except (TypeError, ValueError):
                pass
        nuevo = {"title": asunto, "link": url or "https://github.com", "guid": guid, "pubDate": format_datetime(ahora), "description": cuerpo}
        items = ([nuevo] + items)[:max_items]
        rss = ET.Element("rss", version="2.0")
        ch = ET.SubElement(rss, "channel")
        ET.SubElement(ch, "title").text = "Peligro de incendios forestales · Cuenca del Tinguiririca"
        ET.SubElement(ch, "link").text = url or "https://github.com"
        ET.SubElement(ch, "description").text = "Avisos del Índice Local de Peligro de Incendios (experimental, no oficial)."
        ET.SubElement(ch, "language").text = "es-CL"
        ET.SubElement(ch, "lastBuildDate").text = nuevo["pubDate"]
        for i in items:
            e = ET.SubElement(ch, "item")
            for k in ("title", "link", "pubDate", "description"):
                ET.SubElement(e, k).text = i[k]
            g = ET.SubElement(e, "guid", isPermaLink="false")
            g.text = i["guid"]
        ET.indent(rss)
        ET.ElementTree(rss).write(ruta, encoding="utf-8", xml_declaration=True)
        return f"aviso agregado a {os.path.basename(ruta)}: {asunto}"
    except Exception as e:
        return f"error al actualizar el feed: {type(e).__name__}"


def enviar_si_corresponde(ilpi_hoy, actualizado, env=os.environ, smtp_cls=smtplib.SMTP_SSL, tormenta=None, br=False):
    """Devuelve un texto con lo ocurrido (para el log). Nunca lanza: el correo no debe romper la emision."""
    host, destino = env.get("SMTP_HOST", "").strip(), env.get("EMAIL_DESTINO", "").strip()
    if not host or not destino:
        return "sin SMTP_HOST o EMAIL_DESTINO: se omite"
    try:
        modo = env.get("EMAIL_MODO", "diario").strip().lower()
        if not debe_enviar(ilpi_hoy, modo, tormenta, br or None):
            return "modo alerta: ningun punto en Alto o superior, no se envia"
        url = url_pagina(env)
        asunto, cuerpo = construir(ilpi_hoy, actualizado, url, tormenta, br=br)
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
