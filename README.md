# Botón Rojo TE — Índice Local de Peligro de Incendios (ILPI)

Índice **experimental** de peligro relativo (0–100) de incendios forestales para la cuenca del río Tinguiririca,
calculado cada día de forma automática con GitHub Actions. **No es un pronóstico oficial** ni predice la ocurrencia
de incendios; la referencia oficial es CONAF / SENAPRED.

## Cómo funciona
1. **Estaciones** (Ambient Weather: BT Portillo, BT Tinguiririca) → temperatura, humedad, viento y lluvia horarios.
2. **Modelos** (Open-Meteo: ECMWF IFS y GFS) → mismas variables, pasado reciente y 3 días de pronóstico, a las 15:00 locales.
3. **Clima registrado** de cada día = estación (si el día está completo) o, si no, ECMWF corregido por altitud.
4. **Estado de humedad del combustible fino** (módulo FFMC de Van Wagner, 1987) que se arrastra día a día y se guarda en `historico/estado_ffmc.csv`.
5. **Índice** = sequedad del combustible muerto^0,45 × combustible^0,35 × propagación^0,20 (media geométrica ponderada).
   Detalle y supuestos en `ESPECIFICACION.md`.
6. Mapa: el índice también se calcula por celda de 90 m en toda la cuenca (`ilpi/grilla.py`) con DEM, pendiente, exposición y combustible de `datos/terreno_90m.npz` (catastro de uso de suelo y vegetación de CONAF 2020, con ESA WorldCover como respaldo fuera del límite de la cuenca), que se genera una vez con `scripts/preparar_terreno.py RUTA_TESIS RUTA/lulc_cuenca.tif` desde los TIFF de la tesis. El clima de los puntos se interpola por distancia y se corrige por altitud.
7. Salida: `docs/index.html`, `docs/ilpi_ultimo.json` y el archivo `historico/ilpi_diario.csv` (todo lo emitido, para verificar después).

El **WRF-SMN** se descarga y archiva (`historico/clima_pronostico.csv`) pero **todavía no alimenta el índice**: los nombres de sus
variables de humedad y viento no están verificados. En el log de la primera corrida busca las líneas `[WRF] variables del archivo`.

## Capa de ignición humana (OpenStreetMap)
Capa aparte del peligro (no entra en el índice): qué tan cerca está cada celda de caminos, edificaciones y líneas de transmisión. Se genera con el flujo **Capa de ignición (OSM)** (Actions, ejecución manual), que descarga los datos de OpenStreetMap con la Overpass API y guarda `datos/ignicion_90m.npz`. La página la muestra como una pestaña más del mapa. Pesos y alcances en `ilpi/ignicion.py` (supuestos sin calibrar). Datos © colaboradores de OpenStreetMap (licencia ODbL).

## Correo diario (opcional)
Si defines estos secretos del repositorio, el flujo envía cada mañana un resumen por correo: `SMTP_HOST`, `SMTP_PORT` (465 por defecto), `SMTP_USER`, `SMTP_PASS` y `EMAIL_DESTINO` (el listado de difusión; varias direcciones separadas por coma). Opcionales: `EMAIL_REMITENTE` y `EMAIL_MODO` (`diario`, por defecto, o `alerta`, que solo envía si algún punto llega a Alto o más). Sin `SMTP_HOST` y `EMAIL_DESTINO` no se envía nada. En el log busca la línea `[correo]`.

## Puesta en marcha
1. **Secretos** del repositorio (Settings → Secrets and variables → Actions): `AMBIENT_API_KEY`, `AMBIENT_APPLICATION_KEY`, `MAC_PORTILLO`, `MAC_TINGUIRIRICA`.
2. **Revisa `datos/puntos_terreno.csv`**: la clase de combustible (`pastizal`, `matorral`, `plantacion`, `bosque_nativo`, `agricola`, `sin_combustible`) de cada punto es un *placeholder*; corrígela con tu criterio.
3. (Una vez, con internet) `python scripts/calcular_terreno.py` para calcular pendiente y exposición.
4. Ejecuta el flujo a mano: pestaña Actions → "ILPI diario" → Run workflow.
5. Publicación web opcional: crea la variable `PUBLICAR_PAGES = true` y habilita Pages (fuente: GitHub Actions). Si el repositorio es privado, Pages requiere un plan que lo permita.

La primera corrida **se inicializa sola**: toma 60 días hacia atrás desde Open-Meteo y calcula el estado del FFMC.

## Limitaciones conocidas (versión 0.1)
- Pesos y clases son **provisorios**: se recalibrarán con focos de calor (NASA FIRMS) e incendios históricos.
- Sin nieve ni NDMI: a inicios de temporada puede sobrestimar el peligro en la alta cuenca.
- Las dos estaciones están a ~1.450 m; el punto bajo (HLH, 730 m) depende del modelo, corregido por altitud.
- Si falta un día de datos, el estado se arrastra y el día se marca con `*` (calidad `sin_dato`).
- El repositorio no incluye ningún punto de carácter personal; mantenlo así si lo haces público.

## Desarrollo
```
pip install -r requirements.txt
python -m pytest -q          # 18 pruebas, sin red
python -m ilpi.run_daily     # requiere internet y variables de entorno de las estaciones
```
Estructura: `ilpi/` (código), `datos/` (terreno y combustible), `historico/` (estado y archivos acumulados), `docs/` (salida), `tests/`.
