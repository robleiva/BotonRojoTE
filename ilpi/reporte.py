"""Pagina HTML (tabla por punto y dia) y JSON con el ultimo indice emitido."""
import datetime as dt
import json
import pandas as pd

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _dia(f):
    f = pd.Timestamp(f)
    return f"{DIAS[f.weekday()]} {f:%d-%m}"

COLOR = {"Bajo": "#2f9e44", "Moderado": "#f2c200", "Alto": "#f08c00", "Muy alto": "#e03131", "Extremo": "#7b1fa2"}
TXT = {"Bajo": "#fff", "Moderado": "#222", "Alto": "#fff", "Muy alto": "#fff", "Extremo": "#fff"}


def _celda(g):
    if g.empty:
        return "<td>-</td>"
    p = g[g["Modelo"] == "ECMWF"]
    base = p.iloc[0] if not p.empty else g.iloc[0]
    lo, hi = g["Score"].min(), g["Score"].max()
    rango = f"{lo:.0f}" if abs(hi - lo) < 1 else f"{lo:.0f}-{hi:.0f}"
    aviso = " *" if base["Calidad"] != "ok" else ""
    c = base["Clase"]
    return (f"<td style='background:{COLOR.get(c, '#ccc')};color:{TXT.get(c, '#000')};padding:8px 10px'>"
            f"<b>{c}</b><br><span style='font-size:12px'>{base['Score']:.0f} (rango modelos {rango}){aviso}</span></td>")


def html(ilpi_hoy, historial, actualizado):
    fechas = sorted(ilpi_hoy["Fecha_Valida"].unique()) if not ilpi_hoy.empty else []
    filas = ""
    for pto in ilpi_hoy["Punto"].unique() if not ilpi_hoy.empty else []:
        celdas = "".join(_celda(ilpi_hoy[(ilpi_hoy["Punto"] == pto) & (ilpi_hoy["Fecha_Valida"] == f)]) for f in fechas)
        filas += f"<tr><td style='text-align:left;padding:8px 10px'><b>{pto}</b></td>{celdas}</tr>"
    cab = "".join(f"<th style='padding:8px 10px'>{_dia(f)}</th>" for f in fechas)
    graf = ""
    if historial is not None and not historial.empty:
        import plotly.graph_objects as go
        h = historial[(historial["Lead"] == 0) & (historial["Modelo"] == "ECMWF")]
        fig = go.Figure()
        for pto, g in h.groupby("Punto"):
            g = g.sort_values("Emision")
            fig.add_trace(go.Scatter(x=g["Emision"], y=g["Score"], mode="lines+markers", name=pto))
        fig.update_layout(height=380, template="plotly_white", yaxis_title="Índice (0-100)",
                          margin=dict(l=50, r=20, t=30, b=40), title="Índice del día (emisión diaria)")
        graf = fig.to_html(full_html=False, include_plotlyjs="cdn")
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Botón Rojo TE - Peligro de incendios</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f0f2f5;margin:0;padding:16px;color:#2d3748}}
.c{{max-width:1100px;margin:0 auto;background:#fff;padding:24px;border-radius:10px}}table{{border-collapse:collapse;width:100%;text-align:center}}
th{{background:#2b6cb0;color:#fff}}td,th{{border:1px solid #e2e8f0}}.aviso{{background:#fffaf0;border-left:4px solid #dd6b20;padding:10px 14px;font-size:14px}}</style></head>
<body><div class="c"><h1 style="margin-top:0">Botón Rojo TE - Índice local de peligro de incendios</h1>
<div class="aviso"><b>EXPERIMENTAL.</b> Índice relativo (0-100) con pesos y umbrales provisorios, aún sin calibrar con incendios reales.
No es un pronóstico oficial ni predice ocurrencia de incendios. Referencia oficial: CONAF y SENAPRED.</div>
<p style="font-size:14px">Actualizado: {actualizado}. Valor mostrado: ECMWF IFS a las 15:00 locales; el rango incluye GFS.
<br>* día con datos incompletos (el estado de humedad del combustible se arrastró).</p>
<table><tr><th>Punto</th>{cab}</tr>{filas}</table>
<h3>Historial</h3>{graf}
<p style="font-size:12px;color:#718096">Clases: Bajo &lt;30, Moderado 30-50, Alto 50-65, Muy alto 65-80, Extremo &ge;80 (provisorio).
Sin nieve ni NDMI en esta versión: en la alta cuenca, a inicios de temporada, el índice puede sobrestimar.</p></div></body></html>"""


def json_salida(ilpi_hoy, actualizado):
    return json.dumps({"actualizado": actualizado, "experimental": True,
                       "indice": json.loads(ilpi_hoy.to_json(orient="records", date_format="iso"))}, ensure_ascii=False, indent=1)
