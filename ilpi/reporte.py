"""Pagina HTML corporativa (resumen, mapa por celda, tabla por punto, historial) y JSON con el ultimo indice emitido."""
import json
import pandas as pd
from .config import PUNTOS

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
D.pts.forEach(function(p){var c=D.color[p.c[0]]||"#555";L.circleMarker([p.lat,p.lon],{radius:8,color:"#414042",weight:2,fillColor:c,fillOpacity:1}).addTo(m).bindTooltip("<b>"+p.n+"</b><br>"+p.c.map(function(x,k){return x+" "+p.s[k]}).join("<br>"));});
ver(0);})();</script>"""

_EXPL_CLASES = {"Bajo": "Combustible húmedo o con pocas posibilidades de propagación. Condiciones poco favorables para un fuego.",
    "Moderado": "Combustible algo seco. Un fuego puede iniciarse y avanzar con dificultad; precaución con faenas que usen fuego o chispas.",
    "Alto": "Combustible seco y propagación posible. Un fuego se inicia con facilidad y puede crecer rápido.",
    "Muy alto": "Condiciones críticas: combustible muy seco, con viento o pendiente a favor. Un fuego sería difícil de controlar.",
    "Extremo": "Máximo peligro relativo. Todas las condiciones favorecen un fuego de rápida propagación."}


def _explicacion():
    filas = "".join(f"<tr><td><span class='chip' style='background:{COLOR[c]};color:{TXT[c]}'>{c}</span></td>"
                    f"<td>{UMBRAL[c]}</td><td>{_EXPL_CLASES[c]}</td></tr>" for c in CLASES)
    return f"""<section><h2>Qué significa el índice</h2>
<p class='nota'>Un número de 0 a 100: mientras más alto, más favorables son las condiciones para que un fuego se inicie y se propague.</p>
<p>Es un índice <b>relativo</b>. Sirve para comparar un día con otro y un lugar con otro dentro de la cuenca, no para anunciar un incendio. Un valor alto no significa que habrá fuego, y uno bajo no lo descarta: el índice no considera las fuentes de ignición, como la actividad humana.</p>
<table><tr><th style='text-align:left'>Clase</th><th>Puntaje</th><th style='text-align:left'>Qué indica</th></tr>{filas}</table>
<div class='comp'>
<div><b>Sequedad</b><p>Qué tan seco está el combustible fino muerto (pasto seco y hojarasca). Depende de temperatura, humedad, viento y lluvia de los días anteriores, y es la parte que más pesa en el índice.</p></div>
<div><b>Combustible</b><p>Cuánto y qué tipo de vegetación hay en el lugar. El pastizal arde más fácil que el bosque nativo; la roca, la nieve y el agua no arden.</p></div>
<div><b>Propagación</b><p>Qué tan rápido avanzaría el fuego, según el viento y la pendiente. Una ladera empinada con viento a favor acelera el avance.</p></div></div>
<p class='nota'>Los puntajes y las clases son provisorios: aún no se calibran con incendios reales.</p></section>"""


CSS = """
@font-face{font-family:'Intro Book Alt';src:url('fonts/Intro-Book-Alt.otf') format('opentype');font-weight:400;font-style:normal;font-display:swap}
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap');
:root{--cyan:#00ABE5;--teal:#5BBDB5;--green:#7AB929;--cyan-x:#E5F5FD;--teal-x:#E8F6F5;--green-x:#EEF8DC;
--dark:#414042;--mid:#7F7F7F;--light:#C8C9CB;--bg:#F5F7F8;--brand:'Intro Book Alt','Nunito',sans-serif;--body:'Nunito','Intro Book Alt',sans-serif;
--r-sm:6px;--r-md:12px;--r-lg:20px;--sombra:0 2px 12px rgba(0,174,239,.10)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--dark);font-family:var(--body);font-size:16px;line-height:1.5}
h1,h2,h3{font-family:var(--brand);font-weight:400;line-height:1.2;margin:0}
header{background:var(--cyan);color:#fff;position:relative;overflow:hidden}
header:after{content:"";position:absolute;right:-60px;top:-60px;width:240px;height:240px;border-radius:50%;background:rgba(255,255,255,.12)}
.w{max-width:1120px;margin:0 auto;padding:0 20px}
.cab{display:flex;align-items:center;gap:28px;padding:26px 20px;flex-wrap:wrap;position:relative;z-index:1}
.cab img{height:64px;width:auto}
.cab h1{font-size:30px;color:#fff}
.cab p{margin:4px 0 0;font-size:15px;color:#fff}
.cab .fecha{margin-left:auto;text-align:right;font-size:14px;color:#fff}
.cab .fecha b{font-weight:700}
.aviso{background:var(--green-x);border:1px solid var(--green);border-radius:var(--r-md);padding:14px 18px;font-size:14px;margin:22px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin:0 0 6px}
.kpi{background:#fff;border-radius:var(--r-lg);padding:18px 20px;box-shadow:var(--sombra)}
.kpi-t{font-size:14px;font-weight:600;color:var(--mid)}
.kpi-v{font-family:var(--brand);font-size:22px;margin:6px 0 2px;color:var(--dark)}.kpi-v .num{font-size:34px}
.kpi-s{font-size:13px;color:var(--mid)}
section{background:#fff;border-radius:var(--r-lg);padding:22px 24px;margin:20px 0;box-shadow:var(--sombra)}
section h2{font-size:24px;margin:0 0 4px}
section .nota{margin:0 0 16px;font-size:14px;color:var(--mid)}
.chip{display:inline-block;padding:3px 12px;border-radius:9999px;font-weight:700;font-size:13px;white-space:nowrap}
#mapa{height:540px;border-radius:var(--r-md);border:1px solid var(--light)}
.tabs{margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap}
.tab{border:1px solid var(--light);background:#fff;color:var(--dark);padding:7px 16px;border-radius:9999px;cursor:pointer;font:600 14px var(--body)}
.tab:hover{border-color:var(--cyan);background:var(--cyan-x)}
.tab.on{background:var(--dark);color:#fff;border-color:var(--dark)}
.tab:focus-visible,summary:focus-visible{outline:3px solid var(--cyan);outline-offset:2px}
table{border-collapse:separate;border-spacing:0;width:100%}
th{background:var(--cyan-x);color:var(--dark);font-weight:700;font-size:14px;padding:10px;text-align:center}
th:first-child{border-radius:var(--r-sm) 0 0 var(--r-sm)}th:last-child{border-radius:0 var(--r-sm) var(--r-sm) 0}
th:first-child,td:first-child{text-align:left}
td{border-bottom:1px solid #e6e8ea;padding:10px;text-align:center}
td .sub{font-size:12px;color:var(--mid);margin-top:2px}td.vacio{color:var(--mid)}
.barras .fila{display:flex;align-items:center;gap:12px;margin:8px 0}.barras .et{width:70px;font-size:14px;color:var(--mid)}
.barra{flex:1;display:flex;height:24px;border-radius:9999px;overflow:hidden;background:#e9ecee}.barra span{display:block;height:100%}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:14px;font-size:13px}
.ley i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}.ley small{color:var(--mid)}
details{margin-top:8px}summary{cursor:pointer;font-weight:700;color:var(--cyan);color:#0086b3}
details ul{margin:12px 0 0;padding-left:20px;font-size:15px}details li{margin:6px 0}
table td:nth-child(3){text-align:left}.comp{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:6px 0 10px}.comp>div{background:var(--cyan-x);border-radius:var(--r-md);padding:12px 16px}.comp b{font-family:var(--brand);font-weight:400;font-size:17px}.comp p{margin:4px 0 0;font-size:14px}
footer{display:flex;align-items:center;gap:12px;color:var(--mid);font-size:13px;padding:6px 0 34px}
footer img{height:34px;width:auto}
@media(max-width:640px){.cab h1{font-size:22px}.cab img{height:50px}.cab .fecha{margin-left:0;text-align:left}#mapa{height:420px}}
@media print{header{background:#fff;color:#000}.cab h1,.cab p,.cab .fecha{color:#000}.cab img{filter:invert(1)}.tabs{display:none}#mapa{height:360px}section{break-inside:avoid;box-shadow:none;border:1px solid var(--light)}}
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
        h = historial[(historial["Lead"] == 0) & (historial["Modelo"] == "ECMWF") & (historial["Punto"].isin(list(PUNTOS)))]
        fig = go.Figure()
        for pto, g in h.groupby("Punto"):
            g = g.sort_values("Emision")
            fig.add_trace(go.Scatter(x=g["Emision"], y=g["Score"], mode="lines+markers", name=pto))
        fig.update_layout(height=360, template="plotly_white", yaxis_title="Índice (0-100)",
                          margin=dict(l=50, r=20, t=20, b=40), legend=dict(orientation="h", y=-0.2),
                          colorway=["#00ABE5", "#5BBDB5", "#7AB929", "#414042", "#7F7F7F"], font=dict(family="Nunito, sans-serif", color="#414042"))
        graf = fig.to_html(full_html=False, include_plotlyjs="cdn")
    expl = _explicacion()
    kpis = _kpis(ilpi_hoy, mapa)
    sec_kpis = f"<div class='kpis'>{kpis}</div>" if kpis else ""
    sec_mapa = (f"<section><h2>Mapa de peligro</h2><p class='nota'>Celdas de 90 m. Se pinta solo donde hay combustible relevante; roca, nieve y agua quedan sin color.</p>"
                f"{_mapa_html(mapa, ilpi_hoy)}</section>") if mapa else ""
    sec_barras = (f"<section><h2>Superficie con combustible por clase de peligro</h2>"
                  f"<p class='nota'>Proporción de la superficie con combustible en cada clase, por día.</p>{_barras(mapa)}</section>") if mapa else ""
    sec_graf = f"<section><h2>Historial</h2><p class='nota'>Índice del día en cada punto (emisión diaria, ECMWF).</p>{graf}</section>" if graf else ""
    logo_html = "<img src='img/logo-white.png' alt='Tinguiririca Energía'>" if logo else ""
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
{expl}
<section><h2>Cómo se calcula</h2>
<details><summary>Metodología y limitaciones</summary><ul>
<li><b>Datos:</b> estaciones meteorológicas propias (BT Portillo y BT Tinguiririca), modelos ECMWF IFS y GFS (Open-Meteo), terreno desde un DEM de 30 m y combustible desde el catastro de uso de suelo y vegetación de CONAF (actualización 2020), con ESA WorldCover de 10 m como respaldo fuera del límite de la cuenca.</li>
<li><b>Índice:</b> sequedad del combustible muerto (FFMC, Van Wagner 1987) × tipo de combustible × potencial de propagación (viento y pendiente), como media geométrica ponderada. Pendiente y exposición se consideran en cada celda.</li>
<li><b>Clases (provisorias):</b> Bajo &lt; 30 · Moderado 30–50 · Alto 50–65 · Muy alto 65–80 · Extremo ≥ 80.</li>
<li><b>Limitaciones:</b> sin nieve ni humedad de la vegetación viva (NDMI); el catastro no distingue la carga ni la continuidad del combustible dentro de cada clase; el viento no incorpora el relieve; el mapa cubre solo la cuenca alta y media.</li>
</ul></details></section>
<footer><img src="img/iso-color.png" alt=""><span>Botón Rojo TE · uso interno y experimental. Mapa base © OpenStreetMap.</span></footer>
</div></body></html>"""


def json_salida(ilpi_hoy, actualizado):
    return json.dumps({"actualizado": actualizado, "experimental": True,
                       "indice": json.loads(ilpi_hoy.to_json(orient="records", date_format="iso"))}, ensure_ascii=False, indent=1)
