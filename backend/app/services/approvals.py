"""The preconditions a generation call has to pass, kept in one file.

Regla del estudio, corregida por su dueno: NO hay aprobaciones. Lo que se
genera nace en uso y lo que esta actualmente ES lo valido, sin gestos de
aprobar ni estados que bloqueen. Por eso ninguna condicion de este archivo
mira un estado de aprobacion: la condicion valida es que EXISTA la version
actual de lo que el paso siguiente necesita.

* un videoclip arranca cuando la cancion tiene audio generado;
* Lyria se llama cuando la cancion tiene letra escrita;
* una escena entra a Veo cuando tiene su imagen de referencia generada;
* el montaje espera a que cada escena tenga su clip y la cancion su audio;
* una escena que el Director marco como reutilizada no se genera otra vez
  salvo que el usuario fuerce una toma nueva (esto no es aprobacion: es no
  pagar dos veces por la misma toma).
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


def current_audio_path(song: dict[str, Any] | None) -> str | None:
    """El audio vigente de una cancion: el de su version actual.

    Al generarse, la ultima version queda como la vigente (eso lo hace el
    handler de musica en el acto); ``approved_master_path`` es el campo
    historico donde esa ruta vive, y si un documento antiguo solo tuviera
    versiones, manda la ultima.
    """
    if not song:
        return None
    if song.get("approved_master_path"):
        return song["approved_master_path"]
    for version in reversed(song.get("versions") or []):
        if version.get("audio_path"):
            return version["audio_path"]
    return None


def assert_song_ready(db: Database, universe_id: str, song_id: str) -> dict[str, Any]:
    """La cancion puede alimentar un videoclip cuando TIENE audio.

    Nada de aprobada: generada. Si todavia no hay version con audio, lo que
    falta es generarla, no aprobarla.
    """
    song = db.get(doc_path(universe_id, SONGS, song_id))
    if song is None:
        raise NotFound(f"La cancion {song_id} no existe.")
    if not current_audio_path(song):
        raise Conflict(
            "El videoclip no arranca todavia: la cancion aun no tiene audio "
            "generado. Genera primero la cancion."
        )
    return song


def assert_lyrics_ready(db: Database, universe_id: str, song_id: str) -> dict[str, Any]:
    """Lyria se llama cuando la cancion TIENE letra, escrita o generada."""
    song = db.get(doc_path(universe_id, SONGS, song_id))
    if song is None:
        raise NotFound(f"La cancion {song_id} no existe.")
    if not (song.get("lyrics") or "").strip():
        raise Conflict(
            "La cancion todavia no tiene letra. Escribela o pide que la "
            "escriba el Director antes de generar la musica."
        )
    return song


def assert_scene_image_ready(db: Database, universe_id: str, scene_id: str) -> dict[str, Any]:
    """Una escena entra a Veo cuando TIENE su imagen de referencia.

    La imagen vigente es la ultima generada: no hay que aprobarla ni
    bloquearla para que Veo la reciba.
    """
    scene = db.get(doc_path(universe_id, SCENES, scene_id))
    if scene is None:
        raise NotFound(f"La escena {scene_id} no existe.")
    if not scene.get("image_id"):
        raise Conflict(
            "Una escena no entra a video hasta que tenga su imagen de "
            "referencia generada."
        )
    image = db.get(doc_path(universe_id, IMAGES, scene["image_id"]))
    if image is None:
        raise NotFound("La imagen de referencia de la escena no existe.")
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
    assert_song_ready(db, universe_id, project["song_id"])
    scenes = Repository(db, universe_id, SCENES).list(
        where={"project_id": project_id}, order_by="index", descending=False
    )
    if not scenes:
        raise Conflict("El proyecto no tiene escenas.")
    pending = [
        scene["index"]
        for scene in scenes
        if not scene.get("reuses_scene_id") and not scene.get("clip_id")
    ]
    if pending:
        raise ApprovalRequired(
            f"Faltan clips en las escenas {pending}: genera primero el clip "
            "de cada escena.",
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

