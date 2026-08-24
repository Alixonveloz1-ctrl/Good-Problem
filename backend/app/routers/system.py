"""Health, identity, model registry and the Home screen."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, RedirectResponse

from ..container import Studio
from ..db.repositories import CHARACTERS, SONGS, UNIVERSES, VIDEO_PROJECTS, Repository
from ..domain.enums import CanonStatus, JobState, StageStatus
from ..errors import NotFound
from ..providers.storage import LocalStorage
from ..providers.vertex import redact
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(studio: StudioDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "dry_run": studio.settings.dry_run,
        "project": studio.settings.project_id or None,
        "location": studio.settings.location,
        "firestore": studio.settings.use_firestore,
        "storage": "gcs" if studio.settings.use_gcs else "local",
    }


@router.get("/me")
def me(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    return {
        "email": owner.email,
        "verified": owner.verified,
        "single_user": bool(studio.settings.owner_email),
        "dry_run": studio.settings.dry_run,
    }


# --- Model registry (PRD 41) ----------------------------------------------


@router.get("/registry/models")
def list_models(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    return studio.registry.selector_payload()


@router.put("/registry/models")
def replace_models(
    owner: OwnerDep, studio: StudioDep, document: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Editing this document is how a model is added, repriced or turned off.
    No code changes, no redeploy."""
    registry = studio.replace_registry_document(document)
    return registry.selector_payload()


@router.post("/registry/reload")
def reload_models(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    return studio.reload_registry().selector_payload()


# --- Home (PRD 38) ---------------------------------------------------------


@router.get("/home")
def home(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    universes = studio.db.list(UNIVERSES, order_by="updated_at", limit=50)
    active_jobs: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for universe in universes:
        uid = universe["id"]
        for job in studio.jobs.active(uid, limit=10):
            active_jobs.append({**job, "universe_name": universe.get("name", uid)})
        for job in studio.jobs.list(uid, state=JobState.READY.value, limit=10):
            pending.append(
                {
                    "job_id": job["id"],
                    "universe_id": uid,
                    "universe_name": universe.get("name", uid),
                    "kind": job["kind"],
                    "target_type": job.get("target_type", ""),
                    "target_id": job.get("target_id", ""),
                    "model": job.get("model", ""),
                    "finished_at": job.get("finished_at"),
                }
            )
    return {
        "universes": [_tarjeta(studio, universe) for universe in universes],
        "active_jobs": sorted(active_jobs, key=lambda j: j.get("created_at", ""), reverse=True),
        "pending_approvals": sorted(
            pending, key=lambda j: j.get("finished_at") or "", reverse=True
        ),
        "recent_projects": _ultimos_proyectos(studio, universes),
    }


def _tarjeta(studio: Studio, universe: dict[str, Any]) -> dict[str, Any]:
    """Lo que la pantalla de inicio ensena de cada artista.

    La cara y el estado se calculan aqui y no en el navegador: pedirlos artista
    por artista serian tantas peticiones como artistas, y desde un movil eso se
    nota.
    """
    uid = universe["id"]
    personajes = Repository(studio.db, uid, CHARACTERS).list(limit=50)
    protagonista = next((p for p in personajes if p.get("role") == "lead"), None)
    if protagonista is None and personajes:
        protagonista = personajes[0]

    portada = ""
    for toma in (protagonista or {}).get("master_shots", []):
        if toma.get("storage_path"):
            portada = toma["storage_path"]
            break

    proyectos = Repository(studio.db, uid, VIDEO_PROJECTS).list(limit=100)
    en_marcha = sum(1 for p in proyectos if p.get("status") != CanonStatus.APPROVED.value)

    return {
        **universe,
        "cover_path": portada,
        "artist_name": (protagonista or {}).get("name", ""),
        "projects_active": en_marcha,
        "projects_total": len(proyectos),
    }


def _ultimos_proyectos(studio: Studio, universes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los videoclips mas recientes de todos los artistas, juntos.

    Sin esto hay que entrar artista por artista para acordarse de que habia a
    medias, que es justo lo que una pantalla de inicio tiene que ahorrar.
    """
    filas: list[dict[str, Any]] = []
    for universe in universes:
        uid = universe["id"]
        # La portada de un videoclip es la de su cancion. Se piden todas de una
        # vez: preguntarlo proyecto por proyecto seria una lectura por fila.
        portadas = {
            cancion["id"]: cancion.get("cover_path") or ""
            for cancion in Repository(studio.db, uid, SONGS).list(limit=100)
        }
        for proyecto in Repository(studio.db, uid, VIDEO_PROJECTS).list(limit=20):
            filas.append(
                {
                    "id": proyecto["id"],
                    "universe_id": uid,
                    "universe_name": universe.get("name", uid),
                    "title": proyecto.get("title") or "Sin titulo",
                    "status": proyecto.get("status", ""),
                    "stage": _etapa_actual(proyecto),
                    "cover_path": portadas.get(proyecto.get("song_id", ""), ""),
                    "updated_at": proyecto.get("updated_at", ""),
                }
            )
    return sorted(filas, key=lambda f: f.get("updated_at") or "", reverse=True)[:8]


def _etapa_actual(proyecto: dict[str, Any]) -> str:
    """Por donde va el videoclip: la primera etapa que aun no esta aprobada.

    "BORRADOR" no dice nada; "Storyboard" dice que toca hacer hoy.
    """
    for etapa in proyecto.get("stages", []):
        if etapa.get("status") != StageStatus.APPROVED.value:
            return str(etapa.get("label") or etapa.get("key") or "")
    return "Terminado"


# --- Diagnostics -----------------------------------------------------------


@router.get("/diagnostics/vertex-calls")
def vertex_calls(
    owner: OwnerDep,
    studio: StudioDep,
    prefix: str = Query("", description="Filtra por prefijo de modelo, por ejemplo 'veo'"),
    limit: int = Query(50, le=500),
) -> dict[str, Any]:
    """Acceptance test 27: comprobar que ninguna llamada a Veo pidio audio.

    Every request this process sent is here, with the payload as it went out.
    """
    calls = studio.calls.for_model_prefix(prefix) if prefix else studio.calls.all()
    rows = [
        {**call.to_dict(), "payload": redact(call.payload)} for call in calls[-limit:]
    ]
    audio_requests = [
        row
        for row in rows
        if (row["payload"].get("parameters") or {}).get("generateAudio") is True
    ]
    return {
        "count": len(rows),
        "calls": rows,
        "calls_requesting_audio": len(audio_requests),
    }


# --- Media (local development only) ---------------------------------------

media_router = APIRouter(tags=["media"])


@media_router.get("/media/{path:path}")
def media(path: str, studio: StudioDep):
    """Serves generated assets when no bucket is configured. With a bucket, the
    API hands out signed URLs instead and this route is never used."""
    storage = studio.storage
    if not isinstance(storage, LocalStorage):
        return RedirectResponse(storage.signed_url(path))
    full = storage.root / path
    if not full.exists():
        raise NotFound(f"No existe {path}")
    return FileResponse(full)

