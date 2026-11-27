"""Extrae el limite de la cuenca desde la mascara valida de datos/terreno_90m.npz y lo guarda como poligono simple.

Uso: python scripts/preparar_limite.py
Salida: datos/limite_cuenca.json  ->  {"poligonos": [[[lat, lon], ...], ...]}
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ilpi.config import F_GRILLA, F_LIMITE  # noqa: E402


def contornos(valido, origen, celda, tol_celdas=1.0, min_celdas=200):
    import cv2
    mask = (np.asarray(valido) > 0).astype(np.uint8)
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    lon0, lat0 = float(origen[0]), float(origen[1])
    salida = []
    for c in cs:
        if cv2.contourArea(c) < min_celdas:
            continue
        a = cv2.approxPolyDP(c, tol_celdas, True).reshape(-1, 2)
        pts = [[round(lat0 - (y + 0.5) * celda, 5), round(lon0 + (x + 0.5) * celda, 5)] for x, y in a]
        pts.append(pts[0])
        salida.append(pts)
    return salida


if __name__ == "__main__":
    d = np.load(F_GRILLA)
    pol = contornos(d["valido"], d["origen"], float(d["celda"][0]))
    with open(F_LIMITE, "w", encoding="utf-8") as f:
        json.dump({"poligonos": pol, "fuente": "mascara valida del DEM de la cuenca (90 m)"}, f)
    print(f"{len(pol)} poligono(s), {sum(len(p) for p in pol)} vertices -> {F_LIMITE}")
