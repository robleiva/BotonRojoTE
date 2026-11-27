"""Pagina HTML corporativa (resumen, mapa por celda, tabla por punto, historial) y JSON con el ultimo indice emitido."""
import json
import pandas as pd
from . import fireindex as fi
from .config import PUNTOS

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
CLASES = ["Bajo", "Moderado", "Alto", "Muy alto", "Extremo"]
COLOR = {"Bajo": "#2f9e44", "Moderado": "#f2c200", "Alto": "#f08c00", "Muy alto": "#e03131", "Extremo": "#7b1fa2"}
TXT = {"Bajo": "#fff", "Moderado": "#1f2933", "Alto": "#fff", "Muy alto": "#fff", "Extremo": "#fff"}


def _umbral():
    c = [f"{x:g}" for x in fi.PROV_BREAKS]
    return {"Bajo": f"< {c[0]}", "Moderado": f"{c[0]} – {c[1]}", "Alto": f"{c[1]} – {c[2]}", "Muy alto": f"{c[2]} – {c[3]}", "Extremo": f"≥ {c[3]}"}


UMBRAL = _umbral()


def _calibrado():
    return fi.CALIBRACION is not None


def _texto_clases():
    if _calibrado():
        d = fi.CALIBRACION
        return (f"<b>Clases por percentiles:</b> se calcularon con el clima histórico de la cuenca ({d['periodo'].replace(' a ', ' al ')}, "
                f"{d['dias_temporada']:,} días de temporada) y no con incendios. Bajo: menos del 50 % de los días; Moderado: 50 a 75 %; "
                f"Alto: 75 a 90 %; Muy alto: 90 a 97 %; Extremo: el 3 % de los días más secos. Cortes de puntaje: "
                f"{' · '.join(f'{x:g}' for x in fi.PROV_BREAKS)}.").replace(",", ".")
    return "<b>Clases (provisorias):</b> " + " · ".join(f"{c} {u}" for c, u in UMBRAL.items()) + "."


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
    if base.get("Nieve") == True:                       # noqa: E712  (NaN en filas antiguas)
        return ("<td><span class='chip' style='background:#C4E0F2;color:#414042'>Nieve</span>"
                "<div class='sub'>sin combustible expuesto</div></td>")
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
    if mapa and mapa.get("resumen") and mapa["resumen"][0].get("Ha_nieve", 0) > 0:
        r0 = mapa["resumen"][0]
        tarjetas.append(("Superficie con nieve", f"<span class='num'>{r0['Ha_nieve']:,}</span> ha".replace(",", "."),
                         "estimada con el modelo; se excluye del cálculo"))
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
def _limite_cuenca():
    """Poligonos [[lat, lon], ...] del contorno de la cuenca; lista vacia si el archivo no existe."""
    from .config import F_LIMITE
    try:
        with open(F_LIMITE, encoding="utf-8") as f:
            return json.load(f)["poligonos"]
    except (OSError, ValueError, KeyError):
        return []


def _mapa_html(mapa, ilpi_hoy):
    """Mapa Leaflet con una capa PNG por dia, marcadores de los puntos y leyenda."""
    from . import grilla
    from .config import PUNTOS
    N = mapa.get("nieve")
    dias = [{"etq": _dia(f), "png": grilla.png_base64(mapa["score"][i], mapa["combustible"], None if N is None else N[i])} for i, f in enumerate(mapa["fechas"])]
    pts = []
    for n, m in PUNTOS.items():
        g = ilpi_hoy[(ilpi_hoy["Punto"] == n) & (ilpi_hoy["Modelo"] == "ECMWF")].sort_values("Fecha_Valida")
        pts.append({"n": n, "lat": m["lat"], "lon": m["lon"], "s": [f"{x:.0f}" for x in g["Score"]], "c": list(g["Clase"])})
    ign = grilla.png_ignicion_base64(mapa["ignicion"]) if mapa.get("ignicion") is not None else None
    datos = json.dumps({"lim": mapa["limites"], "dias": dias, "pts": pts, "color": COLOR, "ign": ign, "cuenca": _limite_cuenca(), "nieve": N is not None}, ensure_ascii=False)
    return MAPA_TPL.replace("__DATOS__", datos)


MAPA_TPL = """<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<div class="tabs" id="dias"></div><div id="mapa"></div>
<p class="nota" id="leynieve" style="margin-top:10px"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#C4E0F2;margin-right:6px;vertical-align:-1px"></span>Nieve (estimada con el modelo): sin peligro de incendio.</p>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>(function(){var D=__DATOS__;var m=L.map("mapa",{scrollWheelZoom:false});
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:17,attribution:"&copy; OpenStreetMap"}).addTo(m);
m.fitBounds(D.lim);var capa=null,btns=[];if(!D.nieve)document.getElementById("leynieve").style.display="none";
m.createPane("cuenca");m.getPane("cuenca").style.zIndex=450;m.getPane("cuenca").style.pointerEvents="none";
D.cuenca.forEach(function(r){L.polygon(r,{pane:"cuenca",color:"#414042",weight:2.5,dashArray:"7 5",fill:false,interactive:false}).addTo(m);});
function ver(i){if(capa)m.removeLayer(capa);capa=L.imageOverlay("data:image/png;base64,"+D.dias[i].png,D.lim,{opacity:0.85,interactive:false}).addTo(m);
btns.forEach(function(b,j){b.className=j==i?"tab on":"tab"});document.getElementById("leyign").style.display="none";}
function verIgn(){if(capa)m.removeLayer(capa);capa=L.imageOverlay("data:image/png;base64,"+D.ign,D.lim,{opacity:0.85,interactive:false}).addTo(m);
btns.forEach(function(b,j){b.className=j==D.dias.length?"tab on":"tab"});document.getElementById("leyign").style.display="block";}
D.dias.forEach(function(d,i){var b=document.createElement("button");b.textContent=d.etq;b.className="tab";b.onclick=function(){ver(i)};document.getElementById("dias").appendChild(b);btns.push(b)});
D.pts.forEach(function(p){var c=D.color[p.c[0]]||"#555";L.circleMarker([p.lat,p.lon],{radius:8,color:"#414042",weight:2,fillColor:c,fillOpacity:1}).addTo(m).bindTooltip("<b>"+p.n+"</b><br>"+p.c.map(function(x,k){return x+" "+p.s[k]}).join("<br>"));});
if(D.ign){var bi=document.createElement("button");bi.textContent="Ignición humana";bi.className="tab";bi.onclick=verIgn;document.getElementById("dias").appendChild(bi);btns.push(bi);}
ver(0);})();</script>
<div id="leyign" class="nota" style="display:none;margin-top:10px"><p><b>Ignición humana:</b> muestra qué zonas están más expuestas a que un fuego se <i>inicie</i> por actividad de las personas (chispas de vehículos, faenas, cigarrillos, fogatas, fallas de líneas eléctricas). Se calcula con la cercanía a caminos, edificaciones y líneas de transmisión, según OpenStreetMap.</p>
<p><span style="display:inline-block;width:150px;height:10px;border-radius:5px;vertical-align:middle;background:linear-gradient(90deg,rgba(0,171,229,.45),#414042)"></span> De poca exposición (cian claro) a mucha exposición (gris oscuro).</p>
<p>Es una capa aparte: <b>no entra en el índice de peligro</b> y no está calibrada. El índice dice qué tan fácil sería que un fuego se propague; esta capa dice dónde es más probable que parta. Lo más delicado es la combinación de ambos: peligro alto en una zona con alta exposición.</p></div>"""

_EXPL_CLASES = {"Bajo": "Combustible húmedo o con pocas posibilidades de propagación. Condiciones poco favorables para un fuego.",
    "Moderado": "Combustible algo seco. Un fuego puede iniciarse y avanzar con dificultad; precaución con faenas que usen fuego o chispas.",
    "Alto": "Combustible seco y propagación posible. Un fuego se inicia con facilidad y puede crecer rápido.",
    "Muy alto": "Condiciones críticas: combustible muy seco, con viento o pendiente a favor. Un fuego sería difícil de controlar.",
    "Extremo": "Máximo peligro relativo. Todas las condiciones favorecen un fuego de rápida propagación."}


def _explicacion():
    if _calibrado():
        nota = ("Las clases comparan cada día con la historia de la cuenca (por percentiles del clima desde "
                f"{fi.CALIBRACION['periodo'][:4]}). Extremo significa que el día está entre el 3 % más seco de la temporada; "
                "no están calibradas con incendios reales.")
    else:
        nota = "Los puntajes y las clases son provisorios: aún no se calibran con incendios reales."
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
<p class='nota'>{nota}</p></section>"""


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


def _historial(historial):
    """Una casilla por punto y por dia: color = clase vigente, numero = puntaje. Gris = sin dato."""
    if historial is None or historial.empty:
        return ""
    import pandas as pd
    import plotly.graph_objects as go
    from . import fireindex as fi
    h = historial[(historial["Lead"] == 0) & (historial["Modelo"] == "ECMWF") & (historial["Punto"].isin(list(PUNTOS)))].copy()
    if h.empty:
        return ""
    h["Dia"] = pd.to_datetime(h["Emision"]).dt.normalize()
    h = h.sort_values("Emision").drop_duplicates(["Punto", "Dia"], keep="last")
    h = h[h["Dia"] >= h["Dia"].max() - pd.Timedelta(days=44)]
    dias = pd.date_range(h["Dia"].min(), h["Dia"].max())
    puntos = list(PUNTOS)
    idx = {c: i for i, c in enumerate(CLASES)}
    z, txt, hov = [], [], []
    for pto in puntos:
        g = h[h["Punto"] == pto].set_index("Dia")["Score"]
        fz, ft, fh = [], [], []
        for d in dias:
            if d in g.index:
                sc = float(g[d])
                c = str(fi.to_class(sc, fi.PROV_BREAKS))      # clase con los cortes vigentes, no los de la fecha de emision
                fz.append(idx[c]); ft.append(f"{sc:.0f}")
                fh.append(f"{pto}<br>{_dia(d)}: {c} ({sc:.0f})" + ("<br>combustible húmedo" if sc < 1 else ""))
            else:
                fz.append(None); ft.append(""); fh.append(f"{pto}<br>{_dia(d)}: sin dato")
        z.append(fz); txt.append(ft); hov.append(fh)
    n = len(CLASES)
    escala = []
    for i, c in enumerate(CLASES):
        escala += [[i / n, COLOR[c]], [(i + 1) / n, COLOR[c]]]
    fig = go.Figure(go.Heatmap(z=z, x=[d.strftime("%d-%m") for d in dias], y=puntos, text=txt, texttemplate="%{text}",
                               hovertext=hov, hoverinfo="text", colorscale=escala, zmin=-0.5, zmax=n - 0.5, showscale=False,
                               xgap=3, ygap=3, textfont=dict(size=11, color="#414042")))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, tickangle=-60, type="category")
    fig.update_layout(height=60 + 46 * len(puntos), template="plotly_white", margin=dict(l=110, r=10, t=10, b=60),
                      plot_bgcolor="#EEF1F3", font=dict(family="Nunito, sans-serif", color="#414042"))
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})


def html(ilpi_hoy, historial, actualizado, mapa=None, logo=False):
    fechas = sorted(ilpi_hoy["Fecha_Valida"].unique()) if not ilpi_hoy.empty else []
    filas = ""
    for pto in ilpi_hoy["Punto"].unique() if not ilpi_hoy.empty else []:
        celdas = "".join(_celda(ilpi_hoy[(ilpi_hoy["Punto"] == pto) & (ilpi_hoy["Fecha_Valida"] == f)]) for f in fechas)
        filas += f"<tr><td><b>{pto}</b></td>{celdas}</tr>"
    cab = "".join(f"<th>{_dia(f)}</th>" for f in fechas)
    graf = _historial(historial)
    expl = _explicacion()
    aviso_clases = ("las clases se definen por percentiles del clima histórico de la cuenca, no con incendios reales."
                    if _calibrado() else "las clases son provisorias, aún sin calibrar con incendios reales.")
    kpis = _kpis(ilpi_hoy, mapa)
    sec_kpis = f"<div class='kpis'>{kpis}</div>" if kpis else ""
    sec_mapa = (f"<section><h2>Mapa de peligro</h2><p class='nota'>Celdas de 90 m. Se pinta solo donde hay combustible relevante; roca, nieve y agua quedan sin color.</p>"
                f"{_mapa_html(mapa, ilpi_hoy)}</section>") if mapa else ""
    sec_barras = (f"<section><h2>Superficie con combustible por clase de peligro</h2>"
                  f"<p class='nota'>Proporción de la superficie con combustible en cada clase, por día.</p>{_barras(mapa)}</section>") if mapa else ""
    ley_hist = "<div class='leyenda'>" + "".join("<span class='ley'><i style='background:%s'></i>%s</span>" % (COLOR[c], c) for c in CLASES) + "</div>"
    sec_graf = f"<section><h2>Historial</h2><p class='nota'>Cada casilla es un día en un punto: el color es la clase de peligro y el número, el puntaje (0 = combustible húmedo tras lluvia). Gris: sin dato. Las clases se muestran con los cortes vigentes, también para días anteriores.</p>{graf}{ley_hist}</section>" if graf else ""
    logo_html = "<img src='img/logo-white.png' alt='Tinguiririca Energía'>" if logo else ""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Peligro de incendios forestales · Cuenca del Tinguiririca</title>
<style>{CSS}</style></head><body>
<header><div class="w cab">{logo_html}<div><h1>Índice Local de Peligro de Incendios Forestales</h1>
<p>Cuenca del río Tinguiririca · Tinguiririca Energía</p></div><div class="fecha">Actualizado<br><b>{actualizado}</b></div></div></header>
<div class="w">
<div class="aviso"><b>EXPERIMENTAL.</b> Índice relativo (0–100) con pesos provisorios; {aviso_clases}
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
<li>{_texto_clases()}</li>
<li><b>Limitaciones:</b> la nieve es una estimación del modelo (profundidad y altura de la isoterma 0 °C), sin satélite, y no hay humedad de la vegetación viva (NDMI); el catastro no distingue la carga ni la continuidad del combustible dentro de cada clase; el viento del modelo se corrige con las estaciones propias cuando hay al menos 30 días de comparación, y no incorpora el relieve; el mapa cubre solo la cuenca alta y media.</li>
</ul></details></section>
<footer><img src="img/iso-color.png" alt=""><span>Botón Rojo TE · uso interno y experimental. Mapa base y capa de ignición © colaboradores de OpenStreetMap.</span></footer>
</div></body></html>"""


def json_salida(ilpi_hoy, actualizado):
    return json.dumps({"actualizado": actualizado, "experimental": True,
                       "indice": json.loads(ilpi_hoy.to_json(orient="records", date_format="iso"))}, ensure_ascii=False, indent=1)
