"""Generation Queue (PRD 37)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..domain.enums import JobState
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
def run_job(studio: StudioDep, body: RunIn) -> dict[str, Any]:
    """Cloud Tasks pushes here. Protected by the same IAM boundary as the rest
    of the service, plus the OIDC token Cloud Tasks attaches."""
    return studio.orchestrator.run_job(body.universe_id, body.job_id)
