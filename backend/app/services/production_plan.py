"""Production Plan (PRD 27, 28).

The Producer counts what a production really involves before anything expensive
runs: how many scenes, how many of them reuse an existing take, how many images
and clips are actually needed, with which models, and what that adds up to.

It is a forecast, not a ledger. The studio keeps no running total: what has been
spent is read in the Google Cloud console.

The user can approve it, modify it or cancel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db.repositories import CHARACTERS, LOCATIONS, SCENES, VIDEO_PROJECTS, WARDROBE, Repository
from ..domain.enums import CanonStatus, ModelKind
from ..domain.pricing import estimate_images, estimate_video
from ..errors import NotFound


@dataclass
class PlanInputs:
    image_model: str
    image_variant: str
    video_model: str
    video_variant: str
    attempts_per_image: float = 1.0
    attempts_per_clip: float = 1.0
    clip_seconds: int = 8
    vertical_derivatives: int = 4


def build(
    studio,
    universe_id: str,
    project_id: str,
    inputs: PlanInputs,
) -> dict[str, Any]:
    project = Repository(studio.db, universe_id, VIDEO_PROJECTS).get(project_id)
    if project is None:
        raise NotFound(f"El proyecto {project_id} no existe.")

    scenes = Repository(studio.db, universe_id, SCENES).list(
        where={"project_id": project_id}, order_by="index", descending=False
    )
    reused = [s for s in scenes if s.get("reuses_scene_id")]
    to_generate = [s for s in scenes if not s.get("reuses_scene_id")]

    images_needed = sum(
        1 for s in to_generate if s.get("image_status") != CanonStatus.APPROVED.value
    )
    clips_needed = sum(1 for s in to_generate if s.get("clip_status") != CanonStatus.APPROVED.value)

    registry = studio.registry
    registry.require_active(inputs.image_model, ModelKind.IMAGE)
    registry.require_active(inputs.video_model, ModelKind.VIDEO)

    image_attempts = round(images_needed * inputs.attempts_per_image)
    clip_attempts = round(clips_needed * inputs.attempts_per_clip)

    image_cost = estimate_images(
        registry, inputs.image_model, inputs.image_variant, images=image_attempts
    )
    video_cost = estimate_video(
        registry,
        inputs.video_model,
        inputs.video_variant,
        seconds=inputs.clip_seconds,
        clips=clip_attempts,
    )

    total = image_cost.amount_usd + video_cost.amount_usd

    return {
        "project_id": project_id,
        "project_title": project.get("title") or project.get("id"),
        "video_type": project.get("video_type"),
        "scenes": len(scenes),
        "characters": len(Repository(studio.db, universe_id, CHARACTERS).list(limit=200)),
        "locations": len(Repository(studio.db, universe_id, LOCATIONS).list(limit=200)),
        "wardrobe": len(Repository(studio.db, universe_id, WARDROBE).list(limit=200)),
        "scene_images": {
            "count": image_attempts,
            "model": inputs.image_model,
            "variant": inputs.image_variant,
            "cost_usd": round(image_cost.amount_usd, 2),
        },
        "video_clips": {
            "count": clip_attempts,
            "model": inputs.video_model,
            "variant": inputs.video_variant,
            "seconds_each": inputs.clip_seconds,
            "audio": False,
            "cost_usd": round(video_cost.amount_usd, 2),
        },
        "reused_takes": len(reused),
        "vertical_derivatives": inputs.vertical_derivatives,
        "vertical_cost_usd": 0.0,
        "estimated_generation_cost_usd": round(total, 2),
    }


def render_text(plan: dict[str, Any]) -> str:
    """The plain block shown on the phone (PRD 28)."""
    images = plan["scene_images"]
    clips = plan["video_clips"]
    return "\n".join(
        [
            "PROJECT:",
            str(plan["project_title"]),
            "",
            "VIDEO TYPE:",
            str(plan["video_type"]),
            "",
            "SCENES:",
            str(plan["scenes"]),
            "",
            "CHARACTERS:",
            str(plan["characters"]),
            "",
            "LOCATIONS:",
            str(plan["locations"]),
            "",
            "WARDROBE:",
            str(plan["wardrobe"]),
            "",
            "SCENE IMAGES:",
            f"{images['count']}   (modelo: {images['model']} {images['variant']})",
            "",
            "VIDEO CLIPS:",
            f"{clips['count']}   (modelo: {clips['model']} {clips['variant']}, sin audio)",
            "",
            "TOMAS REUTILIZADAS:",
            str(plan["reused_takes"]),
            "",
            "VERTICAL DERIVATIVES:",
            str(plan["vertical_derivatives"]),
            "",
            "ESTIMATED GENERATION COST:",
            f"${plan['estimated_generation_cost_usd']:,.2f}",
        ]
    )
