# Dashboard NASA — Estadísticas Multi-fuente

Dashboard web interactivo que consume varios endpoints del portal [api.nasa.gov](https://api.nasa.gov/) usando una **developer key** declarada en `.env`. Muestra estadísticas de clima espacial (DONKI), eventos terrestres (EONET), asteroides (NeoWs) y la imagen astronómica del día (APOD).

## Stack

- **Python 3.9+**
- **Flask** + **Dash** (Plotly) para el frontend interactivo
- **Dash Bootstrap Components** para el diseño
- **Pandas** para manipulación de datos
- **Requests** para llamadas HTTP con cache y reintentos

## Endpoints usados (base `https://api.nasa.gov`)

| Endpoint | Servicio | Descripción |
|----------|----------|-------------|
| `/donki/{CME,FLR,GST,SEP,HSS,MPC,RBE}` | DONKI | Space Weather Database — clima espacial |
| `https://eonet.gsfc.nasa.gov/api/v3/events` | EONET | Eventos terrestres (incendios, tormentas, volcanes, hielo) |
| `/neo/rest/v1/feed` | NeoWs | Near Earth Objects — asteroides cercanos |
| `/planetary/apod` | APOD | Astronomy Picture of the Day |

## Características

- **4 pestañas de visualización:**
  1. **Clima Espacial (DONKI)** — conteos por tipo (CME/FLR/GST/SEP/HSS), serie temporal, distribución de flares por clase (X/M/C/B), Kp máximo de tormentas geomagnéticas, tabla de eventos recientes
  2. **Eventos Terrestres (EONET)** — conteos por categoría, serie temporal apilada, mapa interactivo con `scatter_mapbox`, top fuentes
  3. **Asteroides (NeoWs)** — NEOs por día, distribución de diámetros, peligrosos vs no peligrosos, distancia mínima, velocidad media, tabla de los más cercanos
  4. **APOD** — imagen astronómica del día con selector de fecha y explicación
- **Filtros configurables** por pestaña: rangos de fechas independientes para DONKI, EONET y NeoWs
- **KPI cards** superiores: CMEs, flares solares, tormentas geomagnéticas, asteroides
- **Cache en memoria** (TTL configurable) y reintentos con backoff exponencial
- **Manejo de rate limit** HTTP 429 con mensaje claro (DEMO_KEY limitada)
- **Configuración vía `.env`** (API key, URLs, días por defecto, puerto)

## Instalación

```bash
# 1. Crear y activar entorno virtual
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Edita .env y pon tu NASA_API_KEY (solicitada en https://api.nasa.gov/)
```

### Solicitar tu API key

1. Visita https://api.nasa.gov/
2. Rellena el formulario "Generate API Key"
3. Recibirás tu key por email
4. Pégala en `.env` como `NASA_API_KEY=tu_key_aqui`

> **DEMO_KEY** funciona sin registro pero está limitada a **30 requests/hora** y **50 requests/día**. Para uso intensivo, solicita tu propia key.

## Configuración (.env)

| Variable | Descripción | Default |
|----------|-------------|---------|
| `NASA_API_KEY` | Tu developer key de api.nasa.gov | `DEMO_KEY` |
| `NASA_API_BASE_URL` | URL base de la API | `https://api.nasa.gov` |
| `EONET_BASE_URL` | URL base de EONET | `https://eonet.gsfc.nasa.gov/api/v3` |
| `DEFAULT_DONKI_DAYS` | Días hacia atrás para DONKI | `30` |
| `DEFAULT_EONET_DAYS` | Días hacia atrás para EONET | `180` |
| `DEFAULT_NEO_DAYS` | Días hacia atrás para NeoWs (máx 7) | `7` |
| `CACHE_TIMEOUT` | TTL de cache en segundos | `3600` |
| `FLASK_PORT` | Puerto del servidor | `8050` |
| `FLASK_DEBUG` | Modo debug | `True` |

## Ejecución

```bash
python run.py
```

Abre [http://127.0.0.1:8050](http://127.0.0.1:8050) en tu navegador.

## Uso

1. En el sidebar izquierdo ajusta los **rangos de fechas** para cada fuente (DONKI, EONET, Asteroides).
2. Pulsa **Consultar** — se descargan los datos de los tres endpoints.
3. Navega entre las pestañas para ver las estadísticas.
4. En **APOD** elige una fecha y pulsa **Obtener APOD** para ver la imagen astronómica.

## Notas sobre la API

- **api.nasa.gov** requiere una **developer key** (gratuita) que se solicita en su web.
- **DEMO_KEY** está limitada a 30 req/hora y 50 req/día. La app cachea respuestas (1h) para minimizar llamadas.
- **NeoWs feed**: máximo 7 días por request (la app lo recorta automáticamente).
- **DONKI**: rangos largos devuelven muchos eventos; se recomienda 30 días por defecto.
- **EONET** no requiere key pero la respeta si se pasa.

## Estructura del proyecto

```
NasaBigData/
├── .env.example          # Plantilla de configuración
├── .gitignore
├── requirements.txt
├── README.md
├── config.py             # Carga de .env y settings
├── run.py                # Entry point
├── app/
│   ├── __init__.py       # Factory Flask+Dash
│   ├── nasa_client.py    # Cliente api.nasa.gov (DONKI, EONET, NeoWs, APOD)
│   ├── stats.py          # Funciones estadísticas por endpoint
│   └── layouts/
│       ├── main.py       # Layout principal + sidebar + KPIs
│       ├── donki.py      # Pestaña clima espacial
│       ├── eonet.py      # Pestaña eventos terrestres
│       ├── asteroids.py  # Pestaña asteroides
│       └── apod.py       # Pestaña APOD
└── callbacks/
    ├── filters.py        # Filtros globales + KPIs + render tabs
    ├── donki.py
    ├── eonet.py
    ├── asteroids.py
    └── apod.py
```

## Tipos de eventos DONKI

| Código | Descripción |
|--------|-------------|
| `CME` | Coronal Mass Ejection (eyección de masa coronal) |
| `FLR` | Solar Flare (flare solar, clases X/M/C/B/A) |
| `GST` | Geomagnetic Storm (tormenta geomagnética, Kp index) |
| `SEP` | Solar Energetic Particle |
| `HSS` | High Speed Stream |
| `MPC` | Magnetopause Crossing |
| `RBE` | Radiation Belt Enhancement |

## Categorías EONET

- Wildfires (incendios)
- Severe Storms (tormentas severas)
- Volcanoes (volcanes)
- Sea and Lake Ice (hielo marino/lacustre)
- Earthquakes (terremotos)
- Landslides (deslizamientos)
- Manmade (eventos antrópicos)
- Snow (nieve)
- Temp Extremes, Water Color, Drought...
