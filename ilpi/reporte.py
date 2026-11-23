"""Pagina HTML corporativa (resumen, mapa por celda, tabla por punto, historial) y JSON con el ultimo indice emitido."""
import json
import pandas as pd

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
CLASES = ["Bajo", "Moderado", "Alto", "Muy alto", "Extremo"]
COLOR = {"Bajo": "#2f9e44", "Moderado": "#f2c200", "Alto": "#f08c00", "Muy alto": "#e03131", "Extremo": "#7b1fa2"}
TXT = {"Bajo": "#fff", "Moderado": "#1f2933", "Alto": "#fff", "Muy alto": "#fff", "Extremo": "#fff"}
UMBRAL = {"Bajo": "< 30", "Moderado": "30 – 50", "Alto": "50 – 65", "Muy alto": "65 – 80", "Extremo": "≥ 80"}


def _dia(f):
    f = pd.Timestamp(f)
    return f"{DIAS[f.weekday()]} {f:%d-%m}"


def _chip(clase, texto=None):
    return (f"<span class='chip' style='background:{COLOR.get(clase, '#9aa5b1')};color:{TXT.get(clase, '#fff')}'>"
            f"{texto or clase}</span>")


def _celda(g):
    if g.empty:
        return "<td class='vacio'>–</td>"
    p = g[g["Modelo"] == "ECMWF"]
    base = p.iloc[0] if not p.empty else g.iloc[0]
    lo, hi = g["Score"].min(), g["Score"].max()
    rango = f"{lo:.0f}" if abs(hi - lo) < 1 else f"{lo:.0f}–{hi:.0f}"
    aviso = "<sup title='Día con datos incompletos'>*</sup>" if base["Calidad"] != "ok" else ""
    return (f"<td>{_chip(base['Clase'])}<div class='sub'>{base['Score']:.0f}{aviso}"
            f"<span title='Rango entre modelos (ECMWF y GFS)'> · {rango}</span></div></td>")


# ------------------------------------------------------------------ resumen
def _kpis(ilpi_hoy, mapa):
    tarjetas = []
    if not ilpi_hoy.empty:
        e = ilpi_hoy[ilpi_hoy["Modelo"] == "ECMWF"]
        e = e[e["Fecha_Valida"] == e["Fecha_Valida"].min()] if not e.empty else e
        if not e.empty:
            top = e.sort_values("Score", ascending=False).iloc[0]
            tarjetas.append(("Peligro máximo hoy", _chip(top["Clase"], f"{top['Clase']} · {top['Score']:.0f}"),
                             f"en {top['Punto']}"))
    if mapa and mapa.get("resumen"):
        r = mapa["resumen"][0]
        tot = max(r["Ha_combustible"], 1)
        alto = r["Alto"] + r["Muy alto"] + r["Extremo"]
        tarjetas.append(("Superficie en Alto o superior", f"<span class='num'>{alto:,}</span> ha".replace(",", "."),
                         f"{100 * alto / tot:.0f} % de {r['Ha_combustible']:,} ha con combustible".replace(",", ".")))
        if len(mapa["resumen"]) > 1:
            u = mapa["resumen"][-1]
            alto_u = u["Alto"] + u["Muy alto"] + u["Extremo"]
            sube = alto_u - alto
            flecha = "▲" if sube > 0 else ("▼" if sube < 0 else "■")
            tarjetas.append((f"Tendencia a {_dia(u['Fecha'])}", f"<span class='num'>{flecha} {abs(sube):,}</span> ha".replace(",", "."),
                             "variación de la superficie en Alto o superior"))
    return "".join(f"<div class='kpi'><div class='kpi-t'>{t}</div><div class='kpi-v'>{v}</div><div class='kpi-s'>{s}</div></div>"
                   for t, v, s in tarjetas)


def _barras(mapa):
    if not mapa or not mapa.get("resumen"):
        return ""
    filas = ""
    for r in mapa["resumen"]:
        tot = max(r["Ha_combustible"], 1)
        seg = "".join(f"<span style='width:{100 * r[c] / tot:.2f}%;background:{COLOR[c]}' title='{c}: {r[c]:,} ha'></span>".replace(",", ".")
                      for c in CLASES if r[c] > 0)
        filas += f"<div class='fila'><div class='et'>{_dia(r['Fecha'])}</div><div class='barra'>{seg}</div></div>"
    leyenda = "".join(f"<span class='ley'><i style='background:{COLOR[c]}'></i>{c} <small>({UMBRAL[c]})</small></span>" for c in CLASES)
    return f"<div class='barras'>{filas}</div><div class='leyenda'>{leyenda}</div>"


# ------------------------------------------------------------------ mapa
def _mapa_html(mapa, ilpi_hoy):
    """Mapa Leaflet con una capa PNG por dia, marcadores de los puntos y leyenda."""
    from . import grilla
    from .config import PUNTOS
    dias = [{"etq": _dia(f), "png": grilla.png_base64(mapa["score"][i], mapa["combustible"])} for i, f in enumerate(mapa["fechas"])]
    pts = []
    for n, m in PUNTOS.items():
        g = ilpi_hoy[(ilpi_hoy["Punto"] == n) & (ilpi_hoy["Modelo"] == "ECMWF")].sort_values("Fecha_Valida")
        pts.append({"n": n, "lat": m["lat"], "lon": m["lon"], "s": [f"{x:.0f}" for x in g["Score"]], "c": list(g["Clase"])})
    datos = json.dumps({"lim": mapa["limites"], "dias": dias, "pts": pts, "color": COLOR}, ensure_ascii=False)
    return MAPA_TPL.replace("__DATOS__", datos)


MAPA_TPL = """<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="tabs" id="dias"></div><div id="mapa"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>(function(){var D=__DATOS__;var m=L.map("mapa",{scrollWheelZoom:false});
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:17,attribution:"&copy; OpenStreetMap"}).addTo(m);
m.fitBounds(D.lim);var capa=null,btns=[];
function ver(i){if(capa)m.removeLayer(capa);capa=L.imageOverlay("data:image/png;base64,"+D.dias[i].png,D.lim,{opacity:0.85,interactive:false}).addTo(m);
btns.forEach(function(b,j){b.className=j==i?"tab on":"tab"});}
D.dias.forEach(function(d,i){var b=document.createElement("button");b.textContent=d.etq;b.className="tab";b.onclick=function(){ver(i)};document.getElementById("dias").appendChild(b);btns.push(b)});
D.pts.forEach(function(p){var c=D.color[p.c[0]]||"#555";L.circleMarker([p.lat,p.lon],{radius:8,color:"#102a43",weight:2,fillColor:c,fillOpacity:1}).addTo(m).bindTooltip("<b>"+p.n+"</b><br>"+p.c.map(function(x,k){return x+" "+p.s[k]}).join("<br>"));});
ver(0);})();</script>"""

CSS = """
:root{--azul:#0b3a5b;--azul2:#134e7a;--acento:#00a3a1;--fondo:#f3f6f9;--tinta:#1f2933;--gris:#627d98;--linea:#d9e2ec}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--tinta);font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.5}
header{background:linear-gradient(120deg,var(--azul) 0%,var(--azul2) 100%);color:#fff;border-bottom:4px solid var(--acento)}
.w{max-width:1120px;margin:0 auto;padding:0 20px}
.cab{display:flex;align-items:center;gap:18px;padding:22px 20px;flex-wrap:wrap}
.cab img{height:46px;background:#fff;border-radius:6px;padding:6px 10px}
.cab h1{margin:0;font-size:26px;font-weight:650;letter-spacing:.2px}
.cab p{margin:2px 0 0;opacity:.85;font-size:14px}
.cab .fecha{margin-left:auto;text-align:right;font-size:13px;opacity:.9}
.aviso{background:#fff7e6;border-left:5px solid #f08c00;border-radius:6px;padding:12px 16px;font-size:14px;margin:20px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:0 0 6px}
.kpi{background:#fff;border:1px solid var(--linea);border-radius:10px;padding:16px 18px;border-top:3px solid var(--acento)}
.kpi-t{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--gris);font-weight:600}
.kpi-v{font-size:22px;font-weight:650;margin:6px 0 2px;color:var(--azul)}.kpi-v .num{font-size:30px}
.kpi-s{font-size:13px;color:var(--gris)}
section{background:#fff;border:1px solid var(--linea);border-radius:10px;padding:20px 22px;margin:18px 0}
section h2{margin:0 0 4px;font-size:18px;color:var(--azul)}
section .nota{margin:0 0 14px;font-size:13px;color:var(--gris)}
.chip{display:inline-block;padding:3px 11px;border-radius:999px;font-weight:650;font-size:13px;white-space:nowrap}
#mapa{height:540px;border-radius:8px;border:1px solid var(--linea)}
.tabs{margin-bottom:10px;display:flex;gap:6px;flex-wrap:wrap}
.tab{border:1px solid var(--linea);background:#fff;color:var(--azul);padding:7px 14px;border-radius:6px;cursor:pointer;font-size:14px}
.tab.on{background:var(--azul);color:#fff;border-color:var(--azul)}
table{border-collapse:collapse;width:100%}
th{background:var(--azul);color:#fff;font-weight:600;font-size:13px;padding:9px 10px;text-align:center}
th:first-child,td:first-child{text-align:left}
td{border-bottom:1px solid var(--linea);padding:9px 10px;text-align:center}
td .sub{font-size:12px;color:var(--gris);margin-top:2px}td.vacio{color:var(--gris)}
.barras .fila{display:flex;align-items:center;gap:12px;margin:7px 0}.barras .et{width:70px;font-size:13px;color:var(--gris)}
.barra{flex:1;display:flex;height:22px;border-radius:5px;overflow:hidden;background:#e4e7eb}.barra span{display:block;height:100%}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:12px;font-size:13px}
.ley i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}.ley small{color:var(--gris)}
details{margin-top:8px}summary{cursor:pointer;font-weight:600;color:var(--azul2)}
details ul{margin:10px 0 0;padding-left:20px;font-size:14px}details li{margin:4px 0}
footer{color:var(--gris);font-size:12px;padding:6px 0 30px}
@media(max-width:640px){.cab h1{font-size:21px}.cab .fecha{margin-left:0;text-align:left}#mapa{height:420px}}
@media print{header{background:#fff;color:#000;border-bottom:2px solid #000}.tabs{display:none}#mapa{height:360px}section{break-inside:avoid}}
"""


def html(ilpi_hoy, historial, actualizado, mapa=None, logo=False):
    fechas = sorted(ilpi_hoy["Fecha_Valida"].unique()) if not ilpi_hoy.empty else []
    filas = ""
    for pto in ilpi_hoy["Punto"].unique() if not ilpi_hoy.empty else []:
        celdas = "".join(_celda(ilpi_hoy[(ilpi_hoy["Punto"] == pto) & (ilpi_hoy["Fecha_Valida"] == f)]) for f in fechas)
        filas += f"<tr><td><b>{pto}</b></td>{celdas}</tr>"
    cab = "".join(f"<th>{_dia(f)}</th>" for f in fechas)
    graf = ""
    if historial is not None and not historial.empty:
        import plotly.graph_objects as go
        h = historial[(historial["Lead"] == 0) & (historial["Modelo"] == "ECMWF")]
        fig = go.Figure()
        for pto, g in h.groupby("Punto"):
            g = g.sort_values("Emision")
            fig.add_trace(go.Scatter(x=g["Emision"], y=g["Score"], mode="lines+markers", name=pto))
        fig.update_layout(height=360, template="plotly_white", yaxis_title="Índice (0-100)",
                          margin=dict(l=50, r=20, t=20, b=40), legend=dict(orientation="h", y=-0.2),
                          colorway=["#0b3a5b", "#00a3a1", "#f08c00", "#7b1fa2", "#e03131"])
        graf = fig.to_html(full_html=False, include_plotlyjs="cdn")
    kpis = _kpis(ilpi_hoy, mapa)
    sec_kpis = f"<div class='kpis'>{kpis}</div>" if kpis else ""
    sec_mapa = (f"<section><h2>Mapa de peligro</h2><p class='nota'>Celdas de 90 m. Se pinta solo donde hay combustible relevante; roca, nieve y agua quedan sin color.</p>"
                f"{_mapa_html(mapa, ilpi_hoy)}</section>") if mapa else ""
    sec_barras = (f"<section><h2>Superficie con combustible por clase de peligro</h2>"
                  f"<p class='nota'>Proporción de la superficie con combustible en cada clase, por día.</p>{_barras(mapa)}</section>") if mapa else ""
    sec_graf = f"<section><h2>Historial</h2><p class='nota'>Índice del día en cada punto (emisión diaria, ECMWF).</p>{graf}</section>" if graf else ""
    logo_html = "<img src='logo.png' alt='Tinguiririca Energía'>" if logo else ""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Peligro de incendios forestales · Cuenca del Tinguiririca</title>
<style>{CSS}</style></head><body>
<header><div class="w cab">{logo_html}<div><h1>Índice Local de Peligro de Incendios Forestales</h1>
<p>Cuenca del río Tinguiririca · Tinguiririca Energía</p></div><div class="fecha">Actualizado<br><b>{actualizado}</b></div></div></header>
<div class="w">
<div class="aviso"><b>EXPERIMENTAL.</b> Índice relativo (0–100) con pesos y umbrales provisorios, aún sin calibrar con incendios reales.
No es un pronóstico oficial ni predice la ocurrencia de incendios. Referencia oficial: CONAF y SENAPRED.</div>
{sec_kpis}
{sec_mapa}
<section><h2>Peligro por punto de monitoreo</h2>
<p class='nota'>Valor ECMWF IFS a las 15:00 locales · segundo número: rango entre modelos (ECMWF y GFS). * día con datos incompletos.</p>
<table><tr><th>Punto</th>{cab}</tr>{filas}</table></section>
{sec_barras}
{sec_graf}
<section><h2>Cómo se calcula</h2>
<details><summary>Metodología y limitaciones</summary><ul>
<li><b>Datos:</b> estaciones meteorológicas propias (BT Portillo y BT Tinguiririca), modelos ECMWF IFS y GFS (Open-Meteo), terreno desde un DEM de 30 m y cobertura ESA WorldCover de 10 m.</li>
<li><b>Índice:</b> sequedad del combustible muerto (FFMC, Van Wagner 1987) × tipo de combustible × potencial de propagación (viento y pendiente), como media geométrica ponderada. Pendiente y exposición se consideran en cada celda.</li>
<li><b>Clases (provisorias):</b> Bajo &lt; 30 · Moderado 30–50 · Alto 50–65 · Muy alto 65–80 · Extremo ≥ 80.</li>
<li><b>Limitaciones:</b> sin nieve ni humedad de la vegetación viva (NDMI); la cobertura no distingue bosque nativo de plantación; el viento no incorpora el relieve; el mapa cubre solo la cuenca alta y media.</li>
</ul></details></section>
<footer>Botón Rojo TE · uso interno y experimental. Mapa base © OpenStreetMap.</footer>
</div></body></html>"""


def json_salida(ilpi_hoy, actualizado):
    return json.dumps({"actualizado": actualizado, "experimental": True,
                       "indice": json.loads(ilpi_hoy.to_json(orient="records", date_format="iso"))}, ensure_ascii=False, indent=1)
