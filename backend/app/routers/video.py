"""Video pre-production, images, clips and assembly (PRD 21-31).

The order is fixed, and each step only needs the previous one to EXIST —
there are no approvals anywhere:

    song with generated audio -> video concept (with its wardrobe and
    locations written inside it) -> story -> storyboard -> scene images ->
    Veo clips -> assembly -> 16:9 and 9:16.

Whatever was generated last is what is in use. A project is complete when
its rendered MP4 exists: that is a fact about the file, not a user gesture.
The old approve endpoints stay as harmless no-ops for compatibility.

The only character is the artist: the project takes them automatically when
it is created. There is no casting step.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.repositories import (
    CHARACTERS,
    IMAGES,
    SCENES,
    SONGS,
    VIDEO_PROJECTS,
    VIDEOS,
    Repository,
)
from ..domain.enums import CanonStatus, CreativeRole, StageKey, StageStatus, UserAction, VideoType
from ..errors import Conflict
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
    """Requires a song with generated audio: the video is cut over it."""
    song = rules.assert_song_ready(studio.db, universe_id, body.song_id)
    # El unico personaje posible es el artista: entra solo, sin paso de
    # reparto. Sin el, el storyboard no tendria a quien retratar.
    artista = next(
        (
            c
            for c in Repository(studio.db, universe_id, CHARACTERS).list(limit=50)
            if c.get("role") == "lead"
        ),
        None,
    )
    project_id = new_id("vp")
    project = _projects(studio, universe_id).create(
        project_id,
        {
            "song_id": body.song_id,
            "title": body.title or song.get("title", ""),
            "video_type": body.video_type.value,
            "character_ids": [artista["id"]] if artista else [],
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
    per stage (PRD 38). A stage is done when its material EXISTS — nothing
    here waits for an approval that no longer exists."""
    song = Repository(studio.db, universe_id, SONGS).get(project["song_id"]) or {}
    generated = [s for s in scenes if not s.get("reuses_scene_id")]
    images_done = sum(1 for s in generated if s.get("image_id"))
    clips_done = sum(1 for s in generated if s.get("clip_id"))
    def status_of(done: bool, started: bool) -> str:
        if done:
            return StageStatus.APPROVED.value
        return StageStatus.IN_PROGRESS.value if started else StageStatus.PENDING.value

    return [
        {"key": StageKey.CONCEPT.value, "label": "Concepto",
         "status": status_of(bool(project.get("concept")), True), "detail": ""},
        {"key": StageKey.MUSIC.value, "label": "Musica",
         "status": status_of(bool(rules.current_audio_path(song)), True),
         "detail": song.get("title", "")},
        {"key": StageKey.STORY.value, "label": "Historia",
         "status": status_of(
             bool((project.get("story") or {}).get("premise")),
             bool((project.get("story") or {}).get("premise") or project.get("concept"))),
         "detail": ""},
        {"key": StageKey.CHARACTERS.value, "label": "Artista",
         "status": status_of(bool(project.get("character_ids")), True), "detail": ""},
        {"key": StageKey.STORYBOARD.value, "label": "Storyboard",
         "status": status_of(bool(scenes), bool(scenes)),
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


@router.delete("/video-projects/{project_id}")
def delete_project(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str
) -> dict[str, str]:
    """Borra un videoclip y sus escenas.

    Las escenas se borran con él porque no existen fuera de su proyecto: dejar
    una escena sin videoclip es dejar basura que nadie puede ver ni alcanzar.

    Los archivos generados se quedan en el almacenamiento. Saber cuáles se
    pueden borrar exigiría saber quién más los usa, y equivocarse deja huecos
    negros en videos ya terminados.
    """
    proyecto = Repository(studio.db, universe_id, VIDEO_PROJECTS)
    proyecto.require(project_id)

    escenas = Repository(studio.db, universe_id, SCENES)
    borradas = 0
    for escena in escenas.list(limit=500):
        if escena.get("project_id") == project_id:
            escenas.delete(escena["id"])
            borradas += 1

    proyecto.delete(project_id)
    return {"deleted": project_id, "scenes": str(borradas)}


@router.post("/video-projects/{project_id}/concept")
def propose_video_concept(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: DirectorIn
) -> dict[str, Any]:
    project = _projects(studio, universe_id).require(project_id)
    song = rules.assert_song_ready(studio.db, universe_id, project["song_id"])
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
    """Compatibilidad: la historia generada ya esta en uso. No-op."""
    return _projects(studio, universe_id).require(project_id)


@router.post("/video-projects/{project_id}/storyboard")
def propose_storyboard(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: DirectorIn
) -> dict[str, Any]:
    project = _projects(studio, universe_id).require(project_id)
    song = Repository(studio.db, universe_id, SONGS).require(project["song_id"])
    if not (project.get("story") or {}).get("premise") and not project.get("concept"):
        raise Conflict(
            "Pide primero la propuesta del Director: el storyboard se "
            "escribe a partir de su historia."
        )
    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=project.get("character_ids") or [],
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
                "wardrobe_notes": project.get("wardrobe_notes") or "",
                "location_notes": project.get("location_notes") or "",
            },
        )
    )


@router.post("/video-projects/{project_id}/storyboard/approve")
def approve_storyboard(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str
) -> dict[str, Any]:
    """Compatibilidad: el storyboard generado ya esta en uso y las imagenes
    se pueden generar en cuanto las escenas existen. No-op."""
    return _projects(studio, universe_id).require(project_id)


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
            "location_description", "wardrobe_description", "planos", "song_timestamp",
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
    # La escena existe porque hay storyboard: eso es todo lo que hace
    # falta. No hay storyboard que aprobar antes de generar sus imagenes.
    rules.assert_scene_not_reused(scene)

    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=scene.get("character_ids") or [],
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
    """Compatibilidad: la imagen generada ya es la que Veo recibe (PRD 24).

    Nace en uso al generarse; no hay que aprobarla ni bloquearla. No-op.
    """
    return _scenes(studio, universe_id).require(scene_id)


@router.post("/scenes/{scene_id}/image/reject")
def reject_scene_image(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    """Compatibilidad: si la imagen no gusta, se regenera y sustituye. No-op."""
    return _scenes(studio, universe_id).require(scene_id)


@router.post("/scenes/{scene_id}/clip")
def generate_scene_clip(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str, body: SceneClipIn
) -> dict[str, Any]:
    """Veo. The model is chosen here, per generation, and audio is never
    generated: the option does not exist on any screen (PRD 26)."""
    scene = _scenes(studio, universe_id).require(scene_id)
    rules.assert_scene_not_reused(scene)
    rules.assert_scene_image_ready(studio.db, universe_id, scene_id)
    context = load_scene_context(
        studio.db,
        universe_id,
        character_ids=scene.get("character_ids") or [],
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
    """Compatibilidad: el clip generado ya es el que monta el ensamblaje. No-op."""
    return _scenes(studio, universe_id).require(scene_id)


@router.post("/scenes/{scene_id}/clip/reject")
def reject_scene_clip(
    owner: OwnerDep, studio: StudioDep, universe_id: str, scene_id: str
) -> dict[str, Any]:
    """Compatibilidad: si el clip no gusta, se regenera y sustituye. No-op."""
    return _scenes(studio, universe_id).require(scene_id)


# --- Assembly --------------------------------------------------------------


@router.post("/video-projects/{project_id}/assemble")
def assemble(
    owner: OwnerDep, studio: StudioDep, universe_id: str, project_id: str, body: AssembleIn
) -> dict[str, Any]:
    """El Editor decide como se corta el videoclip: corte seco o fundido en cada
    union, segun la produccion. No es una eleccion del usuario (PRD 43)."""
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
    """Compatibilidad: un proyecto no se aprueba, se termina.

    Estar terminado es un estado derivado: el proyecto esta completo cuando
    su MP4 final renderizado existe (``master_16x9_path``), porque un plan
    de montaje (EDL) sin MP4 no es un videoclip descargable. Ningun gesto
    del usuario cambia eso, asi que este endpoint es un no-op que devuelve
    el proyecto tal cual esta.
    """
    return _projects(studio, universe_id).require(project_id)
