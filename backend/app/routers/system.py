"""Health, identity, model registry and the Home screen."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, RedirectResponse

from ..db.repositories import UNIVERSES
from ..domain.enums import JobState
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
        "universes": universes,
        "active_jobs": sorted(active_jobs, key=lambda j: j.get("created_at", ""), reverse=True),
        "pending_approvals": sorted(
            pending, key=lambda j: j.get("finished_at") or "", reverse=True
        ),
    }


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


@router.get("/diagnostics/models")
def check_models(owner: OwnerDep, studio: StudioDep) -> dict[str, Any]:
    """Pregunta a Vertex cuales de los modelos del registro existen de verdad.

    Existe por un error concreto: los IDs salieron del PRD, que traia nombres
    comerciales ("Veo 3.1") y no los identificadores que Vertex quiere
    ("veo-3.1-generate-001"). Con un ID que no existe, cada generacion muere en
    un 404 y en la pantalla solo se ve un trabajo fallido sin explicacion.

    Preguntarselo al catalogo de Google desde este mismo proyecto es la unica
    fuente fiable, y no cuesta nada: pedir la ficha de un modelo no genera nada.
    """
    filas = [
        {
            "id": spec.id,
            "label": spec.label,
            "kind": spec.kind.value,
            "exists": studio.vertex.model_exists(spec.id),
        }
        for spec in studio.registry.all()
    ]
    return {
        "checked": not studio.settings.dry_run,
        "models": filas,
        "missing": [fila["id"] for fila in filas if fila["exists"] is False],
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

