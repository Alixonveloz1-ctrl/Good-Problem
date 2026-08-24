"""Character Department, Wardrobe and Locations (PRD 17-20)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.repositories import CHARACTERS, LOCATIONS, WARDROBE, Repository
from ..domain.enums import CanonStatus, CharacterRole, CreativeRole, UserAction, WardrobeCategory
from ..domain.schemas import MASTER_SHOTS
from ..errors import Conflict
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services.approvals import ApprovalService
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}", tags=["characters"])


def _repo(studio, universe_id: str, collection: str) -> Repository:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, collection)


# --- Characters ------------------------------------------------------------


class CharacterIn(BaseModel):
    name: str
    role: CharacterRole = CharacterRole.SUPPORTING
    apparent_age: str = ""
    appearance: str = ""
    personality: str = ""


class CharacterPatch(BaseModel):
    name: str | None = None
    apparent_age: str | None = None
    appearance: str | None = None
    personality: str | None = None
    wardrobe_ids: list[str] | None = None


class DesignIn(BaseModel):
    brief: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    idempotency_key: str | None = None


class ImageIn(BaseModel):
    prompt: str = ""
    model: str | None = None
    variant: str | None = None
    aspect_ratio: str = "1:1"
    negative_prompt: str = ""
    reference_paths: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


@router.post("/characters")
def create_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: CharacterIn
) -> dict[str, Any]:
    repo = _repo(studio, universe_id, CHARACTERS)
    return repo.create(
        new_id("char"),
        {
            **body.model_dump(),
            "master_shots": [
                {"key": key, "label": label, "storage_path": None,
                 "status": CanonStatus.DRAFT.value, "prompt": ""}
                for key, label in MASTER_SHOTS
            ],
            "reference_image_paths": [],
            "status": CanonStatus.DRAFT.value,
        },
    )


@router.get("/characters")
def list_characters(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    return _repo(studio, universe_id, CHARACTERS).list(limit=100)


@router.get("/characters/{character_id}")
def get_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str
) -> dict[str, Any]:
    return _repo(studio, universe_id, CHARACTERS).require(character_id)


@router.patch("/characters/{character_id}")
def patch_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str, body: CharacterPatch
) -> dict[str, Any]:
    repo = _repo(studio, universe_id, CHARACTERS)
    updated = repo.update(character_id, body.model_dump(exclude_none=True))
    ApprovalService(studio.db).record_user_action(
        universe_id, CHARACTERS, character_id, UserAction.EDIT
    )
    return updated


@router.post("/characters/{character_id}/design")
def design_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str, body: DesignIn
) -> dict[str, Any]:
    """The Casting Director writes the character and the Master shot prompts."""
    _repo(studio, universe_id, CHARACTERS).require(character_id)
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="character",
            target_id=character_id,
            model=body.model,
            role=CreativeRole.CASTING_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={"task": "character", "brief": body.brief, "overrides": body.overrides},
        )
    )


@router.post("/characters/{character_id}/master/{shot_key}")
def generate_master_shot(
    owner: OwnerDep,
    studio: StudioDep,
    universe_id: str,
    character_id: str,
    shot_key: str,
    body: ImageIn,
) -> dict[str, Any]:
    """Character Master shots. Worth generating with the best model available:
    everything downstream leans on them (PRD 18)."""
    character = _repo(studio, universe_id, CHARACTERS).require(character_id)
    prompt = body.prompt or _shot_prompt(character, shot_key)
    if not prompt:
        raise Conflict(
            "No hay prompt para esta toma. Pide el diseno al Director o escribe uno."
        )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="character",
            target_id=character_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "purpose": "character_master",
                "shot_key": shot_key,
                "prompt": prompt,
                "aspect_ratio": body.aspect_ratio,
                "negative_prompt": body.negative_prompt,
                "reference_paths": body.reference_paths,
            },
        )
    )


def _shot_prompt(character: dict[str, Any], shot_key: str) -> str:
    for shot in character.get("master_shots") or []:
        if shot.get("key") == shot_key and shot.get("prompt"):
            base = shot["prompt"]
            break
    else:
        base = ""
    if not base and character.get("appearance"):
        base = f"{shot_key.replace('_', ' ')} of {character['name']}: {character['appearance']}"
    return base


@router.post("/characters/{character_id}/approve")
def approve_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str
) -> dict[str, Any]:
    """Approving the Master is what turns those images into the references
    attached to every later generation with this character (PRD 18)."""
    repo = _repo(studio, universe_id, CHARACTERS)
    character = repo.require(character_id)
    shots = [s for s in (character.get("master_shots") or []) if s.get("storage_path")]
    if not shots:
        raise Conflict(
            "No se puede aprobar un Character Master sin imagenes. Genera al menos el retrato."
        )
    for shot in character["master_shots"]:
        if shot.get("storage_path"):
            shot["status"] = CanonStatus.APPROVED.value
    approvals = ApprovalService(studio.db)
    updated = approvals.approve(
        universe_id,
        CHARACTERS,
        character_id,
        master_shots=character["master_shots"],
        reference_image_paths=[s["storage_path"] for s in shots],
    )
    approvals.record_user_action(universe_id, CHARACTERS, character_id, UserAction.APPROVE)
    approvals.save_to_canon(
        universe_id,
        entity_type="character",
        entity_id=character_id,
        label=character.get("name", ""),
        storage_path=shots[0]["storage_path"],
    )
    return updated


@router.delete("/characters/{character_id}")
def delete_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str
) -> dict[str, str]:
    """Borra un personaje.

    Lo generado se queda en el almacenamiento: borrar los archivos exigiria
    saber quien mas los usa —una toma reutilizada en otra escena, una imagen que
    ya salio en un video montado— y equivocarse ahi deja huecos negros en
    videos ya terminados. Un archivo huerfano cuesta centimos; un video roto
    cuesta volver a generarlo entero.
    """
    _repo(studio, universe_id, CHARACTERS).require(character_id)
    _repo(studio, universe_id, CHARACTERS).delete(character_id)
    return {"deleted": character_id}


@router.post("/characters/{character_id}/reject")
def reject_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str
) -> dict[str, Any]:
    _repo(studio, universe_id, CHARACTERS).require(character_id)
    return ApprovalService(studio.db).reject(universe_id, CHARACTERS, character_id)


# --- Wardrobe --------------------------------------------------------------


class OutfitIn(BaseModel):
    name: str
    category: WardrobeCategory = WardrobeCategory.SIGNATURE
    description: str = ""
    pieces: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    usage: str = ""
    restrictions: list[str] = Field(default_factory=list)


@router.post("/wardrobe")
def create_outfit(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: OutfitIn
) -> dict[str, Any]:
    return _repo(studio, universe_id, WARDROBE).create(
        new_id("fit"), {**body.model_dump(), "status": CanonStatus.DRAFT.value}
    )


@router.get("/wardrobe")
def list_wardrobe(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    return _repo(studio, universe_id, WARDROBE).list(limit=200)


@router.patch("/wardrobe/{outfit_id}")
def patch_outfit(
    owner: OwnerDep, studio: StudioDep, universe_id: str, outfit_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    return _repo(studio, universe_id, WARDROBE).update(outfit_id, body)


@router.post("/wardrobe/{outfit_id}/image")
def generate_outfit_image(
    owner: OwnerDep, studio: StudioDep, universe_id: str, outfit_id: str, body: ImageIn
) -> dict[str, Any]:
    outfit = _repo(studio, universe_id, WARDROBE).require(outfit_id)
    prompt = body.prompt or f"{outfit['name']}: {outfit.get('description','')}"
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="wardrobe",
            target_id=outfit_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "purpose": "wardrobe",
                "prompt": prompt,
                "aspect_ratio": body.aspect_ratio,
                "reference_paths": body.reference_paths,
                "negative_prompt": body.negative_prompt,
            },
        )
    )


@router.post("/wardrobe/{outfit_id}/approve")
def approve_outfit(
    owner: OwnerDep, studio: StudioDep, universe_id: str, outfit_id: str
) -> dict[str, Any]:
    outfit = _repo(studio, universe_id, WARDROBE).require(outfit_id)
    service = ApprovalService(studio.db)
    updated = service.approve(universe_id, WARDROBE, outfit_id)
    service.save_to_canon(
        universe_id,
        entity_type="wardrobe",
        entity_id=outfit_id,
        label=outfit.get("name", ""),
        storage_path=outfit.get("image_path"),
    )
    return updated


# --- Locations -------------------------------------------------------------


class LocationIn(BaseModel):
    name: str
    description: str = ""
    lighting: str = ""
    time_of_day: str = ""
    architecture: str = ""
    mood: str = ""


@router.delete("/wardrobe/{outfit_id}")
def delete_outfit(
    owner: OwnerDep, studio: StudioDep, universe_id: str, outfit_id: str
) -> dict[str, str]:
    _repo(studio, universe_id, WARDROBE).require(outfit_id)
    _repo(studio, universe_id, WARDROBE).delete(outfit_id)
    return {"deleted": outfit_id}


@router.post("/locations")
def create_location(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: LocationIn
) -> dict[str, Any]:
    return _repo(studio, universe_id, LOCATIONS).create(
        new_id("loc"),
        {**body.model_dump(), "reference_paths": [], "status": CanonStatus.DRAFT.value},
    )


@router.get("/locations")
def list_locations(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    return _repo(studio, universe_id, LOCATIONS).list(limit=200)


@router.patch("/locations/{location_id}")
def patch_location(
    owner: OwnerDep, studio: StudioDep, universe_id: str, location_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    return _repo(studio, universe_id, LOCATIONS).update(location_id, body)


@router.post("/locations/{location_id}/image")
def generate_location_image(
    owner: OwnerDep, studio: StudioDep, universe_id: str, location_id: str, body: ImageIn
) -> dict[str, Any]:
    location = _repo(studio, universe_id, LOCATIONS).require(location_id)
    prompt = body.prompt or (
        f"{location['name']}: {location.get('description','')}. "
        f"Lighting: {location.get('lighting','')}. {location.get('time_of_day','')}"
    )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="location",
            target_id=location_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "purpose": "location",
                "prompt": prompt,
                "aspect_ratio": body.aspect_ratio or "16:9",
                "reference_paths": body.reference_paths,
                "negative_prompt": body.negative_prompt,
            },
        )
    )


@router.post("/locations/{location_id}/approve")
def approve_location(
    owner: OwnerDep, studio: StudioDep, universe_id: str, location_id: str
) -> dict[str, Any]:
    location = _repo(studio, universe_id, LOCATIONS).require(location_id)
    service = ApprovalService(studio.db)
    updated = service.approve(universe_id, LOCATIONS, location_id)
    service.save_to_canon(
        universe_id,
        entity_type="location",
        entity_id=location_id,
        label=location.get("name", ""),
        storage_path=(location.get("reference_paths") or [None])[0],
    )
    return updated


@router.delete("/locations/{location_id}")
def delete_location(
    owner: OwnerDep, studio: StudioDep, universe_id: str, location_id: str
) -> dict[str, str]:
    _repo(studio, universe_id, LOCATIONS).require(location_id)
    _repo(studio, universe_id, LOCATIONS).delete(location_id)
    return {"deleted": location_id}
