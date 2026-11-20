"""Configuracion del proyecto Boton Rojo TE - Indice Local de Peligro de Incendios (ILPI)."""
import os

ZONA = "America/Santiago"
HORA_REF = 15          # hora local de referencia (ventana critica de CONAF: 14-19 h)
DIAS_PRON = 3          # hoy + 3 dias
SPINUP_DIAS = 60       # dias hacia atras para inicializar el estado si no existe
F_INICIAL = 85.0       # FFMC inicial (valor estandar)

# Puntos de la cuenca (lat, lon, altitud en m). No se incluyen puntos personales.
PUNTOS = {
    "Termas del Flaco": {"lat": -34.957319, "lon": -70.435943, "alt": 1746},
    "BT Tinguiririca":  {"lat": -34.916224, "lon": -70.505040, "alt": 1450},
    "BT Portillo":      {"lat": -34.770882, "lon": -70.449070, "alt": 1470},
    "HLC":              {"lat": -34.833021, "lon": -70.555089, "alt": 1100},
    "HLH":              {"lat": -34.751769, "lon": -70.713893, "alt": 730},
}

# Estaciones Ambient Weather: punto -> nombre de la variable de entorno con la MAC
ESTACIONES = {"BT Portillo": "MAC_PORTILLO", "BT Tinguiririca": "MAC_TINGUIRIRICA"}

# Rutas
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(BASE, "historico")
DATOS = os.path.join(BASE, "datos")
DOCS = os.path.join(BASE, "docs")
F_OBS = os.path.join(HIST, "obs_estaciones.csv")        # horario, estaciones
F_REG = os.path.join(HIST, "clima_registrado.csv")      # 15 h por dia: lo que "paso" (estacion o modelo)
F_PRON = os.path.join(HIST, "clima_pronostico.csv")     # 15 h por dia, por modelo, por emision
F_ESTADO = os.path.join(HIST, "estado_ffmc.csv")        # estado diario del FFMC por punto
F_ILPI = os.path.join(HIST, "ilpi_diario.csv")          # indice emitido (para verificar despues)
F_FOCOS = os.path.join(HIST, "focos_firms.csv")         # focos de calor NASA FIRMS acumulados
F_GRILLA = os.path.join(DATOS, "terreno_90m.npz")         # DEM, pendiente, exposicion y combustible a 90 m
F_TERRENO = os.path.join(DATOS, "puntos_terreno.csv")   # pendiente, exposicion, combustible, NDMI
