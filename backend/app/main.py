"""RackMon API application factory and process lifecycle."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_VERSION, get_settings, production_safety_check
from .database import init_db
from .routers import admin, alerts, annotations, auth, devices, discovery, metrics, public, reports, rules, stream, support, system, templates
from .services.poller import run_poller
from .services.scheduler import run_scheduler
from .services.seed import seed_all

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("rackmon")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast (in production) or warn (in dev) if insecure default secrets are
    # still in use — before anything else touches the database or network.
    production_safety_check(settings)
    insecure = settings.insecure_defaults_in_use()
    if insecure:
        log.warning(
            "INSECURE DEFAULTS in use (%s) — acceptable for local dev, but MUST be "
            "overridden before deploying to production.",
            ", ".join(insecure),
        )
    init_db()
    seed_all()
    from .plugins import load_plugins
    load_plugins(settings.plugins_modules)
    if settings.redis_url:
        from .services.realtime import hub
        try:
            await hub.connect_redis(settings.redis_url)
            log.info("realtime: connected to Redis for cross-replica fan-out")
        except Exception as exc:  # pragma: no cover - degrade to in-process
            log.warning("realtime: Redis unavailable (%s); using in-process fan-out", exc)
    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.poller_enabled:
        tasks.append(asyncio.create_task(run_poller(stop)))
        tasks.append(asyncio.create_task(run_scheduler(stop)))
    else:
        # El poller corre en otro proceso (es lo que hace el chart de Helm por
        # defecto). La caché de valores vive en memoria y solo la escribe el
        # poller, así que sin esto este proceso no tendría ni un dato que enseñar
        # por mucho que la base de datos esté llena.
        from .services.poller import hidratar_desde_bd, refrescar_cache
        try:
            await asyncio.to_thread(hidratar_desde_bd)
        except Exception as exc:  # pragma: no cover
            log.warning("no he podido rellenar la caché al arrancar (%s)", exc)
        tasks.append(asyncio.create_task(refrescar_cache(stop)))
    if settings.snmp_trap_enabled:
        from .services.traps import run_trap_listener
        tasks.append(asyncio.create_task(run_trap_listener(stop)))
    app.state.background_stop = stop
    app.state.background_tasks = tasks
    log.info("RackMon %s started (env=%s)", APP_VERSION, settings.environment)
    try:
        yield
    finally:
        stop.set()
        if settings.redis_url:
            from .services.realtime import hub
            await hub.disconnect_redis()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        log.info("RackMon stopped")


# En producción la documentación interactiva se apaga. Estaba abierta y sin
# autenticar en cada instalación: cualquiera que llegase a la URL se descargaba
# el mapa completo de la API (todas las rutas, parámetros y esquemas) sin tener
# cuenta. En desarrollo y en los tests sigue disponible, que es donde hace falta.
_en_produccion = settings.environment == "production"

# La referencia de la API se abre solo si alguien lo pide. Antes bastaba con no
# tocar `environment` —que vale "development" por defecto— para dejar /docs,
# /redoc y /openapi.json abiertos a cualquiera. La 1.2.0 los cerró "en
# producción", pero eso deja la seguridad colgando de que el operador se acuerde
# de una variable. Ahora hay que encenderlos a propósito.
_docs = settings.api_docs_enabled

app = FastAPI(
    title="RackMon API",
    version=APP_VERSION,
    description="Thermal monitoring platform for server racks (SNMP).",
    # Authorship and licence travel with the API description itself, so every
    # installation serves them at /docs and /openapi.json without anyone having
    # to go looking for a repository.
    contact={
        "name": "Enrique González Romero",
        "url": "https://www.linkedin.com/in/enrique-gonz%C3%A1lez-romero-1b6a90275",
    },
    license_info={
        "name": "MIT",
        "url": "https://github.com/rackmonsoftware-star/rackmon/blob/main/LICENSE",
    },
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Un panel de monitorización no necesita ninguna de estas capacidades. Negarlas
    # explícitamente corta el daño si algún día entra un script donde no debe.
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "accelerometer=(), gyroscope=(), magnetometer=(), interest-cohort=()",
    )
    # HSTS: only when the request arrived over TLS, so local HTTP dev isn't pinned.
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self' data:; "
        "base-uri 'self'; frame-ancestors 'none'",
    )
    if settings.environment == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    return response


# --- API routers ----------------------------------------------------------- #
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(discovery.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(annotations.router)
app.include_router(rules.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(templates.router)
app.include_router(system.router)
app.include_router(stream.router)
app.include_router(public.router)
app.include_router(support.router)


# --- Static SPA (built frontend) ------------------------------------------- #
_ASSETS_DIR = STATIC_DIR / "assets"
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    if _ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

    # index.html references content-hashed asset filenames, so it must never be
    # cached by the browser — otherwise a client keeps loading the previous
    # build's (now-deleted) assets after a deploy. The hashed assets under
    # /assets are immutable and may be cached freely.
    _INDEX_HEADERS = {"Cache-Control": "no-cache"}

    # GET y HEAD, para que un comprobador de enlaces o un monitor no reciba un
    # 405 donde hay una página perfectamente servida.
    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa_root():
        return FileResponse(STATIC_DIR / "index.html", headers=_INDEX_HEADERS)

    # La raíz real de lo que se puede servir, resuelta UNA vez al arrancar.
    _RAIZ_SERVIBLE = STATIC_DIR.resolve()

    def _fichero_servible(full_path: str):
        """El fichero que corresponde a esta ruta, SOLO si está dentro de static.

        Antes esto era `candidate = STATIC_DIR / full_path` y un `is_file()`, y
        eso es una lectura de ficheros arbitraria sin autenticar. Juntar rutas con
        "/" no normaliza los "..": el sistema operativo sí los resuelve al mirar
        si el fichero existe, así que una petición a `/%2e%2e/%2e%2e/.env` —que
        Starlette descodifica a "../../.env" antes de llegar aquí— salía del
        directorio y devolvía el fichero con un 200. Comprobado contra la
        aplicación real: dos de tres codificaciones lo servían.
        
        Lo que había al alcance de cualquiera que supiera la dirección: el .env
        con RACKMON_JWT_SECRET y RACKMON_MASTER_KEY —es decir, firmar un token de
        administrador y descifrar todas las credenciales SNMP guardadas—, la base
        de datos entera, y cualquier cosa legible por el proceso.

        `resolve()` normaliza los ".." Y sigue los enlaces simbólicos, así que
        tampoco vale colar un enlace dentro de static que apunte fuera.
        """
        try:
            candidato = (STATIC_DIR / full_path).resolve()
        except (OSError, ValueError, RuntimeError):
            return None
        try:
            candidato.relative_to(_RAIZ_SERVIBLE)
        except ValueError:
            return None  # se ha salido del directorio: no existe para nosotros
        return candidato if candidato.is_file() else None

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa_catch_all(full_path: str):
        # Serve real files if present, otherwise hand routing to the SPA.
        candidate = _fichero_servible(full_path)
        if candidate is not None:
            return FileResponse(candidate)
        if full_path.startswith("api/") or full_path in {"health", "metrics"}:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(STATIC_DIR / "index.html", headers=_INDEX_HEADERS)
else:  # pragma: no cover - only when frontend is not built

    @app.get("/", include_in_schema=False)
    async def root_placeholder():
        return JSONResponse(
            {
                "name": "RackMon API",
                "version": APP_VERSION,
                "docs": "/docs",
                "note": "Frontend not built. Run 'npm run build' in ./frontend.",
            }
        )
