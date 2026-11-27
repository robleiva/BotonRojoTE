"""Descarga caminos, edificaciones y lineas electricas de OpenStreetMap y genera datos/ignicion_90m.npz.

Necesita internet (Overpass API). Se ejecuta desde GitHub Actions: flujo "Capa de ignicion (OSM)", a mano, una vez
(y de vez en cuando para actualizar). Uso local: python scripts/preparar_ignicion.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ilpi import ignicion, grilla  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def main():
    ter = grilla.cargar_terreno(RAIZ / "datos" / "terreno_90m.npz")
    (sur, oeste), (norte, este) = grilla.limites(ter)
    q_lin, q_edi = ignicion.consultas(sur, oeste, norte, este)
    caminos, lineas, edificios = ignicion.parsear(ignicion.descargar(q_lin), ignicion.descargar(q_edi))
    print(f"OSM: {len(caminos)} tramos de camino, {len(lineas)} tramos de linea electrica, {len(edificios)} edificaciones")
    if not (caminos or lineas or edificios):
        raise SystemExit("Overpass no devolvio elementos: no se escribe nada")
    exp, _ = ignicion.exposicion(ter["valido"].shape, ter["origen"], ter["celda"], caminos, lineas, edificios)
    exp = np.where(ter["valido"], exp, 0).astype(np.uint8)
    np.savez_compressed(RAIZ / "datos" / "ignicion_90m.npz", exposicion=exp)
    (RAIZ / "datos" / "osm_resumen.json").write_text(json.dumps(
        {"fecha": dt.date.today().isoformat(), "caminos": len(caminos), "lineas": len(lineas), "edificios": len(edificios),
         "fuente": "OpenStreetMap (ODbL), via Overpass API"}, indent=1), encoding="utf-8")
    print(f"celdas con exposicion >= 50: {int((exp >= 50).sum())} de {int(ter['valido'].sum())}")


if __name__ == "__main__":
    main()
