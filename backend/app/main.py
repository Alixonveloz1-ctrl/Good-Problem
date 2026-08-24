"""AI Artist Universe Studio.

One Cloud Run service: the API, the job worker and the PWA that the phone
loads. Entra una sola persona, con su cuenta de Google: el servicio es público
en Cloud Run —tiene que serlo para poder pintar la pantalla de entrada— y la
puerta la pone el middleware de aquí abajo, no la red (PRD 41).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import gate
from .container import get_studio
from .errors import DomainError, NotFound
from .routers import (
    auth,
    characters,
    content,
    exports,
    jobs,
    music,
    system,
    universes,
    video,
)
from .settings import get_settings

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("aaus")

app = FastAPI(
    title="AI Artist Universe Studio",
    version="2.1.0",
    description=(
        "Estudio creativo virtual controlado desde un iPhone. La IA propone y produce, "
        "el usuario decide."
    ),
)


@app.on_event("startup")
def startup() -> None:
    studio = get_studio()
    app.state.studio = studio

    # Un despliegue mal configurado tiene que romperse aquí, en el despliegue, y
    # no media hora después cuando alguien pase por delante de una puerta que no
    # cierra.
    problemas = studio.settings.check()
    if problemas:
        raise RuntimeError("Configuración incompleta: " + " | ".join(problemas))

    studio.ensure_registry_seeded()
    logger.info(
        "studio_ready dry_run=%s project=%s storage=%s puerta=%s",
        studio.settings.dry_run,
        studio.settings.project_id or "(local)",
        "gcs" if studio.settings.use_gcs else "local",
        studio.settings.owner_email or "abierta",
    )


@app.middleware("http")
async def puerta(request: Request, call_next):
    """Identidad antes que nada, para todo lo que sirva datos."""
    settings = getattr(app.state, "studio", None)
    settings = settings.settings if settings else get_settings()
    error = gate(request, settings)
    if error is not None:
        return JSONResponse(status_code=error.status_code, content=error.to_payload())
    return await call_next(request)


@app.exception_handler(DomainError)
def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.exception_handler(Exception)
def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Cualquier fallo no previsto, contado en JSON y no en texto plano.

    Sin esto, un fallo del servidor sale como "Internal Server Error" a secas, y
    la aplicación —que espera JSON— muestra "JSON Parse error: Unexpected
    identifier". Es decir: el único mensaje que llega al teléfono habla del
    formato de la respuesta y no del problema, y no hay forma de saber qué pasó
    sin ir a leer los registros de Cloud Run desde un móvil.

    El texto del error va dentro. Aquí no es una fuga: entra una sola persona,
    la dueña, y es justo quien necesita leerlo.
    """
    logger.exception("fallo_no_previsto %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": f"{type(exc).__name__}: {exc}"[:800],
                "details": {"ruta": request.url.path},
            }
        },
    )


app.include_router(auth.router)
app.include_router(system.router)
app.include_router(system.media_router)
app.include_router(universes.router)
app.include_router(characters.router)
app.include_router(music.router)
app.include_router(video.router)
app.include_router(content.router)
app.include_router(exports.router)
app.include_router(jobs.router)
app.include_router(jobs.internal_router)


# --- The PWA ---------------------------------------------------------------

_settings = get_settings()
_static = Path(_settings.static_dir)

if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def spa(request: Request, full_path: str) -> Any:
        """Serve the built PWA, letting the client router handle the path.

        An unknown /api path must not fall through to index.html: a client
        calling a route that no longer exists would get HTML and a 200, and the
        mistake would surface as a JSON parse error somewhere far away. It gets
        a 404 whatever the method, rather than the 405 that a GET-only catch all
        would produce for a POST.
        """
        if full_path.startswith("api/"):
            raise NotFound(f"No existe la ruta /{full_path}")
        if request.method != "GET":
            raise NotFound(f"No existe la ruta /{full_path}")
        candidate = _static / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")

else:  # pragma: no cover - only when the frontend has not been built

    @app.get("/", include_in_schema=False)
    def no_frontend() -> dict[str, str]:
        return {
            "status": "backend ok",
            "frontend": "sin construir: ejecuta 'npm ci && npm run build' en frontend/",
        }
