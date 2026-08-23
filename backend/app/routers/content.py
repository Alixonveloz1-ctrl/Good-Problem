"""Content Studio, BTS and interviews (PRD 33, 34, 35).

Everything here is derived from approved material and must respect the Canon.
The picture is generated without audio; the voice is the cloned Chirp voice laid
over it in the edit.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.repositories import CONTENT, Repository
from ..domain.enums import AspectRatio, BtsKind, CanonStatus, ContentKind, CreativeRole
from ..errors import Conflict
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services.approvals import ApprovalService
from ..services.context import load_bible
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}/content", tags=["content"])


def _repo(studio, universe_id: str) -> Repository:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, CONTENT)


class ContentIn(BaseModel):
    kind: ContentKind
    bts_kind: BtsKind | None = None
    title: str = ""
    song_id: str | None = None
    project_id: str | None = None
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL


class ScriptIn(BaseModel):
    brief: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    idempotency_key: str | None = None


class VoiceIn(BaseModel):
    text: str | None = None
    language_code: str = "es-ES"
    idempotency_key: str | None = None


@router.post("")
def create_content(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: ContentIn
) -> dict[str, Any]:
    return _repo(studio, universe_id).create(
        new_id("cnt"), {**body.model_dump(), "status": CanonStatus.DRAFT.value}
    )


@router.get("")
def list_content(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    rows = _repo(studio, universe_id).list(limit=200)
    return [
        {
            **row,
            "url": studio.storage.signed_url(row["storage_path"])
            if row.get("storage_path")
            else None,
            "voice_url": studio.storage.signed_url(row["spoken_audio_path"])
            if row.get("spoken_audio_path")
            else None,
        }
        for row in rows
    ]


@router.get("/{content_id}")
def get_content(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str
) -> dict[str, Any]:
    row = _repo(studio, universe_id).require(content_id)
    return {
        **row,
        "url": studio.storage.signed_url(row["storage_path"]) if row.get("storage_path") else None,
        "voice_url": studio.storage.signed_url(row["spoken_audio_path"])
        if row.get("spoken_audio_path")
        else None,
    }


@router.post("/{content_id}/script")
def write_script(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str, body: ScriptIn
) -> dict[str, Any]:
    row = _repo(studio, universe_id).require(content_id)
    task = "interview" if row.get("kind") == ContentKind.INTERVIEW.value else "content_script"
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="content",
            target_id=content_id,
            model=body.model,
            role=CreativeRole.DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": task,
                "brief": body.brief,
                "overrides": body.overrides,
                "content_kind": row.get("kind"),
                "bts_kind": row.get("bts_kind"),
            },
        )
    )


@router.post("/{content_id}/voice")
def synthesize_voice(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str, body: VoiceIn
) -> dict[str, Any]:
    """Chirp 3. The sung voice is not solved in the MVP; the spoken one is."""
    row = _repo(studio, universe_id).require(content_id)
    text = body.text or row.get("spoken_text") or row.get("script") or ""
    if not text.strip():
        raise Conflict("No hay texto que sintetizar. Pide el guion primero.")
    bible = load_bible(studio.db, universe_id)
    if not bible.voice_profile.speaking_voice_secret and not studio.settings.dry_run:
        raise Conflict(
            "Este artista no tiene voz hablada clonada. Registra la clave de Chirp 3 en "
            "Secret Manager y guardala en el Voice Profile."
        )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="speech",
            target_type="content",
            target_id=content_id,
            model="chirp-3-instant-custom-voice",
            idempotency_key=body.idempotency_key,
            payload={"text": text, "language_code": body.language_code},
        )
    )


@router.post("/{content_id}/approve")
def approve_content(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str
) -> dict[str, Any]:
    row = _repo(studio, universe_id).require(content_id)
    service = ApprovalService(studio.db)
    updated = service.approve(universe_id, CONTENT, content_id)
    service.save_to_canon(
        universe_id,
        entity_type="content",
        entity_id=content_id,
        label=row.get("title", ""),
        storage_path=row.get("storage_path"),
    )
    return updated


class VoiceCloneIn(BaseModel):
    sample_base64: str
    consent_base64: str
    language_code: str = "es-ES"
    secret_name: str = "chirp-voice-cloning-key"


@router.post("/voice-clone")
def create_voice_clone(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: VoiceCloneIn
) -> dict[str, Any]:
    """Ten seconds of sample plus a consent recording produce a reusable key.
    The key is stored in Secret Manager and referenced from the Voice Profile;
    it is the only secret this project keeps (PRD 40)."""
    import base64

    studio.orchestrator.require_universe(universe_id)
    key = studio.chirp.create_voice_clone_key(
        sample_wav=base64.b64decode(body.sample_base64),
        consent_wav=base64.b64decode(body.consent_base64),
        language_code=body.language_code,
    )
    secret_name = f"{body.secret_name}-{universe_id}"
    studio.secrets.write(secret_name, key)
    from ..services.context import save_bible

    bible = load_bible(studio.db, universe_id)
    bible.voice_profile.speaking_voice_secret = secret_name
    save_bible(studio.db, universe_id, bible)
    return {"secret_name": secret_name, "stored": True}
