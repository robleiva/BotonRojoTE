"""Orquesta el calculo diario: recolectar -> registrar -> actualizar estado -> pronosticar indice -> publicar.
Uso: python -m ilpi.run_daily"""
import os
import datetime as dt
import numpy as np
import pandas as pd
from . import colectores as col, pipeline as pl, reporte, grilla, firms, alerta, nieve as nv, viento as vi, rayos as ry, boton_rojo as br_conaf
from .config import *


def _leer(ruta, fechas=()):
    if os.path.exists(ruta):
        d = pd.read_csv(ruta)
        for c in fechas:
            if c in d:
                d[c] = pd.to_datetime(d[c])
        return d
    return pd.DataFrame()


def _upsert(nuevo, previo, clave):
    if previo.empty:
        return nuevo
    return pd.concat([previo, nuevo]).drop_duplicates(subset=clave, keep="last")


def cargar_terreno():
    t = _leer(F_TERRENO)
    out = {}
    pesos = {"pastizal": 1.0, "matorral": 0.85, "plantacion": 0.9, "bosque_nativo": 0.5, "agricola": 0.4, "sin_combustible": 0.0}
    for _, r in t.iterrows():
        out[r["Punto"]] = {"slope": float(r["slope"]) if pd.notna(r["slope"]) else 10.0,
                           "aspect": float(r["aspect"]) if pd.notna(r["aspect"]) else np.nan,
                           "fuel_w": pesos.get(str(r["fuel_class"]).strip(), 0.85),
                           "ndmi": float(r["ndmi"]) if pd.notna(r.get("ndmi", np.nan)) else np.nan}
    return out


def main():
    os.makedirs(HIST, exist_ok=True); os.makedirs(DOCS, exist_ok=True)
    ahora = pd.Timestamp.now(tz=ZONA)
    hoy = ahora.tz_localize(None).normalize()
    print(f"== ILPI {ahora:%Y-%m-%d %H:%M} (hora de Chile)")

    # 1. Estaciones -> historico horario
    api, app = os.environ.get("AMBIENT_API_KEY", "").strip(), os.environ.get("AMBIENT_APPLICATION_KEY", "").strip()
    nuevas = [col.fetch_ambient(col.formatear_mac(os.environ.get(var, "")), pto, api, app) for pto, var in ESTACIONES.items()]
    nuevas = [n for n in nuevas if not n.empty]
    obs = _leer(F_OBS, ["Fecha_Local"])
    if nuevas:
        obs = _upsert(pd.concat(nuevas), obs, ["Punto", "Fecha_Local"])
        obs.to_csv(F_OBS, index=False)
    print(f"[estaciones] {0 if obs.empty else len(obs)} registros horarios en historico")
    avisos_est = []
    for pto in ESTACIONES:                       # aviso si una estacion lleva dias sin reportar
        o = obs[obs["Punto"] == pto] if not obs.empty else obs
        if o.empty or (hoy - o["Fecha_Local"].max().normalize()).days >= 2:
            ult = "nunca" if o.empty else f"{o['Fecha_Local'].max():%Y-%m-%d %H:%M}"
            print(f"[estaciones] ATENCION: {pto} sin datos recientes (ultimo registro: {ult}); el indice de ese punto usa el modelo")
            avisos_est.append(f"La estación {pto} no reporta datos " + ("todavía" if o.empty else f"desde el {o['Fecha_Local'].max():%d-%m}") +
                              ": el índice de ese punto se calcula solo con el modelo.")

    # 2. Modelos (Open-Meteo): 15 h registrado (pasado) y pronostico
    reg_modelo, pron = [], []
    for pto, m in PUNTOS.items():
        mods, z = col.fetch_openmeteo(m["lat"], m["lon"], past_days=SPINUP_DIAS, forecast_days=DIAS_PRON + 1)
        for nombre, dfh in mods.items():
            c = pl.clima_15h(dfh)
            if c.empty:
                continue
            c["Punto"], c["z_ref"] = pto, z
            pron.append(c[c["Fecha"] >= hoy].assign(Modelo=nombre))
            if nombre == "ECMWF":
                reg_modelo.append(c[c["Fecha"] < hoy].assign(Fuente="ECMWF"))
    if not reg_modelo or not pron:
        raise SystemExit("Sin datos de Open-Meteo: no se emite indice hoy (el estado no se modifica).")
    reg_modelo, pron = pd.concat(reg_modelo), pd.concat(pron)
    pron = pron[pron["Fecha"] <= hoy + pd.Timedelta(days=DIAS_PRON)]

    # 2b. Viento: correccion con las estaciones propias (solo con >= 30 dias de comparacion)
    pron_hist = _leer(F_PRON, ["Fecha", "Emision"])
    fac_v, info_v = vi.factores(obs, pron_hist, list(PUNTOS))
    for pto, (n, razon) in info_v.items():
        print(f"[viento] {pto}: {n} dias comparados, razon mediana medido/modelo {razon:.2f} -> " +
              (f"factor aplicado {fac_v[pto]:.2f}" if pto in fac_v else f"sin corregir (faltan {vi.MIN_DIAS - n} dias)"))
    if not info_v:
        print("[viento] sin mediciones de viento de estaciones: se usa el modelo")
    pron_crudo = pron                       # lo archivado es el viento SIN corregir (si no, la correccion se acumularia dia a dia)
    reg_modelo, pron = vi.aplicar(reg_modelo, fac_v), vi.aplicar(pron, fac_v)

    # 3. Clima registrado: estacion (si esta completa) > modelo
    reg = reg_modelo.copy()
    for pto in ESTACIONES:
        o = obs[obs["Punto"] == pto] if not obs.empty else pd.DataFrame()
        c = pl.clima_15h(o)
        if c.empty:
            continue
        c = c[(c["Fecha"] < hoy)].dropna(subset=["T", "RH", "V", "PP24"])
        c["Punto"], c["Fuente"], c["z_ref"] = pto, "ESTACION", np.nan
        reg = pd.concat([reg[~((reg["Punto"] == pto) & reg["Fecha"].isin(c["Fecha"]))], c])
    prev_reg = _leer(F_REG, ["Fecha"])
    reg_total = _upsert(reg, prev_reg, ["Punto", "Fecha"])
    reg_total.to_csv(F_REG, index=False)

    # 3b. Nieve (modelo): profundidad e isoterma 0 C por punto. Si falla, el indice no cambia.
    nv_nuevo = []
    for pto, m in PUNTOS.items():
        d = nv.fetch(m["lat"], m["lon"], past_days=3, forecast_days=DIAS_PRON + 1)
        if not d.empty:
            nv_nuevo.append(d.assign(Punto=pto))
    nieve_df = _upsert(pd.concat(nv_nuevo)[nv.COLS], _leer(F_NIEVE, ["Fecha"]), ["Punto", "Fecha"]) if nv_nuevo else _leer(F_NIEVE, ["Fecha"])
    if not nieve_df.empty:
        nieve_df.to_csv(F_NIEVE, index=False)
    ult = nieve_df[nieve_df["Fecha"] == hoy] if not nieve_df.empty else nieve_df
    print(f"[nieve] {len(nv_nuevo)}/{len(PUNTOS)} puntos con dato; hoy: " +
          (", ".join(f"{r.Punto} {r.NIEVE:.2f} m, isoterma 0 C {r.FZL:.0f} m" for r in ult.itertuples()) if not ult.empty else "sin dato (no se aplica nieve)"))

    # 3c. Posibilidad de tormenta electrica (CAPE del modelo). Si falla, simplemente no se muestra.
    ry_nuevo = []
    for pto, m in PUNTOS.items():
        d = ry.fetch(m["lat"], m["lon"], past_days=2, forecast_days=DIAS_PRON + 1)
        if not d.empty and d["CAPE"].notna().any():
            ry_nuevo.append(d.assign(Punto=pto))
    rayos_df = _upsert(pd.concat(ry_nuevo)[ry.COLS], _leer(F_RAYOS, ["Fecha"]), ["Punto", "Fecha"]) if ry_nuevo else _leer(F_RAYOS, ["Fecha"])
    if not rayos_df.empty:
        rayos_df.to_csv(F_RAYOS, index=False)
    tormenta = ry.por_dia(rayos_df, desde=hoy)
    print(f"[rayos] {len(ry_nuevo)}/{len(PUNTOS)} puntos con CAPE; " +
          (", ".join(f"{r.Fecha:%d-%m} CAPE {r.CAPE:.0f} -> {ry.NIVELES[r.Nivel]}" for r in tormenta.itertuples()) if not tormenta.empty else "sin dato (no se muestra)"))

    # 4. Estado + indice
    estado = _leer(F_ESTADO, ["Fecha"])
    if estado.empty:
        estado = pd.DataFrame(columns=["Punto", "Fecha", "FFMC", "M", "Calidad", "Fuente"])
    nuevo_estado, ilpi = pl.calcular(reg_total, pron, estado, cargar_terreno(), hoy)
    ilpi = nv.marcar_puntos(ilpi, nieve_df, PUNTOS)
    pd.concat([estado, nuevo_estado]).drop_duplicates(["Punto", "Fecha"], keep="last").to_csv(F_ESTADO, index=False)
    hist = _upsert(ilpi, _leer(F_ILPI, ["Emision", "Fecha_Valida"]), ["Emision", "Punto", "Modelo", "Fecha_Valida"])
    hist.to_csv(F_ILPI, index=False)

    # 5. Pronostico del clima por modelo, archivado (para verificar despues)
    p_arch = _upsert(pron_crudo.assign(Emision=hoy), _leer(F_PRON, ["Fecha", "Emision"]), ["Emision", "Punto", "Modelo", "Fecha"])
    p_arch.to_csv(F_PRON, index=False)

    # 6. WRF-SMN: solo se archiva (no alimenta el indice en esta version)
    if os.environ.get("USAR_WRF", "1") == "1":
        try:
            utc = dt.datetime.now(dt.timezone.utc)
            corrida = dt.datetime(utc.year, utc.month, utc.day, 0) - (dt.timedelta(hours=12) if utc.hour < 7 else dt.timedelta())
            w = col.fetch_wrf(corrida)
            if not w.empty:
                filas = []
                for pto, g in w.groupby("Punto"):
                    c = pl.clima_15h(g)
                    if not c.empty:
                        filas.append(c.assign(Punto=pto, Modelo="WRF", Emision=hoy, z_ref=np.nan))
                if filas:
                    _upsert(pd.concat(filas), _leer(F_PRON, ["Fecha", "Emision"]), ["Emision", "Punto", "Modelo", "Fecha"]).to_csv(F_PRON, index=False)
        except Exception as e:
            print(f"[WRF] omitido: {e}")

    # 6b. Focos de calor NASA FIRMS (verificacion y calibracion futura; no alimenta el indice)
    clave_firms = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if clave_firms:
        try:
            nuevos, errores = firms.fetch_todas(clave_firms, hoy)
            for e in errores:
                print(f"[FIRMS] {e}")
            acum = firms.acumular(nuevos, _leer(F_FOCOS))
            acum.to_csv(F_FOCOS, index=False)
            print(f"[FIRMS] {len(nuevos)} focos descargados, {len(acum)} acumulados")
        except Exception as e:
            print(f"[FIRMS] omitido: {e}")
    else:
        print("[FIRMS] sin clave (FIRMS_MAP_KEY): se omite")

    # 7. Salidas
    stamp = f"{ahora:%Y-%m-%d %H:%M} (hora de Chile)"
    hoy_df = ilpi
    mapa = None
    try:
        mapa = grilla.calcular_mapa(reg_total, pron, hoy, F_GRILLA, ruta_ignicion=F_IGNICION, nieve=nieve_df)
        print(f"[mapa] {len(mapa['fechas'])} dias, {mapa['resumen'][0]['Ha_combustible']} ha con combustible")
    except Exception as e:                      # el mapa nunca debe impedir la emision por punto
        print(f"[mapa] omitido: {e}")
    # estado oficial de Boton Rojo (CONAF): se usa en la pagina y en el correo
    fechas_br = sorted(hoy_df[hoy_df["Modelo"] == "ECMWF"]["Fecha_Valida"].unique())
    br = br_conaf.consultar(COMUNAS_BR, [pd.Timestamp(f).strftime("%Y-%m-%d") for f in fechas_br])
    print("[botón rojo]", "no disponible" if br is None else {f: {c: (None if v is None else v["activo"]) for c, v in d.items()} for f, d in br.items()})
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(reporte.html(hoy_df, hist, stamp, mapa, avisos=avisos_est, tormenta=tormenta, br=br, logo=os.path.exists(os.path.join(DOCS, "img", "logo-white.png"))))
    with open(os.path.join(DOCS, "ilpi_ultimo.json"), "w", encoding="utf-8") as f:
        f.write(reporte.json_salida(hoy_df, stamp))
    print("[correo]", alerta.enviar_si_corresponde(hoy_df, stamp, tormenta=tormenta, br=br))
    print("[feed]", alerta.actualizar_feed(hoy_df, stamp, os.path.join(DOCS, "alertas.xml"), hoy, tormenta=tormenta, br=br))
    print(hoy_df[hoy_df["Modelo"] == "ECMWF"].pivot(index="Punto", columns="Fecha_Valida", values="Clase").to_string())


if __name__ == "__main__":
    main()
