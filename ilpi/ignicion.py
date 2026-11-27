"""Exposicion a ignicion humana por celda de 90 m, a partir de OpenStreetMap (caminos, edificaciones, lineas electricas).

Es una capa APARTE del peligro meteorologico: dice que tan cerca esta cada celda de las fuentes habituales de ignicion
(transito, viviendas y faenas, lineas de transmision). No se mezcla con el indice.
Exposicion (0-100) = 1 - (1 - p_caminos)(1 - p_edificios)(1 - p_lineas), con p = peso x exp(-distancia / alcance).
Los pesos y alcances son supuestos de partida, sin calibrar.
"""
import time

import numpy as np
import requests

URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"]
CABECERAS = {"User-Agent": "BotonRojoTE/0.3 (indice local de peligro de incendios, Tinguiririca Energia; uso interno)",
             "Accept": "application/json"}
PESO_CAMINO = {"motorway": 0.8, "trunk": 0.8, "primary": 0.8, "secondary": 0.8, "tertiary": 0.8, "unclassified": 0.8,
               "residential": 0.8, "track": 0.5, "service": 0.5}
PESO_LINEA = {"line": 0.6, "minor_line": 0.4}
ALCANCE_M = {"caminos": 300.0, "edificios": 500.0, "lineas": 200.0}   # distancia a la que la probabilidad cae a 37 %
PESO_EDIFICIO = 1.0
PASO_M = 30.0


def consultas(sur, oeste, norte, este):
    bb = f"({sur},{oeste},{norte},{este})"
    hw = "|".join(PESO_CAMINO)
    lineas = f'[out:json][timeout:240];(way["highway"~"^({hw})$"]{bb};way["power"~"^(line|minor_line)$"]{bb};);out geom;'
    edif = f'[out:json][timeout:240];(way["building"]{bb};node["building"]{bb};);out center;'
    return lineas, edif


def descargar(consulta, intentos=5, espera=30, dormir=time.sleep):
    """POST a Overpass con identificacion (User-Agent) y reintentos con espera creciente.
    Los servidores publicos limitan la tasa (HTTP 429/504): se prueba cada espejo y se vuelve a intentar."""
    errores = []
    for i in range(intentos):
        for url in URLS:
            try:
                r = requests.post(url, data={"data": consulta}, headers=CABECERAS, timeout=300)
                if r.status_code == 200:
                    return r.json()
                errores.append(f"{url.split('/')[2]} HTTP {r.status_code}")
            except Exception as e:
                errores.append(f"{url.split('/')[2]} {type(e).__name__}")
        print(f"[OSM] intento {i + 1}/{intentos} fallido: {'; '.join(errores[-len(URLS):])}", flush=True)
        if i < intentos - 1:
            dormir(espera * (i + 1))
    raise RuntimeError("Overpass no respondio: " + "; ".join(errores[-len(URLS):]))


def parsear(json_lineas, json_edif):
    """Devuelve (caminos, lineas, edificios): caminos y lineas = [(peso, [(lat, lon), ...])], edificios = [(lat, lon)]."""
    caminos, lineas, edificios = [], [], []
    for e in json_lineas.get("elements", []):
        g = [(p["lat"], p["lon"]) for p in e.get("geometry", [])]
        t = e.get("tags", {})
        if len(g) < 2:
            continue
        if t.get("power") in PESO_LINEA:
            lineas.append((PESO_LINEA[t["power"]], g))
        elif t.get("highway") in PESO_CAMINO:
            caminos.append((PESO_CAMINO[t["highway"]], g))
    for e in json_edif.get("elements", []):
        c = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        if c:
            edificios.append((c["lat"], c["lon"]))
    return caminos, lineas, edificios


def _marcar(shape, origen, celda, trazos, puntos):
    """Rejilla con el mayor peso de las fuentes que tocan cada celda."""
    h, w = shape
    lon0, lat0 = origen
    M = np.zeros(shape)

    def poner(lat, lon, peso):
        r = np.floor((lat0 - np.asarray(lat)) / celda).astype(int)
        k = np.floor((np.asarray(lon) - lon0) / celda).astype(int)
        ok = (r >= 0) & (r < h) & (k >= 0) & (k < w)
        np.maximum.at(M, (r[ok], k[ok]), peso)

    for peso, g in trazos:
        g = np.array(g)
        for (a, b) in zip(g[:-1], g[1:]):
            largo = np.hypot((b[0] - a[0]) * 111320.0, (b[1] - a[1]) * 111320.0 * np.cos(np.radians(a[0])))
            n = max(int(largo // PASO_M), 1) + 1
            t = np.linspace(0, 1, n)
            poner(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, peso)
    for lat, lon in puntos:
        poner([lat], [lon], PESO_EDIFICIO)
    return M


def _difundir(M, alcance_m, celda_m):
    """max sobre desplazamientos de M * exp(-d / alcance); sin envolver los bordes."""
    R = int(np.ceil(3 * alcance_m / celda_m))
    h, w = M.shape
    out = np.zeros_like(M)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            d = np.hypot(dx, dy) * celda_m
            if d > 3 * alcance_m:
                continue
            f = np.exp(-d / alcance_m)
            ys, yd = (slice(max(dy, 0), h + min(dy, 0)), slice(max(-dy, 0), h + min(-dy, 0)))
            xs, xd = (slice(max(dx, 0), w + min(dx, 0)), slice(max(-dx, 0), w + min(-dx, 0)))
            np.maximum(out[yd, xd], M[ys, xs] * f, out=out[yd, xd])
    return out


def exposicion(shape, origen, celda_deg, caminos, lineas, edificios):
    """Rejilla 0-100 (uint8) de exposicion a ignicion humana."""
    celda_m = celda_deg * 111320.0
    pc = _difundir(_marcar(shape, origen, celda_deg, caminos, []), ALCANCE_M["caminos"], celda_m)
    pl = _difundir(_marcar(shape, origen, celda_deg, lineas, []), ALCANCE_M["lineas"], celda_m)
    pe = _difundir(_marcar(shape, origen, celda_deg, [], edificios), ALCANCE_M["edificios"], celda_m)
    p = 1 - (1 - pc) * (1 - pl) * (1 - pe)
    return np.round(100 * p).astype(np.uint8), (pc, pl, pe)
