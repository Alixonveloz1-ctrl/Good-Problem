"""Generation Queue (PRD 37)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..auth import COLA, leer_encargo
from ..domain.enums import JobState
from ..errors import Forbidden
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}/jobs", tags=["jobs"])
internal_router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.get("")
def list_jobs(
    owner: OwnerDep, studio: StudioDep, universe_id: str, state: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    studio.orchestrator.require_universe(universe_id)
    return studio.jobs.list(universe_id, state=state, limit=limit)


@router.get("/{job_id}")
def get_job(
    owner: OwnerDep, studio: StudioDep, universe_id: str, job_id: str
) -> dict[str, Any]:
    job = studio.jobs.get(universe_id, job_id)
    result = job.get("result") or {}
    if result.get("storage_path"):
        result = {**result, "url": studio.storage.signed_url(result["storage_path"])}
    return {**job, "result": result or None}


@router.post("/{job_id}/retry")
def retry_job(
    owner: OwnerDep, studio: StudioDep, universe_id: str, job_id: str
) -> dict[str, Any]:
    """Retries with the same model that was requested. The system never
    substitutes a different or weaker one."""
    return studio.jobs.retry(universe_id, job_id)


@router.post("/{job_id}/cancel")
def cancel_job(
    owner: OwnerDep, studio: StudioDep, universe_id: str, job_id: str
) -> dict[str, Any]:
    return studio.jobs.cancel(universe_id, job_id)


@router.post("/{job_id}/approve")
def approve_job(
    owner: OwnerDep, studio: StudioDep, universe_id: str, job_id: str
) -> dict[str, Any]:
    return studio.jobs.mark_state(universe_id, job_id, JobState.APPROVED)


@router.post("/{job_id}/reject")
def reject_job(
    owner: OwnerDep, studio: StudioDep, universe_id: str, job_id: str
) -> dict[str, Any]:
    return studio.jobs.mark_state(universe_id, job_id, JobState.REJECTED)


class RunIn(BaseModel):
    universe_id: str
    job_id: str


@internal_router.post("/jobs/run")
def run_job(request: Request, studio: StudioDep, body: RunIn) -> dict[str, Any]:
    """Aqui empuja Cloud Tasks cuando le toca a un trabajo.

    Que el pase este bien firmado ya lo comprobo la puerta. Lo que se comprueba
    aqui es lo otro: que el pase sea de ESTE trabajo y no de otro. Sin esto, un
    encargo legitimo valdria de llave para lanzar cualquier generacion.
    """
    encargo = leer_encargo(request.headers.get(COLA, ""), studio.settings.session_secret)
    if encargo is not None and encargo != (body.universe_id, body.job_id):
        raise Forbidden("Ese pase no es de este trabajo.")
    return studio.orchestrator.run_job(body.universe_id, body.job_id)
