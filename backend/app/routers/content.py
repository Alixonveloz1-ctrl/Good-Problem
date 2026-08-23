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
from ..services.context import load_bible, load_scene_context
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


# Las rutas de /voice-clone van antes que /{content_id}: FastAPI resuelve en
# orden, y si no, tomaria 'voice-clone' por el id de una pieza de contenido.
class VoiceCloneIn(BaseModel):
    sample_base64: str
    consent_base64: str
    language_code: str = "es-ES"
    secret_name: str = "chirp-voice-cloning-key"


@router.get("/voice-clone")
def voice_clone_status(owner: OwnerDep, studio: StudioDep, universe_id: str) -> dict[str, Any]:
    """Que hace falta para clonar la voz hablada, y si ya esta hecha.

    El texto de consentimiento lo fija Google: hay que leerlo palabra por
    palabra y en ingles, o Chirp rechaza la grabacion.
    """
    from ..providers.chirp import CONSENT_SCRIPT

    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    return {
        "ready": bool(bible.voice_profile.speaking_voice_secret),
        "secret_name": bible.voice_profile.speaking_voice_secret,
        "consent_script": CONSENT_SCRIPT,
        "sample_seconds": 10,
        "sample_rate_hertz": 24000,
    }


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


class StillIn(BaseModel):
    prompt: str | None = None
    model: str | None = None
    variant: str | None = None
    idempotency_key: str | None = None


class ClipIn(BaseModel):
    prompt: str | None = None
    model: str | None = None
    variant: str | None = None
    duration_seconds: int | None = None
    idempotency_key: str | None = None


class CutIn(BaseModel):
    project_id: str | None = None
    start: float = 0.0
    duration: float = 15.0
    idempotency_key: str | None = None


@router.post("/{content_id}/still")
def generate_still(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str, body: StillIn
) -> dict[str, Any]:
    """The image the clip will be generated from. Same rule as a scene: nothing
    reaches Veo without an image first (PRD 24)."""
    row = _repo(studio, universe_id).require(content_id)
    prompt = body.prompt or row.get("video_prompt") or row.get("script", "")[:500]
    if not prompt.strip():
        raise Conflict("No hay prompt. Pide el guion al Director o escribe uno.")
    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=[c["id"] for c in _lead_characters(studio, universe_id)],
        location_id=None,
        wardrobe_ids=[],
    )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="content",
            target_id=content_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "purpose": "content",
                "prompt": prompt,
                "aspect_ratio": row.get("aspect_ratio", "9:16"),
                "reference_paths": context.reference_paths,
            },
        )
    )


@router.post("/{content_id}/clip")
def generate_clip(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str, body: ClipIn
) -> dict[str, Any]:
    """Veo, without audio as always. The voice goes on afterwards."""
    row = _repo(studio, universe_id).require(content_id)
    if not row.get("source_image_path"):
        raise Conflict("Genera primero la imagen de esta pieza.")
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="video",
            target_type="content",
            target_id=content_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "prompt": body.prompt,
                "aspect_ratio": row.get("aspect_ratio", "9:16"),
                "duration_seconds": body.duration_seconds,
            },
        )
    )


@router.post("/{content_id}/cut")
def cut_from_master(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str, body: CutIn
) -> dict[str, Any]:
    """Shorts, Reels and TikToks come out of the approved master by reframing,
    so they cost nothing to generate (PRD 32, 33)."""
    _repo(studio, universe_id).require(content_id)
    return studio.orchestrator.submit_local(
        GenerationRequest(
            universe_id=universe_id,
            kind="cut",
            target_type="content",
            target_id=content_id,
            idempotency_key=body.idempotency_key,
            payload={
                "project_id": body.project_id,
                "start": body.start,
                "duration": body.duration,
            },
        )
    )


@router.post("/{content_id}/mix")
def mix_voice(
    owner: OwnerDep, studio: StudioDep, universe_id: str, content_id: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lay the Chirp voice over the silent footage (PRD 29, 34, 35)."""
    row = _repo(studio, universe_id).require(content_id)
    if not row.get("storage_path"):
        raise Conflict("Esta pieza todavia no tiene video.")
    if not row.get("spoken_audio_path"):
        raise Conflict("Genera la voz de Chirp antes de mezclar.")
    return studio.orchestrator.submit_local(
        GenerationRequest(
            universe_id=universe_id,
            kind="mix",
            target_type="content",
            target_id=content_id,
            idempotency_key=(body or {}).get("idempotency_key"),
        )
    )


def _lead_characters(studio, universe_id: str) -> list[dict[str, Any]]:
    """The artist travels with every piece of content about the artist."""
    from ..db.repositories import CHARACTERS

    rows = Repository(studio.db, universe_id, CHARACTERS).list(limit=50)
    approved = [r for r in rows if r.get("status") == CanonStatus.APPROVED.value]
    leads = [r for r in approved if r.get("role") == "lead"]
    return leads or approved[:1]


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
