"""Genera datos/terreno_90m.npz a partir de los TIFF de la tesis (DEM 30 m y cobertura WorldCover 10 m).

Uso (una sola vez, o cuando cambien los TIFF):
    python scripts/preparar_terreno.py RUTA_CARPETA_TESIS

Salida liviana (unos pocos MB) que SI va al repositorio; los TIFF originales no.
Requiere solo numpy y Pillow.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
F = 3  # DEM 30 m -> celda de 90 m (y cobertura 10 m -> bloques de 9 x 9)

# ESA WorldCover -> peso de combustible (provisorio; ver ESPECIFICACION.md)
PESO = {10: 0.50, 20: 0.85, 30: 1.00, 40: 0.40, 50: 0.0, 60: 0.10, 70: 0.0, 80: 0.0, 100: 0.30}


def main(carpeta):
    carpeta = Path(carpeta)
    dem = np.array(Image.open(carpeta / "DEM_Cuenca_Tinguiririca_30m.tif")).astype(float)
    lc = np.array(Image.open(carpeta / "LandCover_Cuenca_Tinguiririca_10m.tif"))
    sc_d, tie_d = 0.0002694945852358564, (-70.72628295120954, -34.58572316426582)
    sc_l, tie_l = 8.983152841195215e-05, (-70.72632372537745, -34.58588200439074)
    dem[dem <= 0] = np.nan

    H, W = (dem.shape[0] // F) * F, (dem.shape[1] // F) * F
    dem = dem[:H, :W]
    # alinear la cobertura con el DEM (esta ~1,8 pixeles de 10 m mas al norte)
    pad = int(round((tie_l[1] - tie_d[1]) / sc_l)) * -1
    lc = np.pad(lc, ((pad, 0), (0, 0)))[: H * F, : W * F]
    if lc.shape != (H * F, W * F):
        lc = np.pad(lc, ((0, H * F - lc.shape[0]), (0, W * F - lc.shape[1])))

    lat_c = tie_d[1] - (H / 2) * sc_d
    my = sc_d * 111320.0
    mx = my * np.cos(np.radians(lat_c))
    gy, gx = np.gradient(dem)
    ex, ny = gx / mx, -gy / my  # derivada hacia el este y hacia el norte

    def bloque(a):
        return a.reshape(H // F, F, W // F, F).transpose(0, 2, 1, 3).reshape(H // F, W // F, F * F)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        elev = np.nanmean(bloque(dem), axis=2)
        n_ok = np.sum(np.isfinite(bloque(dem)), axis=2)
        e_m, n_m = np.nanmean(bloque(ex), axis=2), np.nanmean(bloque(ny), axis=2)
    valido = n_ok >= 5
    pend = np.degrees(np.arctan(np.hypot(e_m, n_m)))
    asp = np.degrees(np.arctan2(-e_m, -n_m)) % 360          # hacia donde mira la ladera
    asp = np.where(pend < 2.0, -1, asp)                      # terreno plano: sin exposicion

    # combustible: peso medio ponderado por area dentro de cada celda de 90 m
    b = lc.reshape(H // F, F * 3, W // F, F * 3).transpose(0, 2, 1, 3).reshape(H // F, W // F, -1)
    peso, n_cob = np.zeros(b.shape[:2]), np.zeros(b.shape[:2])
    cuenta = {}
    for k, w in PESO.items():
        c = (b == k).sum(axis=2)
        cuenta[k] = c
        peso += w * c
        n_cob += c
    fuel = np.where(n_cob > 0, peso / np.maximum(n_cob, 1), 0.0)
    clases = sorted(PESO)
    dom = np.array(clases)[np.argmax(np.stack([cuenta[k] for k in clases]), axis=0)]
    dom = np.where(n_cob > 0, dom, 0)

    out = Path(__file__).resolve().parents[1] / "datos" / "terreno_90m.npz"
    np.savez_compressed(
        out,
        elev=np.where(valido, np.round(elev), 0).astype(np.int16),
        slope=np.where(valido, np.round(pend), 0).astype(np.uint8),
        aspect=np.where(valido, np.round(asp), -1).astype(np.int16),
        fuel=np.where(valido, np.round(100 * fuel), 0).astype(np.uint8),
        dom=np.where(valido, dom, 0).astype(np.uint8),
        valido=valido,
        origen=np.array([tie_d[0], tie_d[1]]),
        celda=np.array([sc_d * F]),
    )
    print(f"{out} ({out.stat().st_size/1e6:.2f} MB) | celdas {valido.shape}, validas {int(valido.sum())}")
    print("altitud", float(np.nanmin(elev)), float(np.nanmax(elev)), "| peso medio", round(float(fuel[valido].mean()), 2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
