"""AI Artist Universe Studio.

One Cloud Run service: the API, the job worker and the PWA that the phone
loads. Access is IAM plus IAP against a single Google account, so there is no
login screen and no OAuth consent screen to click through from a phone
(PRD 41).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .container import get_studio
from .errors import DomainError
from .routers import characters, content, exports, jobs, music, system, universes, video
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
    studio.ensure_registry_seeded()
    logger.info(
        "studio_ready dry_run=%s project=%s storage=%s",
        studio.settings.dry_run,
        studio.settings.project_id or "(local)",
        "gcs" if studio.settings.use_gcs else "local",
    )


@app.exception_handler(DomainError)
def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


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

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        """Serve the built PWA, letting the client router handle the path."""
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
