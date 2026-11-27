"""Genera datos/terreno_90m.npz a partir de los TIFF de la tesis (DEM 30 m) y de la cobertura de combustible.

Combustible: catastro de uso de suelo y vegetacion de CONAF (raster lulc_cuenca.tif, 19 clases, UTM 19S, ~28 m)
y, fuera del limite de la cuenca donde el catastro no tiene dato, ESA WorldCover 10 m (respaldo).

Uso (una sola vez, o cuando cambien los TIFF):
    python scripts/preparar_terreno.py RUTA_CARPETA_TESIS [RUTA_lulc_cuenca.tif]

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


# CATASTRO CONAF (lucode del archivo lucode_lookup.csv) -> peso de combustible (provisorio, a revisar por el equipo forestal)
PESO_CONAF = {1: 0.50,    # bosque nativo esclerofilo
              2: 0.0, 3: 0.0,   # agua
              4: 0.10, 5: 0.20,  # bofedales, vegas (suelo humedo)
              6: 0.0, 7: 0.0,    # glaciares, nieves
              8: 0.85, 9: 0.85, 10: 0.60, 11: 0.95,  # matorrales y matorral-pradera
              12: 1.00,          # praderas
              13: 0.50, 14: 0.40,  # agricola
              15: 0.0, 16: 0.0, 17: 0.05, 18: 0.10,  # sin vegetacion / sobre el limite altitudinal
              19: 0.0}           # urbano e industrial


def utm19s(lon, lat):
    """lon/lat WGS84 -> (este, norte) UTM huso 19 sur (serie de Kruger)."""
    a, f = 6378137.0, 1 / 298.257223563
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    al = [n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16, 13 * n**2 / 48 - 3 * n**3 / 5, 61 * n**3 / 240]
    e = np.sqrt(f * (2 - f))
    phi, lam = np.radians(lat), np.radians(lon + 69.0)
    t = np.sinh(np.arctanh(np.sin(phi)) - e * np.arctanh(e * np.sin(phi)))
    xi = np.arctan2(t, np.cos(lam))
    eta = np.arctanh(np.sin(lam) / np.sqrt(1 + t**2))
    E = 500000 + 0.9996 * A * (eta + sum(al[j] * np.cos(2 * (j + 1) * xi) * np.sinh(2 * (j + 1) * eta) for j in range(3)))
    N = 10000000 + 0.9996 * A * (xi + sum(al[j] * np.sin(2 * (j + 1) * xi) * np.cosh(2 * (j + 1) * eta) for j in range(3)))
    return E, N


def combustible_conaf(ruta, lon0, lat0, H, W, celda):
    """Peso y clase dominante CONAF por celda de la grilla (3 x 3 submuestras por celda)."""
    im = Image.open(ruta)
    t = im.tag_v2
    dx, dy = t[33550][0], t[33550][1]
    x0, y0 = t[33922][3], t[33922][4]
    a = np.array(im)
    peso, n_ok = np.zeros((H, W)), np.zeros((H, W))
    cnt = np.zeros((20, H, W))
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            lat = lat0 - (np.arange(H)[:, None] + 0.5 + oy / 3.0) * celda + np.zeros((1, W))
            lon = lon0 + (np.arange(W)[None, :] + 0.5 + ox / 3.0) * celda + np.zeros((H, 1))
            E, N = utm19s(lon, lat)
            c, r = np.floor((E - x0) / dx).astype(int), np.floor((y0 - N) / dy).astype(int)
            dentro = (r >= 0) & (r < a.shape[0]) & (c >= 0) & (c < a.shape[1])
            v = np.where(dentro, a[np.clip(r, 0, a.shape[0] - 1), np.clip(c, 0, a.shape[1] - 1)], 0)
            for k, w in PESO_CONAF.items():
                m = v == k
                peso += w * m
                cnt[k] += m
            n_ok += (v > 0)
    return np.where(n_ok > 0, peso / np.maximum(n_ok, 1), np.nan), np.argmax(cnt, axis=0) * (n_ok > 0)


def main(carpeta, ruta_conaf=None):
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

    origen_fuel = np.zeros(fuel.shape, np.uint8)       # 0 = WorldCover, 1 = catastro CONAF
    if ruta_conaf:
        fc, dc = combustible_conaf(ruta_conaf, tie_d[0], tie_d[1], H // F, W // F, sc_d * F)
        usa = np.isfinite(fc)
        print(f"catastro CONAF cubre {usa.mean():.0%} de las celdas; el resto usa WorldCover")
        fuel = np.where(usa, fc, fuel)
        dom = np.where(usa, dc, 0)
        origen_fuel = usa.astype(np.uint8)

    out = Path(__file__).resolve().parents[1] / "datos" / "terreno_90m.npz"
    np.savez_compressed(
        out,
        elev=np.where(valido, np.round(elev), 0).astype(np.int16),
        slope=np.where(valido, np.round(pend), 0).astype(np.uint8),
        aspect=np.where(valido, np.round(asp), -1).astype(np.int16),
        fuel=np.where(valido, np.round(100 * fuel), 0).astype(np.uint8),
        dom=np.where(valido, dom, 0).astype(np.uint8),
        valido=valido,
        origen_fuel=origen_fuel,
        origen=np.array([tie_d[0], tie_d[1]]),
        celda=np.array([sc_d * F]),
    )
    print(f"{out} ({out.stat().st_size/1e6:.2f} MB) | celdas {valido.shape}, validas {int(valido.sum())}")
    print("altitud", float(np.nanmin(elev)), float(np.nanmax(elev)), "| peso medio", round(float(fuel[valido].mean()), 2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".", sys.argv[2] if len(sys.argv) > 2 else None)
