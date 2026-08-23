"""The approval gates (PRD 3, 36, and the stage rules scattered through 14-31).

"La IA propone y produce. El usuario decide." In code that means a small number
of preconditions that generation calls have to pass, kept in one file so they
can be read as a list:

* a rejected song does not trigger a music video (PRD 14);
* mass image generation waits for an approved storyboard (PRD 23);
* a scene does not reach Veo until its image is approved and locked (PRD 24);
* assembly waits for approved clips and an approved master audio (PRD 31);
* a scene the Director marked as reused is not generated again unless the user
  forces it (PRD 23).
"""

from __future__ import annotations

from typing import Any

from ..clock import now_iso
from ..db.client import Database
from ..db.repositories import (
    CANON,
    IMAGES,
    SCENES,
    SONGS,
    VIDEO_PROJECTS,
    Repository,
    doc_path,
)
from ..domain.enums import CanonStatus, StageKey, StageStatus, UserAction
from ..errors import ApprovalRequired, Conflict, NotFound
from ..ids import new_id


def _status(doc: dict[str, Any] | None, field: str = "status") -> str:
    return (doc or {}).get(field, CanonStatus.DRAFT.value)


def is_approved(doc: dict[str, Any] | None, field: str = "status") -> bool:
    return _status(doc, field) == CanonStatus.APPROVED.value


# --- Preconditions ---------------------------------------------------------


def assert_song_approved(db: Database, universe_id: str, song_id: str) -> dict[str, Any]:
    song = db.get(doc_path(universe_id, SONGS, song_id))
    if song is None:
        raise NotFound(f"La cancion {song_id} no existe.")
    if not is_approved(song):
        raise ApprovalRequired(
            "El videoclip no arranca hasta que la cancion este aprobada. "
            f"Estado actual: {_status(song)}."
        )
    if not song.get("approved_master_path"):
        raise ApprovalRequired("La cancion esta aprobada pero no tiene master de audio.")
    return song


def assert_lyrics_approved(db: Database, universe_id: str, song_id: str) -> dict[str, Any]:
    song = db.get(doc_path(universe_id, SONGS, song_id))
    if song is None:
        raise NotFound(f"La cancion {song_id} no existe.")
    if song.get("lyrics_status") != CanonStatus.APPROVED.value:
        raise ApprovalRequired(
            "Lyria no se llama hasta que la letra este aprobada. "
            f"Estado actual: {song.get('lyrics_status', 'DRAFT')}."
        )
    return song


def assert_storyboard_approved(db: Database, universe_id: str, project_id: str) -> dict[str, Any]:
    project = db.get(doc_path(universe_id, VIDEO_PROJECTS, project_id))
    if project is None:
        raise NotFound(f"El proyecto {project_id} no existe.")
    if project.get("storyboard_status") != CanonStatus.APPROVED.value:
        raise ApprovalRequired(
            "El storyboard tiene que estar aprobado antes de la generacion masiva de imagenes."
        )
    return project


def assert_scene_image_locked(db: Database, universe_id: str, scene_id: str) -> dict[str, Any]:
    scene = db.get(doc_path(universe_id, SCENES, scene_id))
    if scene is None:
        raise NotFound(f"La escena {scene_id} no existe.")
    if scene.get("image_status") != CanonStatus.APPROVED.value or not scene.get("image_id"):
        raise ApprovalRequired(
            "Una escena no entra a video hasta que su imagen de referencia este aprobada."
        )
    image = db.get(doc_path(universe_id, IMAGES, scene["image_id"]))
    if image is None:
        raise NotFound("La imagen aprobada de la escena no existe.")
    if not image.get("locked"):
        raise ApprovalRequired("La imagen de la escena esta aprobada pero no bloqueada.")
    return scene


def assert_scene_not_reused(scene: dict[str, Any]) -> None:
    if scene.get("reuses_scene_id") and not scene.get("reuse_forced_by_user"):
        raise Conflict(
            "El Director marco esta toma para reutilizar material ya aprobado. "
            "Fuerza la generacion desde la escena si quieres una toma nueva."
        )


def assert_ready_for_assembly(db: Database, universe_id: str, project_id: str) -> dict[str, Any]:
    project = db.get(doc_path(universe_id, VIDEO_PROJECTS, project_id))
    if project is None:
        raise NotFound(f"El proyecto {project_id} no existe.")
    assert_song_approved(db, universe_id, project["song_id"])
    scenes = Repository(db, universe_id, SCENES).list(
        where={"project_id": project_id}, order_by="index", descending=False
    )
    if not scenes:
        raise Conflict("El proyecto no tiene escenas.")
    pending = [
        scene["index"]
        for scene in scenes
        if not scene.get("reuses_scene_id")
        and scene.get("clip_status") != CanonStatus.APPROVED.value
    ]
    if pending:
        raise ApprovalRequired(
            f"Faltan clips aprobados en las escenas {pending}.",
            details={"pending_scenes": pending},
        )
    return project


# --- Transitions -----------------------------------------------------------


class ApprovalService:
    """Applies APPROVE / REGENERATE / EDIT / REJECT / SAVE TO CANON to any
    document that carries a ``status`` field."""

    def __init__(self, db: Database):
        self.db = db

    def _repo(self, universe_id: str, collection: str) -> Repository:
        return Repository(self.db, universe_id, collection)

    def set_status(
        self,
        universe_id: str,
        collection: str,
        doc_id: str,
        status: CanonStatus,
        *,
        field: str = "status",
        note: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {field: status.value, **(extra or {})}
        doc = self._repo(universe_id, collection).require(doc_id)
        history = list(doc.get("approval_history") or [])
        history.append(
            {
                "field": field,
                "from": doc.get(field),
                "to": status.value,
                "note": note,
                "at": now_iso(),
            }
        )
        patch["approval_history"] = history[-40:]
        return self._repo(universe_id, collection).update(doc_id, patch)

    def approve(self, universe_id: str, collection: str, doc_id: str, *, note: str = "", **extra):
        return self.set_status(
            universe_id, collection, doc_id, CanonStatus.APPROVED, note=note, extra=extra
        )

    def reject(self, universe_id: str, collection: str, doc_id: str, *, note: str = "", **extra):
        return self.set_status(
            universe_id, collection, doc_id, CanonStatus.REJECTED, note=note, extra=extra
        )

    def archive(self, universe_id: str, collection: str, doc_id: str, *, note: str = ""):
        return self.set_status(universe_id, collection, doc_id, CanonStatus.ARCHIVED, note=note)

    def record_user_action(
        self,
        universe_id: str,
        collection: str,
        doc_id: str,
        action: UserAction,
        *,
        written: str = "",
        edited: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Provenance keeps what the human contributed, not only what the model
        produced (PRD 46)."""
        doc = self._repo(universe_id, collection).require(doc_id)
        provenance = dict(doc.get("provenance") or {})
        contributions = list(provenance.get("user_contributions") or [])
        contributions.append(
            {
                "action": action.value,
                "written": written or None,
                "edited": edited or None,
                "note": note or None,
                "at": now_iso(),
            }
        )
        provenance["user_contributions"] = contributions[-50:]
        return self._repo(universe_id, collection).update(doc_id, {"provenance": provenance})

    def save_to_canon(
        self,
        universe_id: str,
        *,
        entity_type: str,
        entity_id: str,
        label: str = "",
        storage_path: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Approved assets become Canon and are used as preferred context and as
        reference images in later generations (PRD 16)."""
        existing = self._repo(universe_id, CANON).list(where={"entity_id": entity_id}, limit=1)
        if existing:
            return self._repo(universe_id, CANON).update(
                existing[0]["id"],
                {
                    "label": label or existing[0].get("label", ""),
                    "storage_path": storage_path or existing[0].get("storage_path"),
                    "status": CanonStatus.APPROVED.value,
                    "note": note or existing[0].get("note", ""),
                },
            )
        return self._repo(universe_id, CANON).create(
            new_id("canon"),
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "label": label,
                "storage_path": storage_path,
                "status": CanonStatus.APPROVED.value,
                "note": note,
            },
        )


# --- Stage rail (PRD 38) ---------------------------------------------------

_STAGE_LABELS: dict[StageKey, str] = {
    StageKey.CONCEPT: "Concepto",
    StageKey.MUSIC: "Musica",
    StageKey.STORY: "Historia",
    StageKey.CHARACTERS: "Personajes",
    StageKey.STORYBOARD: "Storyboard",
    StageKey.IMAGES: "Imagenes",
    StageKey.VIDEO: "Video",
    StageKey.ASSEMBLY: "Ensamblaje",
    StageKey.EXPORT: "Export",
}


def stage_label(key: StageKey | str) -> str:
    return _STAGE_LABELS.get(StageKey(key), str(key))


def build_stage(key: StageKey, status: StageStatus, **extra: Any) -> dict[str, Any]:
    return {
        "key": key.value,
        "label": stage_label(key),
        "status": status.value,
        "updated_at": now_iso(),
        **extra,
    }

