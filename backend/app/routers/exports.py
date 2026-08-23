"""Export packages (PRD 49). Everything downloadable from the iPhone."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..db.repositories import EXPORTS, Repository
from ..services.exports import build_package
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}/exports", tags=["exports"])


@router.post("/songs/{song_id}")
def export_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    return build_package(studio, universe_id, song_id)


@router.get("")
def list_exports(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, EXPORTS).list(limit=100)


@router.get("/{export_id}")
def get_export(
    owner: OwnerDep, studio: StudioDep, universe_id: str, export_id: str
) -> dict[str, Any]:
    studio.orchestrator.require_universe(universe_id)
    record = Repository(studio.db, universe_id, EXPORTS).require(export_id)
    return {
        **record,
        "archive_url": studio.storage.signed_url(record["archive_path"])
        if record.get("archive_path")
        else None,
    }
