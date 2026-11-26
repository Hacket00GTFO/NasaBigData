# Dashboard NASA — Estadísticas multi-fuente

Dashboard con **Flask + HTML/CSS/JavaScript + Plotly.js**. El servidor carga la clave de `.env`, consulta NASA y entrega al frontend únicamente estadísticas procesadas y configuración pública.

## Instalación y ejecución

Requiere Python 3.10 o posterior (se validó con Python 3.12).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edita NASA_API_KEY en .env; conserva tu archivo si ya existe.
python run.py
```

Abre [http://127.0.0.1:8050](http://127.0.0.1:8050). Los valores de entorno del proceso tienen prioridad sobre `.env`. Reinicia el servidor al cambiar la configuración.

## Configuración

| Variable | Valor predeterminado | Uso |
|---|---|---|
| `NASA_API_KEY` | `DEMO_KEY` | Clave para NeoWs y APOD; permanece en el servidor |
| `NASA_API_BASE_URL` | `https://api.nasa.gov` | Portal autenticado de NASA |
| `DONKI_BASE_URL` | `https://ccmc.gsfc.nasa.gov/DONKI-API/get` | API pública actual de DONKI, sin clave |
| `APOD_FALLBACK_BASE_URL` | `https://science.nasa.gov/wp-json/wp/v2/apod-basic` | Sucesor oficial de APOD si el portal entrega contenido genérico |
| `EONET_BASE_URL` | `https://eonet.gsfc.nasa.gov/api/v3` | API pública EONET, sin clave |
| `DEFAULT_DONKI_DAYS` | `30` | Días incluidos en el rango inicial (1–365) |
| `DEFAULT_EONET_DAYS` | `180` | Días incluidos en el rango inicial (1–3660) |
| `DEFAULT_NEO_DAYS` | `7` | Días incluidos en el rango inicial (1–7) |
| `CACHE_TIMEOUT` | `3600` | TTL en segundos; `0` desactiva la caché de respuestas |
| `CACHE_MAX_ENTRIES` | `512` | Límite de respuestas en memoria |
| `FLASK_PORT` | `8050` | Puerto local |
| `FLASK_DEBUG` | `False` | Activa depuración solo en desarrollo |

La plantilla contiene `DEMO_KEY`. Guarda la clave real exclusivamente en `.env`, excluido de Git. Una clave que haya aparecido en archivos versionados debe reemplazarse en el proveedor; retirarla de la plantilla no elimina el historial.

DONKI cambió de dirección el 30 de septiembre de 2026. Se usa la [nueva API oficial de CCMC](https://ccmc.gsfc.nasa.gov/news/major-updates/), que conserva los parámetros y el formato de respuesta. Para usar explícitamente el portal anterior, configura `DONKI_BASE_URL=https://api.nasa.gov/DONKI`; en ese caso el cliente añade la clave.

## Consultas y procesamiento

- `GET /api/config`: estado de configuración, días iniciales y límites; nunca entrega la clave.
- `GET /api/fetch`: recibe `donki_start`, `donki_end`, `eonet_start`, `eonet_end`, `neo_start`, `neo_end`, todos con formato `YYYY-MM-DD`.
- `GET /api/apod?date=YYYY-MM-DD`: imagen o video astronómico desde 1995-06-16 hasta hoy.

Los rangos incluyen inicio y fin. Se permite consultar un solo día. NeoWs se limita a siete días incluidos; un rango mayor se rechaza con HTTP 400, sin recortarlo silenciosamente. DONKI (CCMC) acepta como máximo 61 días por consulta; EONET admite hasta 3660.

EONET recibe `start`, `end` y `status=all`, conforme a su [documentación oficial](https://eonet.gsfc.nasa.gov/docs/v3). Las estadísticas utilizan solo geometrías dentro del rango seleccionado; los polígonos se representan en el mapa mediante un vértice.

## Rendimiento y errores

El proceso reutiliza un cliente con caché TTL acotada y conexiones HTTP por trabajador. Las consultas idénticas simultáneas comparten la descarga en curso. DONKI, EONET y NeoWs se solicitan concurrentemente; los siete tipos DONKI se descargan con un máximo de cuatro trabajadores. Cambiar únicamente un rango reutiliza las respuestas vigentes de las otras fuentes.

Solo se reintentan fallos de conexión y respuestas transitorias. HTTP 429 activa una pausa de consultas por host según `Retry-After`. Los fallos no se guardan como listas vacías. `/api/fetch` devuelve HTTP 200 con `partial=true` y `errors` por fuente cuando conserva resultados parciales; un KPI no disponible se devuelve como `null`, distinguido de cero.

El frontend valida los rangos antes de consultar, aplica un tiempo máximo de espera, conserva el resultado anterior ante un error general y evita consultas duplicadas durante la carga. Las gráficas de detalle se dibujan al abrir la pestaña y se actualizan con `Plotly.react`. APOD usa la imagen normal del contrato antiguo o `hdurl` cuando el nuevo contrato solo ofrece esa imagen.

El mapa usa el estilo `open-street-map`, con atribución de OpenStreetMap y sin una clave adicional de teselas. El antiguo estilo de CARTO devolvía imágenes con “API KEY REQUIRED”.

APOD valida el contenido antes de guardarlo en caché: una respuesta HTTP 200 con “NASA Science” o el logo genérico no es una fotografía válida. En ese caso consulta el [endpoint WordPress oficial](https://github.com/nasa/apod-api), usando `YYMMDD`. En este nuevo contrato, `url` apunta al artículo y `hdurl` a la imagen; se normalizan antes de enviarlos al navegador. Los videos usan su URL de inserción, y los créditos y explicaciones se convierten a texto. Si falla la descarga de una imagen se muestra un mensaje y el enlace a la publicación original.

La caché reside en memoria **por proceso**: se pierde al reiniciar y no se comparte entre varios servidores. Para despliegues con múltiples procesos conviene una caché externa. Un resultado completo sin caché necesita nueve solicitudes (siete DONKI, una EONET y una NeoWs); APOD se consulta por separado. El servidor incluido es para desarrollo local.

## Pipeline de predicciones

El dashboard acumula un dataset histórico en SQLite (`state/nasa_big_data.db`) y entrena modelos scikit-learn para anticipar la actividad solar y los eventos naturales de EONET a partir de datos previos. El flujo completo es: **backfill → features → entrenamiento → scheduler → pestaña Predicciones**.

```powershell
python -m pip install -r requirements.txt
python scripts/backfill.py --source all    # DONKI 2010→hoy, EONET 2000→hoy, Open-Meteo
python scripts/train_models.py            # entrena y muestra el informe de evaluación
python run.py                             # pestaña "Predicciones" en el dashboard
```

Fuentes del dataset:

- **DONKI** (sin clave): flares FLR, CME, GST y SEP desde 2010, en tramos de 60 días (el endpoint CCMC rechaza rangos de 62 días o más).
- **EONET** (sin clave): eventos naturales desde 2000, fechados por su primera geometría (misma convención que la serie temporal del dashboard).
- **Open-Meteo** (sin clave): clima histórico ERA5 de seis regiones propensas a incendios (California, Amazonía, Australia SE, Siberia Sur, África Central, Canadá Oeste).
- **FIRMS** (opcional, requiere `FIRMS_MAP_KEY` gratuita): focos de incendio VIIRS; solo incremental porque la API limita cada consulta a 10 días.

El backfill es idempotente: puede interrumpirse y reanudarse sin duplicar filas.

Modelos (validación temporal: el último año como prueba final nunca visto; selección de variante en una ventana de validación dentro del entrenamiento, comparadas contra el baseline de persistencia "mañana será igual que hoy"):

| Modelo | Tipo | Objetivo |
|---|---|---|
| `flares_next_day` | Regresión | Número de flares de las próximas 24 h |
| `flares_week_total` | Regresión | Total de flares de los próximos 7 días |
| `flares_x_next_day` | Clasificación | Probabilidad de al menos un flare clase X en 24 h |
| `eonet_<categoría>_next_day` | Regresión | Eventos de la categoría (incendios, tormentas...) en 24 h |

Cada regresión compite entre **tres variantes** y se registra la que gana en validación: *persistencia* (el baseline puro), *delta* (el modelo aprende la corrección sobre la persistencia: pronóstico = hoy + corrección, robusta a los cambios de régimen del registro de eventos) y *directa* (el modelo aprende el valor de mañana tal cual). El clasificador calibra su umbral maximizando F1 sobre probabilidades fuera de muestra (5 pliegues estratificados). Los hiperparámetros se ajustan con `TimeSeriesSplit` y el entrenamiento pondera las filas por recencia (semivida configurable) porque el proceso generador cambia con el tiempo (ciclo solar, automatización de la ingesta de EONET desde 2024).

Las variables (features) son retardos de 1, 2, 3, 7, 14 y 28 días, medias móviles de 7 y 28 días, componentes estacionales (día del año y mes), fase del ciclo solar de ~11 años, la **intensidad numérica de los flares** (log10 del flujo pico en W/m²: un M9.9 ≈ X1.0, lo que el conteo no ve) y los días desde el último flare clase X; los modelos EONET añaden el clima de las regiones propensas a incendios.

Endpoints nuevos:

- `GET /api/predictions`: volumen del dataset, métricas por modelo, pronóstico vigente y backtest de 60 días.
- `POST /api/collect`: refresco incremental de los últimos días (idempotente).
- `POST /api/train`: reentrena todos los modelos con el dataset vigente.

El scheduler (APScheduler, dentro del servidor Flask) refresca los datos cada `SCHEDULER_COLLECT_HOURS` horas, reentrena cada día a las `SCHEDULER_TRAIN_HOUR` UTC y hace una recolección inicial dos minutos después de arrancar. `SCHEDULER_ENABLED=False` lo desactiva.

| Variable | Valor predeterminado | Uso |
|---|---|---|
| `DB_PATH` | `state/nasa_big_data.db` | Ruta de la base SQLite del dataset |
| `MODELS_DIR` | `state/models` | Directorio de los modelos entrenados |
| `FIRMS_MAP_KEY` | vacía | Map key gratuita de FIRMS; sin ella se omite la fuente |
| `DONKI_BACKFILL_TYPES` | `FLR,CME,GST,SEP` | Tipos DONKI que se descargan |
| `DONKI_BACKFILL_START` | `2010-01-01` | Inicio del backfill DONKI |
| `EONET_BACKFILL_START` | `2000-01-01` | Inicio del backfill EONET y Open-Meteo |
| `COLLECT_LOOKBACK_DAYS` | `3` | Días que refresca la recolección incremental |
| `SCHEDULER_ENABLED` | `True` | Tareas programadas dentro de Flask |
| `SCHEDULER_COLLECT_HOURS` | `6` | Horas entre recolecciones |
| `SCHEDULER_TRAIN_HOUR` | `3` | Hora UTC del reentrenamiento diario |
| `ML_TEST_DAYS` | `365` | Días reservados como conjunto de prueba |
| `ML_MIN_TRAIN_ROWS` | `400` | Filas mínimas para entrenar un modelo |
| `ML_VALIDATION_DAYS` | `90` | Días de la ventana de validación para elegir variante |
| `ML_RECENCY_HALFLIFE_DAYS` | `1095` | Semivida (días) de la ponderación por recencia; `0` la desactiva |
| `EONET_MODEL_CATEGORIES` | `3` | Categorías EONET con modelo propio |

## Pruebas

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/js/app.js
```

Las pruebas Python funcionan sin red ni consumo de cuota. Cubren caché entre consultas HTTP, expiración y capacidad, concurrencia, errores parciales, respuestas inválidas, reintentos, protección de la clave, fechas, APOD y estadísticas.

## Estructura

```text
config.py              Carga de .env y configuración
run.py                 Arranque de Flask
app/__init__.py        Factory, dataset y scheduler
app/api.py             Validación, agregación y predicciones REST
app/nasa_client.py     HTTP, concurrencia, caché y errores
app/stats.py           Estadísticas con pandas
app/db.py              Dataset acumulado en SQLite
app/collector.py       Backfill e incremental (DONKI, EONET, Open-Meteo, FIRMS)
app/features.py        Series diarias e ingeniería de variables
app/ml.py              Entrenamiento, evaluación y pronóstico scikit-learn
app/scheduler.py       Recolectar y reentrenar con APScheduler
scripts/backfill.py    Descarga del historial hacia SQLite
scripts/train_models.py Entrenamiento e informe de evaluación
static/index.html      Interfaz
static/js/app.js       Consultas, gráficas y predicciones
static/css/style.css   Estilos
tests/test_nasa.py     Pruebas sin red del cliente y las estadísticas
tests/test_predictions.py Pruebas sin red del pipeline de predicciones
```
