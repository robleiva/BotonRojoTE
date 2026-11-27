"""Estado oficial de Boton Rojo (CONAF) por comuna.

CONAF publica una capa publica (ArcGIS) con las comunas donde se cumple la condicion de Boton Rojo
(probabilidad de ignicion >= 70 % y viento >= 20 km/h entre las 14:00 y las 18:59), por fecha y por hora
(horas 1 a 5 de esa ventana), para hoy y los 4 dias siguientes. Solo aparecen las comunas con Boton Rojo:
si hay filas para una fecha pero no para la comuna, la comuna NO esta en Boton Rojo ese dia.
Si no hay filas para la fecha, el dato no se publico y se informa 'sin dato' (nunca se asume 'sin Boton Rojo').
"""
import json
import unicodedata
import urllib.parse
import urllib.request

URL = "https://services5.arcgis.com/A1ELWse9bRAi2JiV/arcgis/rest/services/Boton_Rojo/FeatureServer/0/query"
CAMPOS = "com,reg,date,horas,SUM_br_ha,proportion"


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "ilpi-tinguiririca"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def descargar(http_get=_http_get):
    """Devuelve la lista de filas (dict) de la capa. Lanza excepcion si la consulta falla."""
    q = urllib.parse.urlencode({"f": "json", "where": "1=1", "outFields": CAMPOS, "returnGeometry": "false"})
    j = http_get(f"{URL}?{q}")
    if "error" in j or "features" not in j:
        raise RuntimeError("respuesta invalida de CONAF")
    return [f["attributes"] for f in j["features"]]


def resumir(filas, comunas, fechas):
    """{fecha 'YYYY-MM-DD': {comuna: None (sin dato) | {'activo': bool, 'horas': n, 'prop': 0-1}}}"""
    objetivo = {_norm(c): c for c in comunas}
    fechas_pub = {str(f.get("date")) for f in filas}
    out = {}
    for fecha in fechas:
        out[fecha] = {}
        for k, nombre in objetivo.items():
            if fecha not in fechas_pub:
                out[fecha][nombre] = None
                continue
            propias = [f for f in filas if str(f.get("date")) == fecha and _norm(f.get("com")) == k]
            horas = {int(f["horas"]) for f in propias if f.get("horas") is not None}
            prop = max([float(f.get("proportion") or 0) for f in propias] or [0.0])
            out[fecha][nombre] = {"activo": bool(propias), "horas": len(horas), "prop": prop}
    return out


def consultar(comunas, fechas, http_get=_http_get):
    """Nunca lanza: devuelve None si no se pudo consultar (el correo lo informa como 'no disponible')."""
    try:
        return resumir(descargar(http_get), comunas, [str(f) for f in fechas])
    except Exception:
        return None


def hay_boton_rojo(br, dias=2):
    """True si alguna comuna esta en Boton Rojo en los primeros `dias` dias publicados."""
    if not br:
        return False
    for fecha in sorted(br)[:dias]:
        if any(v and v["activo"] for v in br[fecha].values()):
            return True
    return False
