"""Calcula los cortes de clase por percentiles del clima historico y guarda datos/calibracion_percentiles.json.

Necesita internet (Open-Meteo archive). Se ejecuta desde GitHub Actions: flujo "Calibracion por percentiles".
Uso local: python scripts/calibrar_percentiles.py [ANIO_INICIO] [ANIO_FIN]
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ilpi import calibracion  # noqa: E402
from ilpi.config import PUNTOS  # noqa: E402
from ilpi.run_daily import cargar_terreno  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def main(anio_ini=2000, anio_fin=None):
    hoy = dt.date.today()
    fin = dt.date(anio_fin, 12, 31) if anio_fin else hoy - dt.timedelta(days=10)
    ini = dt.date(anio_ini, 7, 1)
    terreno = cargar_terreno()
    series = {}
    for pto, meta in PUNTOS.items():
        horario, elev = calibracion.descargar_punto(meta["lat"], meta["lon"], ini, fin)
        series[pto] = calibracion.serie_indice(horario, elev, meta, terreno[pto])
        print(f"[calibracion] {pto}: {len(series[pto])} dias, elevacion del modelo {elev} m", flush=True)
    res = calibracion.armar_resultado(series, f"{ini.isoformat()} a {fin.isoformat()}")
    (RAIZ / "datos" / "calibracion_percentiles.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print("[calibracion] cortes (P50, P75, P90, P97):", res["cortes"], "| dias de temporada:", res["dias_temporada"])
    print("[calibracion] por punto:", res["por_punto"])


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000, int(sys.argv[2]) if len(sys.argv) > 2 else None)
