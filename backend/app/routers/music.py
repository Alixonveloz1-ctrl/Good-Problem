"""Music Studio (PRD 12, 13, 14, 15).

The rail is: idea or lyrics -> Director -> music concept -> approval -> lyrics
-> approval -> Lyria 3 Pro -> song version -> approval -> song master.

Every arrow that says "approval" is an endpoint the user has to call. Nothing
walks forward on its own, and a rejected song never triggers a music video.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.repositories import SONGS, Repository
from ..domain.enums import CanonStatus, CreativeRole, LyricsAuthor, UserAction
from ..errors import Conflict, NotFound
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services import approvals as approval_rules
from ..services.approvals import ApprovalService
from ..services.context import load_bible
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}/songs", tags=["music"])


def _repo(studio, universe_id: str) -> Repository:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, SONGS)


class SongIn(BaseModel):
    title: str = ""
    requested_duration_seconds: int = 150


class DirectorIn(BaseModel):
    brief: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)
    """What the user changed by hand: genre, BPM, mood... The Director rebuilds
    its proposal from these instead of arguing them back (PRD 11)."""
    model: str | None = None
    idempotency_key: str | None = None


class LyricsIn(BaseModel):
    lyrics: str
    author: LyricsAuthor = LyricsAuthor.USER


class GenerateIn(BaseModel):
    duration_seconds: int | None = None
    prompt: str | None = None
    negative_prompt: str = ""
    seed: int | None = None
    idempotency_key: str | None = None


@router.post("")
def create_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: SongIn
) -> dict[str, Any]:
    bible = load_bible(studio.db, universe_id)
    return _repo(studio, universe_id).create(
        new_id("song"),
        {
            "title": body.title,
            "requested_duration_seconds": min(max(body.requested_duration_seconds, 15), 180),
            "voice_profile": bible.voice_profile.model_dump(),
            "genre": bible.musical.genre,
            "status": CanonStatus.DRAFT.value,
            "lyrics_status": CanonStatus.DRAFT.value,
            "versions": [],
        },
    )


@router.get("")
def list_songs(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    return _repo(studio, universe_id).list(limit=200)


@router.get("/{song_id}")
def get_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    versions = []
    for version in song.get("versions") or []:
        versions.append(
            {**version, "url": studio.storage.signed_url(version["audio_path"])
             if version.get("audio_path") else None}
        )
    return {**song, "versions": versions}


@router.patch("/{song_id}")
def patch_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    repo = _repo(studio, universe_id)
    repo.require(song_id)
    allowed = {
        k: v
        for k, v in body.items()
        if k in {"title", "genre", "bpm", "mood", "structure", "music_prompt",
                 "requested_duration_seconds", "concept", "metadata"}
    }
    updated = repo.update(song_id, allowed)
    ApprovalService(studio.db).record_user_action(universe_id, SONGS, song_id, UserAction.EDIT)
    return updated


# --- Director on the song --------------------------------------------------


@router.delete("/{song_id}")
def delete_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, str]:
    """Borra una cancion.

    Los archivos generados se quedan: pueden estar dentro de un videoclip ya
    montado, y borrarlos dejaria ese video sin audio sin que nadie se entere.
    """
    repo = Repository(studio.db, universe_id, SONGS)
    repo.require(song_id)
    repo.delete(song_id)
    return {"deleted": song_id}


@router.post("/{song_id}/concept")
def propose_concept(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: DirectorIn
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="song",
            target_id=song_id,
            model=body.model,
            role=CreativeRole.MUSIC_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "music_concept",
                "brief": body.brief,
                "overrides": body.overrides,
                "duration_seconds": song.get("requested_duration_seconds", 150),
            },
        )
    )


@router.post("/{song_id}/concept/approve")
def approve_concept(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    repo = _repo(studio, universe_id)
    song = repo.require(song_id)
    concept = {**(song.get("concept") or {}), "status": CanonStatus.APPROVED.value}
    return repo.update(song_id, {"concept": concept})


@router.post("/{song_id}/lyrics/generate")
def generate_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: DirectorIn
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    if (song.get("concept") or {}).get("status") != CanonStatus.APPROVED.value:
        raise Conflict("Aprueba el concepto musical antes de pedir la letra.")
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="song",
            target_id=song_id,
            model=body.model,
            role=CreativeRole.MUSIC_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "lyrics",
                "concept": song.get("concept") or {},
                "overrides": body.overrides,
            },
        )
    )


@router.put("/{song_id}/lyrics")
def put_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: LyricsIn
) -> dict[str, Any]:
    """The user pastes or edits the lyrics. They are never modified
    automatically without approval (PRD 12)."""
    repo = _repo(studio, universe_id)
    repo.require(song_id)
    updated = repo.update(
        song_id,
        {
            "lyrics": body.lyrics,
            "lyrics_author": body.author.value,
            "lyrics_status": CanonStatus.DRAFT.value,
        },
    )
    ApprovalService(studio.db).record_user_action(
        universe_id, SONGS, song_id, UserAction.EDIT, written=body.lyrics[:2000]
    )
    return updated


@router.post("/{song_id}/lyrics/analyze")
def analyze_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: DirectorIn
) -> dict[str, Any]:
    """User supplied lyrics: the Director analyses them and proposes genre, BPM,
    interpretation and production, without rewriting a line (PRD 12)."""
    song = _repo(studio, universe_id).require(song_id)
    if not song.get("lyrics"):
        raise Conflict("Sube o pega una letra antes de pedir el analisis.")
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="song",
            target_id=song_id,
            model=body.model,
            role=CreativeRole.MUSIC_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "lyrics_analysis",
                "lyrics": song["lyrics"],
                "overrides": body.overrides,
                "brief": body.brief,
            },
        )
    )


@router.post("/{song_id}/lyrics/approve")
def approve_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    repo = _repo(studio, universe_id)
    song = repo.require(song_id)
    if not song.get("lyrics"):
        raise Conflict("No hay letra que aprobar.")
    updated = repo.update(song_id, {"lyrics_status": CanonStatus.APPROVED.value})
    ApprovalService(studio.db).record_user_action(universe_id, SONGS, song_id, UserAction.APPROVE)
    return updated


# --- Lyria -----------------------------------------------------------------


@router.post("/{song_id}/generate")
def generate_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: GenerateIn
) -> dict[str, Any]:
    """Always Lyria 3 Pro. There is no model selector here because there is
    nothing to select: the other two Lyria models make 30 second clips."""
    song = _repo(studio, universe_id).require(song_id)
    approval_rules.assert_lyrics_approved(studio.db, universe_id, song_id)
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="music",
            target_type="song",
            target_id=song_id,
            model=None,  # resolved to lyria-3-pro-preview by the orchestrator
            idempotency_key=body.idempotency_key,
            payload={
                "duration_seconds": body.duration_seconds
                or song.get("requested_duration_seconds", 150),
                "prompt": body.prompt,
                "negative_prompt": body.negative_prompt,
                "seed": body.seed,
            },
        )
    )


@router.post("/{song_id}/versions/{version}/approve")
def approve_version(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, version: int
) -> dict[str, Any]:
    """The approved version becomes the Song Master, and that is the audio the
    music video will always use (PRD 30)."""
    repo = _repo(studio, universe_id)
    song = repo.require(song_id)
    versions = list(song.get("versions") or [])
    match = next((v for v in versions if int(v.get("version", 0)) == version), None)
    if match is None:
        raise NotFound(f"La cancion no tiene version {version}.")
    for entry in versions:
        entry["status"] = (
            CanonStatus.APPROVED.value
            if int(entry.get("version", 0)) == version
            else CanonStatus.ARCHIVED.value
        )
    service = ApprovalService(studio.db)
    updated = service.approve(
        universe_id,
        SONGS,
        song_id,
        versions=versions,
        approved_version=version,
        approved_master_path=match.get("audio_path"),
    )
    service.record_user_action(universe_id, SONGS, song_id, UserAction.APPROVE)
    service.save_to_canon(
        universe_id,
        entity_type="song",
        entity_id=song_id,
        label=song.get("title", ""),
        storage_path=match.get("audio_path"),
    )
    return updated


@router.post("/{song_id}/reject")
def reject_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    """A rejected song does not trigger the music video (PRD 14)."""
    _repo(studio, universe_id).require(song_id)
    service = ApprovalService(studio.db)
    updated = service.reject(universe_id, SONGS, song_id, approved_master_path=None,
                             approved_version=None)
    service.record_user_action(universe_id, SONGS, song_id, UserAction.REJECT)
    return updated


@router.post("/{song_id}/cover")
def generate_cover(
    owner: OwnerDep,
    studio: StudioDep,
    universe_id: str,
    song_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    prompt = body.get("prompt") or (
        f"Album cover for '{song.get('title','')}'. "
        f"{(song.get('concept') or {}).get('visual_concept','')}"
    )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="song",
            target_id=song_id,
            model=body.get("model"),
            variant=body.get("variant"),
            idempotency_key=body.get("idempotency_key"),
            payload={
                "purpose": "cover",
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "reference_paths": body.get("reference_paths") or [],
            },
        )
    )
