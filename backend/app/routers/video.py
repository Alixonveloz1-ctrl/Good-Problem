"""Video pre-production, images, clips and assembly (PRD 21-31).

The order is fixed and every step is gated:

    song approved -> video concept -> story approved -> casting -> locations ->
    wardrobe -> storyboard approved -> scene images approved and locked ->
    Veo clips approved -> assembly -> 16:9 and 9:16.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.repositories import (
    IMAGES,
    LOCATIONS,
    SCENES,
    SONGS,
    VIDEO_PROJECTS,
    VIDEOS,
    Repository,
)
from ..domain.enums import CanonStatus, CreativeRole, StageKey, StageStatus, UserAction, VideoType
from ..errors import Conflict, NotFound
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services import approvals as rules
from ..services.approvals import ApprovalService, build_stage
from ..services.context import load_scene_context
from ..services.production_plan import PlanInputs, render_text
from ..services.production_plan import build as build_plan
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}", tags=["video"])


def _projects(studio, universe_id: str) -> Repository:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, VIDEO_PROJECTS)


def _scenes(studio, universe_id: str) -> Repository:
    return Repository(studio.db, universe_id, SCENES)


class ProjectIn(BaseModel):
    song_id: str
    title: str = ""
    video_type: VideoType = VideoType.NARRATIVE


class DirectorIn(BaseModel):
    brief: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    idempotency_key: str | None = None


class SceneImageIn(BaseModel):
    prompt: str | None = None
    model: str | None = None
    variant: str | None = None
    aspect_ratio: str = "16:9"
    negative_prompt: str = ""
    idempotency_key: str | None = None


class SceneClipIn(BaseModel):
    prompt: str | None = None
    model: str | None = None
    variant: str | None = None
    aspect_ratio: str = "16:9"
    duration_seconds: int | None = None
    negative_prompt: str = ""
    idempotency_key: str | None = None


class PlanIn(BaseModel):
    image_model: str
    image_variant: str = "1K"
    video_model: str
    video_variant: str = "1080p"
    attempts_per_image: float = 1.0
    attempts_per_clip: float = 1.0
    vertical_derivatives: int = 4


class AssembleIn(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["16:9", "9:16"])
    captions: bool = False
    idempotency_key: str | None = None


# --- Projects --------------------------------------------------------------


@router.post("/video-projects")
def create_project(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: ProjectIn
) -> dict[str, Any]:
    """Requires an approved song: a rejected song does not trigger a video."""
    song = rules.assert_song_approved(studio.db, universe_id, body.song_id)
    project_id = new_id("vp")
    project = _projects(studio, universe_id).create(
        project_id,
        {
            "song_id": body.song_id,
            "title": body.title or song.get("title", ""),
            "video_type": body.video_type.value,
            "story": {"status": CanonStatus.DRAFT.value},
            "storyboard_status": CanonStatus.DRAFT.value,
            "status": CanonStatus.DRAFT.value,
            "stages": _initial_stages(),
        },
    )
    Repository(studio.db, universe_id, SONGS).update(
        body.song_id, {"video_project_id": project_id}
    )
    return project


def _initial_stages() -> list[dict[str, Any]]:
    approved = {StageKey.CONCEPT, StageKey.MUSIC}
    stages = []
    for key in StageKey:
        status = StageStatus.APPROVED if key in approved else StageStatus.PENDING
        stages.append(build_stage(key, status))
    return stages


@router.get("/video-projects")
def list_projects(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    return _projects(studio, universe_id).list(limit=100)


@router.get("/video-projects/{project_id}")
def get_project(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str
) -> dict[str, Any]:
    project = _projects(studio, universe_id).require(project_id)
    scenes = _scenes(studio, universe_id).list(
        where={"project_id": project_id}, order_by="index", descending=False
    )
    return {
        **project,
        "scenes": scenes,
        "stage_summary": _stage_summary(studio, universe_id, project, scenes),
        "master_16x9_url": studio.storage.signed_url(project["master_16x9_path"])
        if project.get("master_16x9_path")
        else None,
        "master_9x16_url": studio.storage.signed_url(project["master_9x16_path"])
        if project.get("master_9x16_path")
        else None,
    }


def _stage_summary(studio, universe_id: str, project: dict, scenes: list[dict]) -> list[dict]:
    """What the production rail shows: status, model in use and accumulated cost
    per stage (PRD 38)."""
    song = Repository(studio.db, universe_id, SONGS).get(project["song_id"]) or {}
    generated = [s for s in scenes if not s.get("reuses_scene_id")]
    images_done = sum(
        1 for s in generated if s.get("image_status") == CanonStatus.APPROVED.value
    )
    clips_done = sum(1 for s in generated if s.get("clip_status") == CanonStatus.APPROVED.value)
    def status_of(done: bool, started: bool) -> str:
        if done:
            return StageStatus.APPROVED.value
        return StageStatus.IN_PROGRESS.value if started else StageStatus.PENDING.value

    return [
        {"key": StageKey.CONCEPT.value, "label": "Concepto",
         "status": status_of(bool(project.get("concept")), True), "detail": ""},
        {"key": StageKey.MUSIC.value, "label": "Musica",
         "status": status_of(song.get("status") == CanonStatus.APPROVED.value, True),
         "detail": song.get("title", "")},
        {"key": StageKey.STORY.value, "label": "Historia",
         "status": status_of(
             (project.get("story") or {}).get("status") == CanonStatus.APPROVED.value,
             bool((project.get("story") or {}).get("premise"))),
         "detail": ""},
        {"key": StageKey.CHARACTERS.value, "label": "Personajes",
         "status": status_of(bool(project.get("character_ids")), True), "detail": ""},
        {"key": StageKey.STORYBOARD.value, "label": "Storyboard",
         "status": status_of(
             project.get("storyboard_status") == CanonStatus.APPROVED.value, bool(scenes)),
         "detail": f"{len(scenes)} escenas, {len(scenes) - len(generated)} reutilizadas"},
        {"key": StageKey.IMAGES.value, "label": "Imagenes",
         "status": status_of(bool(generated) and images_done == len(generated), images_done > 0),
         "detail": f"{images_done}/{len(generated)}"},
        {"key": StageKey.VIDEO.value, "label": "Video",
         "status": status_of(bool(generated) and clips_done == len(generated), clips_done > 0),
         "detail": f"{clips_done}/{len(generated)}"},
        {"key": StageKey.ASSEMBLY.value, "label": "Ensamblaje",
         "status": status_of(bool(project.get("master_16x9_path")), False), "detail": ""},
        {"key": StageKey.EXPORT.value, "label": "Export",
         "status": status_of(False, False), "detail": ""},
    ]


@router.post("/video-projects/{project_id}/concept")
def propose_video_concept(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: DirectorIn
) -> dict[str, Any]:
    project = _projects(studio, universe_id).require(project_id)
    song = rules.assert_song_approved(studio.db, universe_id, project["song_id"])
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="video_project",
            target_id=project_id,
            model=body.model,
            role=CreativeRole.DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "video_concept",
                "brief": body.brief,
                "overrides": body.overrides,
                "song": {
                    "title": song.get("title"),
                    "genre": song.get("genre"),
                    "mood": song.get("mood"),
                    "lyrics": song.get("lyrics", "")[:4000],
                    "structure": song.get("structure", []),
                },
            },
        )
    )


@router.post("/video-projects/{project_id}/story/approve")
def approve_story(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str
) -> dict[str, Any]:
    repo = _projects(studio, universe_id)
    project = repo.require(project_id)
    story = {**(project.get("story") or {}), "status": CanonStatus.APPROVED.value}
    if not story.get("premise"):
        raise Conflict("No hay historia que aprobar todavia.")
    return repo.update(project_id, {"story": story})


class CastIn(BaseModel):
    character_ids: list[str] = Field(default_factory=list)
    location_ids: list[str] = Field(default_factory=list)
    wardrobe_ids: list[str] = Field(default_factory=list)


@router.put("/video-projects/{project_id}/cast")
def set_cast(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: CastIn
) -> dict[str, Any]:
    """Characters exist before the scenes do (PRD 17)."""
    repo = _projects(studio, universe_id)
    repo.require(project_id)
    return repo.update(project_id, body.model_dump())


@router.post("/video-projects/{project_id}/storyboard")
def propose_storyboard(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: DirectorIn
) -> dict[str, Any]:
    project = _projects(studio, universe_id).require(project_id)
    song = Repository(studio.db, universe_id, SONGS).require(project["song_id"])
    if (project.get("story") or {}).get("status") != CanonStatus.APPROVED.value:
        raise Conflict("Aprueba la historia antes de pedir el storyboard.")
    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=project.get("character_ids") or [],
        location_id=None,
        wardrobe_ids=project.get("wardrobe_ids") or [],
        max_references=0,
    )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="video_project",
            target_id=project_id,
            model=body.model,
            role=CreativeRole.CINEMATOGRAPHER,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "storyboard",
                "brief": body.brief,
                "overrides": body.overrides,
                "song_duration_seconds": song.get("requested_duration_seconds", 150),
                "story": project.get("story") or {},
                "lyrics": song.get("lyrics", "")[:4000],
                "characters": [
                    {"name": c.get("name"), "appearance": c.get("appearance")}
                    for c in context.characters
                ],
                "locations": [
                    {"name": loc.get("name"), "description": loc.get("description")}
                    for loc in Repository(studio.db, universe_id, LOCATIONS).list(limit=50)
                ],
                "wardrobe": [
                    {"name": o.get("name"), "description": o.get("description")}
                    for o in context.outfits
                ],
            },
        )
    )


@router.post("/video-projects/{project_id}/storyboard/approve")
def approve_storyboard(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str
) -> dict[str, Any]:
    """Mass image generation does not start before this (PRD 23)."""
    repo = _projects(studio, universe_id)
    repo.require(project_id)
    scenes = _scenes(studio, universe_id).list(where={"project_id": project_id})
    if not scenes:
        raise Conflict("No hay storyboard que aprobar.")
    for scene in scenes:
        _scenes(studio, universe_id).update(scene["id"], {"status": CanonStatus.APPROVED.value})
    updated = repo.update(project_id, {"storyboard_status": CanonStatus.APPROVED.value})
    ApprovalService(studio.db).record_user_action(
        universe_id, VIDEO_PROJECTS, project_id, UserAction.APPROVE
    )
    return updated


# --- Production plan -------------------------------------------------------


@router.post("/video-projects/{project_id}/plan")
def production_plan(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: PlanIn
) -> dict[str, Any]:
    plan = build_plan(
        studio,
        universe_id,
        project_id,
        PlanInputs(
            image_model=body.image_model,
            image_variant=body.image_variant,
            video_model=body.video_model,
            video_variant=body.video_variant,
            attempts_per_image=body.attempts_per_image,
            attempts_per_clip=body.attempts_per_clip,
            vertical_derivatives=body.vertical_derivatives,
        ),
    )
    _projects(studio, universe_id).update(project_id, {"production_plan": plan})
    return {**plan, "text": render_text(plan)}


# --- Scenes ----------------------------------------------------------------


@router.get("/scenes/{scene_id}")
def get_scene(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    scene = _scenes(studio, universe_id).require(scene_id)
    image = (
        Repository(studio.db, universe_id, IMAGES).get(scene["image_id"])
        if scene.get("image_id")
        else None
    )
    clip = (
        Repository(studio.db, universe_id, VIDEOS).get(scene["clip_id"])
        if scene.get("clip_id")
        else None
    )
    return {
        **scene,
        "image": {**image, "url": studio.storage.signed_url(image["storage_path"])}
        if image
        else None,
        "clip": {**clip, "url": studio.storage.signed_url(clip["storage_path"])} if clip else None,
    }


@router.patch("/scenes/{scene_id}")
def patch_scene(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    repo = _scenes(studio, universe_id)
    repo.require(scene_id)
    allowed = {
        k: v
        for k, v in body.items()
        if k in {
            "action", "emotion", "camera", "lighting", "environment", "dialogue",
            "visual_objective", "image_prompt", "video_prompt", "character_ids",
            "location_id", "wardrobe_ids", "song_timestamp",
        }
    }
    return repo.update(scene_id, allowed)


class ReuseIn(BaseModel):
    reuses_scene_id: str | None = None
    force_generate: bool = False
    note: str = ""


@router.post("/scenes/{scene_id}/reuse")
def set_reuse(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str, body: ReuseIn
) -> dict[str, Any]:
    """The user can force generating a take the Director wanted to reuse, and
    the other way round (PRD 23)."""
    repo = _scenes(studio, universe_id)
    repo.require(scene_id)
    if body.reuses_scene_id:
        repo.require(body.reuses_scene_id)
    return repo.update(
        scene_id,
        {
            "reuses_scene_id": body.reuses_scene_id,
            "reuse_forced_by_user": body.force_generate,
            "reuse_note": body.note,
        },
    )


@router.post("/scenes/{scene_id}/image")
def generate_scene_image(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str, body: SceneImageIn
) -> dict[str, Any]:
    """Images are mandatory before Veo (PRD 24), and the model is chosen here,
    per generation."""
    scene = _scenes(studio, universe_id).require(scene_id)
    rules.assert_storyboard_approved(studio.db, universe_id, scene["project_id"])
    rules.assert_scene_not_reused(scene)

    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=scene.get("character_ids") or [],
        location_id=scene.get("location_id"),
        wardrobe_ids=scene.get("wardrobe_ids") or [],
    )
    prompt = body.prompt or scene.get("image_prompt") or ""
    if not prompt:
        raise Conflict("La escena no tiene prompt de imagen.")
    full_prompt = "\n\n".join(part for part in [prompt, context.describe()] if part)

    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="scene",
            target_id=scene_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "purpose": "scene",
                "prompt": full_prompt,
                "aspect_ratio": body.aspect_ratio,
                "negative_prompt": body.negative_prompt,
                "reference_paths": context.reference_paths,
            },
        )
    )


@router.post("/scenes/{scene_id}/image/approve")
def approve_scene_image(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    """Approve locks the image. A locked image is what Veo receives (PRD 24)."""
    scenes = _scenes(studio, universe_id)
    scene = scenes.require(scene_id)
    image_id = scene.get("image_id")
    if not image_id:
        raise Conflict("La escena no tiene imagen que aprobar.")
    service = ApprovalService(studio.db)
    service.approve(universe_id, IMAGES, image_id, locked=True)
    service.record_user_action(universe_id, IMAGES, image_id, UserAction.APPROVE)
    return scenes.update(scene_id, {"image_status": CanonStatus.APPROVED.value})


@router.post("/scenes/{scene_id}/image/reject")
def reject_scene_image(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    scenes = _scenes(studio, universe_id)
    scene = scenes.require(scene_id)
    if scene.get("image_id"):
        ApprovalService(studio.db).reject(universe_id, IMAGES, scene["image_id"], locked=False)
    return scenes.update(scene_id, {"image_status": CanonStatus.REJECTED.value})


@router.post("/scenes/{scene_id}/clip")
def generate_scene_clip(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str, body: SceneClipIn
) -> dict[str, Any]:
    """Veo. The model is chosen here, per generation, and audio is never
    generated: the option does not exist on any screen (PRD 26)."""
    scene = _scenes(studio, universe_id).require(scene_id)
    rules.assert_scene_not_reused(scene)
    rules.assert_scene_image_locked(studio.db, universe_id, scene_id)
    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=scene.get("character_ids") or [],
        location_id=scene.get("location_id"),
        wardrobe_ids=scene.get("wardrobe_ids") or [],
        max_references=3,
    )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="video",
            target_type="scene",
            target_id=scene_id,
            model=body.model,
            variant=body.variant,
            idempotency_key=body.idempotency_key,
            payload={
                "prompt": body.prompt,
                "aspect_ratio": body.aspect_ratio,
                "duration_seconds": body.duration_seconds,
                "negative_prompt": body.negative_prompt,
                "reference_paths": context.reference_paths,
            },
        )
    )


@router.post("/scenes/{scene_id}/clip/approve")
def approve_scene_clip(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    scenes = _scenes(studio, universe_id)
    scene = scenes.require(scene_id)
    clip_id = scene.get("clip_id")
    if not clip_id:
        raise Conflict("La escena no tiene clip que aprobar.")
    service = ApprovalService(studio.db)
    service.approve(universe_id, VIDEOS, clip_id, locked=True)
    service.record_user_action(universe_id, VIDEOS, clip_id, UserAction.APPROVE)
    return scenes.update(scene_id, {"clip_status": CanonStatus.APPROVED.value})


@router.post("/scenes/{scene_id}/clip/reject")
def reject_scene_clip(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    scenes = _scenes(studio, universe_id)
    scene = scenes.require(scene_id)
    if scene.get("clip_id"):
        ApprovalService(studio.db).reject(universe_id, VIDEOS, scene["clip_id"], locked=False)
    return scenes.update(scene_id, {"clip_status": CanonStatus.REJECTED.value})


# --- Assembly --------------------------------------------------------------


@router.post("/video-projects/{project_id}/assemble")
def assemble(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: AssembleIn
) -> dict[str, Any]:
    rules.assert_ready_for_assembly(studio.db, universe_id, project_id)
    return studio.orchestrator.submit_local(
        GenerationRequest(
            universe_id=universe_id,
            kind="assembly",
            target_type="video_project",
            target_id=project_id,
            idempotency_key=body.idempotency_key,
            payload={"formats": body.formats, "captions": body.captions},
        )
    )


@router.post("/video-projects/{project_id}/approve")
def approve_project(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str
) -> dict[str, Any]:
    project = _projects(studio, universe_id).require(project_id)
    if not project.get("master_16x9_path") and not project.get("edl_path"):
        raise NotFound("El proyecto todavia no tiene ensamblaje.")
    service = ApprovalService(studio.db)
    updated = service.approve(universe_id, VIDEO_PROJECTS, project_id)
    service.save_to_canon(
        universe_id,
        entity_type="video_project",
        entity_id=project_id,
        label=project.get("title", ""),
        storage_path=project.get("master_16x9_path"),
    )
    return updated
