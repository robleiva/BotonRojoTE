# Índice Local de Peligro de Incendios (ILPI) — Cuenca del Tinguiririca
**Proyecto Botón Rojo TE · Especificación v0.1 · 2 nov 2026 · Estado: pipeline diario implementado (sin ejecutar con datos reales aún); índice sin calibrar**

## 1. Objetivo y alcance
Índice de **peligro relativo 0–100** por celda (≈1–10 km) y día, ajustado a temperatura, topografía, viento, combustible y humedad de la cuenca. Mide *qué tan favorables son las condiciones para que un incendio se inicie y se propague*; **no** predice ocurrencia ni localiza igniciones.

Por qué un índice propio: el FWI global del ECMWF tuvo desempeño "excepcionalmente pobre" en Sudamérica (Di Giuseppe et al. 2020), fue calibrado en bosque boreal canadiense y no considera vegetación ni ignición. El Botón Rojo de CONAF no tiene metodología ni API públicas.

## 2. Estructura
`ILPI_bruto = sequedad^0.45 × combustible^0.35 × propagación'^0.20`, con propagación' = 0,25 + 0,75·propagación (el fuego avanza aunque no haya viento ni pendiente). Media geométrica ponderada: si un factor se anula (combustible inexistente, vegetación empapada, nieve) el peligro cae, aunque los otros sean extremos. **Pesos a priori; se calibran (§5).**

| Componente | Entradas | Cálculo (ver `fireindex.py`) |
|---|---|---|
| **Meteorología en el sitio** | T, HR de la celda del modelo y su altitud; altitud del sitio | T − 0,0065 K/m·Δz; punto de rocío − 0,002 K/m·Δz; HR recalculada |
| **Sequedad (0–1)** | Humedad del combustible fino muerto *m* (%) | *m* sale del módulo FFMC de Van Wagner (1987) con T, HR, viento y lluvia 24 h; sequedad = (30 − *m*)/24 acotada a 0–1; ×(0,9–1,1) según exposición (cara norte, más sol, hemisferio sur) |
| **Combustible (0–1)** | Tipo de cobertura; NDMI satelital | peso por tipo (pastizal 1,0; plantación 0,9; matorral 0,85; bosque nativo 0,5; agrícola 0,4; sin combustible 0) × (0,6 + 0,4·sequedad del combustible vivo); NDMI faltante → neutro 0,5 |
| **Propagación (0–1)** | Viento (km/h, dirección), pendiente, exposición | 1 − (1 − f_viento)(1 − f_pendiente); f_viento = 1 − e^(−V/25); f_pendiente = tan(pendiente) × (0,6 + 0,4·alineación del viento con la ladera arriba) |
| **Nieve** | Profundidad de nieve | > 2 cm → índice 0 |

**Score 0–100.** Objetivo: percentil del valor bruto dentro de la distribución histórica de temporada de la propia cuenca (clases por percentil: Bajo < 50 · Moderado 50–75 · Alto 75–90 · Muy alto 90–97 · Extremo > 97). **Versión 0.1, mientras no exista esa distribución:** score provisorio = 100 × valor bruto, con clases Bajo < 30 · Moderado 30–50 · Alto 50–65 · Muy alto 65–80 · Extremo ≥ 80. Estos cortes son arbitrarios y se reemplazan al calibrar.

**Ignición humana: capa separada** (distancia a rutas como la I‑45, viviendas, interfaz urbano‑rural, uso agrícola). No se mezcla con el peligro meteorológico, para poder leer "qué tan seco está" y "qué tan probable es un inicio" por separado.

## 3. Datos
| Dato | Fuente | Estado |
|---|---|---|
| Meteorología diaria 15:00 local | Estaciones Tinguiririca Energía (verdad local) + ERA5‑Land vía Open‑Meteo (≈9 km) + estaciones DMC/DGA | ERA5‑Land listo en `fetch_data.py`; **estaciones propias por incorporar** |
| Pronóstico (operación) | Modelo numérico abierto de alta resolución + DMC | Por definir |
| Topografía | DEM Copernicus 90 m (Open‑Meteo Elevation); idealmente DEM 30 m | Pendiente/exposición a ~500 m listas |
| Combustible | Catastro de uso de suelo y vegetación CONAF, actualización 2020 (raster `lulc_cuenca.tif`, 19 clases); ESA WorldCover como respaldo fuera del límite de la cuenca | En uso desde v0.3 |
| Estado hídrico vegetación | NDMI Sentinel‑2 (10–20 m) / MODIS | **Pendiente** |
| Incendios para calibrar y validar | NASA FIRMS VIIRS; registros CONAF | FIRMS en `fetch_data.py` (requiere MAP_KEY); CONAF por solicitar |

**Capa de ignición humana (v0.3).** Exposición 0–100 = 1 − (1 − p_caminos)(1 − p_edificios)(1 − p_líneas), con p = peso × exp(−distancia/alcance). Caminos (carreteras y huellas, peso 0,8 y 0,5; alcance 300 m), edificaciones (peso 1,0; 500 m) y líneas de transmisión (línea 0,6, minor_line 0,4; 200 m) desde OpenStreetMap. Se muestra aparte del peligro y se calibrará con registros de causa de incendios de CONAF.

**Calibración por percentiles (v0.3).** Con los cortes provisorios (30/50/65/80) casi toda la cuenca cae en Alto o más incluso con clima suave, por lo que las clases no discriminan. Se reemplazan por percentiles 50/75/90/97 del puntaje diario (15:00) en octubre–abril, calculados con ERA5-Land desde julio de 2000 sobre los cinco puntos (`ilpi/calibracion.py`, `scripts/calibrar_percentiles.py`). Limitación: el ERA5-Land es una malla de ~9 km y puede diferir de las estaciones propias; la clase mide qué tan inusual es el día para la cuenca, no la probabilidad de fuego.

## 4. Implementación (ver README del repositorio)
- `ilpi/fireindex.py`: motor del índice (pruebas automáticas, incluido el caso de referencia FFMC 87,7 de Van Wagner y Pickett 1985).
- `ilpi/colectores.py`: estaciones Ambient, Open-Meteo (ECMWF IFS y GFS) y WRF-SMN.
- `ilpi/pipeline.py`: estado diario del FFMC, correcciones de altitud y cálculo del índice por punto, día y modelo.
- `ilpi/run_daily.py`: orquestación diaria; `.github/workflows/diario.yml`: ejecución programada.
- Archivos acumulados en `historico/`: clima registrado, pronósticos archivados, estado del FFMC e índice emitido (insumo de la verificación futura).
- Aún **no ejecutado con datos reales** (sin acceso a red en el entorno de desarrollo): 18 pruebas pasan con datos simulados, incluida una corrida completa idempotente.

## 5. Calibración y validación
1. Temporada de prueba inicial: oct 2016 – mar 2017; después 2023‑24 y 2025‑26.
2. División **cronológica** 70/30 (nunca aleatoria, para no filtrar información del futuro).
3. Comparación contra: FFMC solo, temperatura sola, FWI de Copernicus y días de Botón Rojo.
4. Métricas: AUC y **tasa de focos por clase** (el índice sirve si la tasa sube de Bajo a Extremo).
5. Regresión logística (o GAM) sobre los logaritmos de los tres componentes para ajustar pesos.
6. Un componente constante en el panel no es calibrable: mientras el combustible sea un valor fijo, su peso no se identifica.

## 6. Limitaciones conocidas
- Focos FIRMS incluyen quemas agrícolas, industria y fuegos fuera de vegetación; sesgan la etiqueta. Una celda de 10 km con foco no equivale a "incendio forestal".
- ERA5‑Land (≈9 km) suaviza viento y humedad en un valle encajonado; las estaciones propias deben corregirlo.
- Las constantes (30 % y 6 % de humedad, 25 km/h, pesos de combustible) son supuestos de partida.
- Un solo satélite polar pasa pocas veces al día: la etiqueta pierde fuegos breves o con nubes.
- El índice describe peligro relativo; la decisión operativa requiere umbrales validados con CONAF.

## 7. Próximos pasos
1. Ejecutar `fetch_data.py` en un equipo con internet y correr `backtest.py` con datos reales.
2. Incorporar mapa de combustibles y NDMI.
3. Cargar series de las estaciones de Tinguiririca y medir el sesgo de ERA5‑Land.
4. Definir con CONAF/COGRID umbrales de clase y formato de alerta.

## Referencias
Van Wagner (1987), *Development and structure of the Canadian Forest Fire Weather Index System*. · Di Giuseppe et al. (2020), NHESS 20, 2365. · Gajardo et al. (2025), *Fire* 8(3), 113. · Bohlmann y Laine (2024), NHESS 24, 4225.


## Mapa por celda (v0.2)
- Terreno a 90 m (datos/terreno_90m.npz): altitud, pendiente, exposición y peso de combustible (media por celda del catastro CONAF, 3×3 submuestras; pesos provisorios: bosque nativo 0,5; matorral y matorral arborescente 0,85; matorral-pradera 0,95; pradera 1,0; matorral con suculentas 0,6; rotación cultivo-pradera 0,5; agrícola 0,4; bofedal 0,1; vega 0,2; sobre el límite altitudinal 0,1; otros sin vegetación 0,05; agua, nieve, glaciar, roca y urbano 0. Donde CONAF no tiene dato, ESA WorldCover 10 m). Cobertura solo hasta la longitud -70,726 (no incluye La Rufina ni San Fernando).
- Clima: los puntos (estación o ECMWF) se llevan a 1.500 m, se interpolan por distancia inversa al cuadrado y se corrigen a la altitud de cada celda; viento con media vectorial.
- FFMC por celda: se reconstruye en cada corrida con los últimos 30 días registrados (F0 = 85) y se continúa con el pronóstico ECMWF.
- Se colorean solo celdas con peso de combustible >= 0,15. Clases provisorias (30/50/65/80), sin calibrar.
- Limitaciones: el catastro no mide carga ni continuidad del combustible dentro de cada clase; sin NDMI ni nieve; el viento no incorpora efectos del relieve; la lluvia no varía con la altitud.
