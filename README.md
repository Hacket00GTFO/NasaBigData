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

Los rangos incluyen inicio y fin. Se permite consultar un solo día. NeoWs se limita a siete días incluidos; un rango mayor se rechaza con HTTP 400, sin recortarlo silenciosamente. DONKI y EONET tienen límites de aplicación de 365 y 3660 días, respectivamente.

EONET recibe `start`, `end` y `status=all`, conforme a su [documentación oficial](https://eonet.gsfc.nasa.gov/docs/v3). Las estadísticas utilizan solo geometrías dentro del rango seleccionado; los polígonos se representan en el mapa mediante un vértice.

## Rendimiento y errores

El proceso reutiliza un cliente con caché TTL acotada y conexiones HTTP por trabajador. Las consultas idénticas simultáneas comparten la descarga en curso. DONKI, EONET y NeoWs se solicitan concurrentemente; los siete tipos DONKI se descargan con un máximo de cuatro trabajadores. Cambiar únicamente un rango reutiliza las respuestas vigentes de las otras fuentes.

Solo se reintentan fallos de conexión y respuestas transitorias. HTTP 429 activa una pausa de consultas por host según `Retry-After`. Los fallos no se guardan como listas vacías. `/api/fetch` devuelve HTTP 200 con `partial=true` y `errors` por fuente cuando conserva resultados parciales; un KPI no disponible se devuelve como `null`, distinguido de cero.

El frontend valida los rangos antes de consultar, aplica un tiempo máximo de espera, conserva el resultado anterior ante un error general y evita consultas duplicadas durante la carga. Las gráficas de detalle se dibujan al abrir la pestaña y se actualizan con `Plotly.react`. APOD carga la imagen de tamaño normal, evitando descargar automáticamente la versión HD.

La caché reside en memoria **por proceso**: se pierde al reiniciar y no se comparte entre varios servidores. Para despliegues con múltiples procesos conviene una caché externa. Un resultado completo sin caché necesita nueve solicitudes (siete DONKI, una EONET y una NeoWs); APOD se consulta por separado. El servidor incluido es para desarrollo local.

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
app/__init__.py        Factory y archivos estáticos
app/api.py             Validación y agregación REST
app/nasa_client.py     HTTP, concurrencia, caché y errores
app/stats.py           Estadísticas con pandas
static/index.html      Interfaz
static/js/app.js       Consultas y gráficas
static/css/style.css   Estilos
tests/test_nasa.py     Pruebas sin red
```
