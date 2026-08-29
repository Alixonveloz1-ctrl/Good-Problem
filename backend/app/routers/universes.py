"""Universes, Artist Bible and Canon (PRD 8, 9, 16)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..container import Studio
from ..db.repositories import (
    CANON,
    CHARACTERS,
    SONGS,
    UNIVERSES,
    VIDEO_PROJECTS,
    Repository,
    universe_path,
)
from ..domain.enums import CanonStatus, CharacterRole, CreativeRole
from ..domain.schemas import MASTER_SHOTS, ArtistBible, Universe
from ..errors import NotFound
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services.approvals import ApprovalService
from ..services.context import load_bible, save_bible, summarize_bible
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes", tags=["universes"])

logger = logging.getLogger("aaus.universes")


class UniverseIn(BaseModel):
    """Quien es el artista. Se pregunta una vez y no se vuelve a preguntar.

    Antes se creaba un universo con un nombre, y dentro habia que crear otra vez
    al artista con otro nombre. Dos nombres para la misma persona, y el segundo
    lo cambiaba el Director por su cuenta.
    """

    name: str
    tagline: str = ""
    gender: str = ""
    genre: str = ""
    notes: str = ""


class UniversePatch(BaseModel):
    name: str | None = None
    tagline: str | None = None
    cover_image: str | None = None


@router.post("")
def create_universe(owner: OwnerDep, studio: StudioDep, body: UniverseIn) -> dict[str, Any]:
    """Crea el artista entero: su mundo, su ficha y el encargo al Director.

    Un solo formulario. Antes eran dos pantallas y dos nombres, y lo que se
    escribia en la segunda lo reescribia el Director de casting.
    """
    universe_id = new_id("uni")
    universe = Universe(
        id=universe_id,
        universe_id=universe_id,
        name=body.name,
        tagline=body.tagline or body.genre,
    )
    studio.db.set(universe_path(universe_id), universe.model_dump())
    # A universe starts with an empty Bible so every later call has something
    # to read (PRD 42.4).
    save_bible(studio.db, universe_id, ArtistBible(id="current", universe_id=universe_id))

    # Y el artista, que ES el estudio. El nombre y el sexo quedan puestos desde
    # aqui: son lo unico que el Director tiene prohibido cambiar.
    protagonista = Repository(studio.db, universe_id, CHARACTERS).create(
        new_id("char"), _ficha_en_blanco(body.name, body.gender)
    )

    # Y se pone a trabajar solo. Nadie tiene que acordarse de pedirselo: sin el
    # diseno no hay prompts, y sin prompts ningun boton de "Generar" funciona,
    # que es exactamente donde se quedaba encallado.
    encargo = None
    try:
        encargo = studio.orchestrator.submit(
            GenerationRequest(
                universe_id=universe_id,
                kind="text",
                target_type="character",
                target_id=protagonista["id"],
                role=CreativeRole.CASTING_DIRECTOR,
                payload={
                    "task": "character",
                    "brief": _quien_es(body),
                    "locked": {"name": body.name, "gender": body.gender},
                },
            )
        )
    except Exception:  # pragma: no cover - el artista existe igual
        # Si el encargo no sale, el artista ya esta creado y se puede volver a
        # pedir el diseno desde su pantalla. Perder el universo por esto seria
        # mucho peor que empezar sin retrato.
        logger.exception("no se pudo encargar el diseno inicial de %s", universe_id)

    return {**universe.model_dump(), "lead_character_id": protagonista["id"], "job": encargo}


def _ficha_en_blanco(nombre: str, genero: str = "") -> dict[str, Any]:
    """El protagonista recien creado: su nombre, quien es, y nada mas."""
    return {
        "name": nombre,
        "role": CharacterRole.LEAD.value,
        "gender": genero,
        "apparent_age": "",
        "appearance": "",
        "personality": "",
        "master_shots": [
            {"key": key, "label": label, "storage_path": None,
             "status": CanonStatus.DRAFT.value, "prompt": ""}
            for key, label in MASTER_SHOTS
        ],
        "reference_image_paths": [],
        "status": CanonStatus.DRAFT.value,
    }


def _quien_es(body: UniverseIn) -> str:
    """Lo que el usuario conto del artista, en una sola nota para el Director."""
    partes = [f"Artist stage name: {body.name}."]
    if body.gender:
        partes.append(f"Gender: {body.gender}.")
    if body.genre:
        partes.append(f"Musical genre: {body.genre}.")
    if body.notes:
        partes.append(body.notes.strip())
    return " ".join(partes)


@router.get("")
def list_universes(owner: OwnerDep, studio: StudioDep) -> list[dict[str, Any]]:
    return studio.db.list(UNIVERSES, order_by="updated_at", limit=100)


@router.get("/{universe_id}")
def get_universe(owner: OwnerDep, studio: StudioDep, universe_id: str) -> dict[str, Any]:
    universe = studio.db.get(universe_path(universe_id))
    if universe is None:
        raise NotFound(f"El universe {universe_id} no existe.")
    return {**universe, "siguiente": siguiente_paso(studio, universe)}


def siguiente_paso(studio: Studio, universe: dict[str, Any]) -> dict[str, Any]:
    """Que toca ahora, una sola cosa.

    "No se ni por donde empezar ni que crear ni que ver." La pantalla del
    artista era un indice de once puertas sin ningun orden entre ellas, y un
    indice no dice que hacer: lo dice quien ya sabe el camino.

    El camino es este y no cambia: primero se sabe quien es el artista, luego
    se le ve la cara, luego tiene una cancion, y con la cancion se monta el
    videoclip. Cada paso necesita el anterior de verdad -un video sin cara
    aprobada no sabe a quien esta grabando- asi que ensenar los cuatro a la vez
    es ensenar tres callejones.
    """
    uid = universe["id"]
    nombre = universe.get("name") or "tu artista"
    personajes = Repository(studio.db, uid, CHARACTERS).list(limit=50)
    artista = next((p for p in personajes if p.get("role") == CharacterRole.LEAD.value), None)

    if artista is None:
        # Pasa en los universos creados antes de que crear al artista fuera un
        # solo paso. Sin protagonista, la pantalla acababa ensenando a un
        # secundario como si fuera el artista.
        return _paso(
            "artista",
            f"Falta {nombre}",
            "Este es su estudio, pero el artista todavía no existe dentro. "
            "Se crea con el nombre que le pusiste.",
            accion="crear_artista",
            boton=f"Crear a {nombre}",
        )

    if not artista.get("gender"):
        return _paso(
            "genero",
            f"Di quién es {artista.get('name') or nombre}",
            "Si no lo dices, lo elige el Director, y de un nombre de mujer puede "
            "sacar un hombre.",
            ir_a="characters",
            boton="Decirlo",
        )

    tomas = artista.get("master_shots") or []
    if not any(t.get("storage_path") for t in tomas):
        return _paso(
            "cara",
            f"Genérale la cara a {artista.get('name') or nombre}",
            "Es lo primero de todo. Cada video parte de una imagen suya: sin "
            "ella, no saben a quién están grabando.",
            ir_a="characters",
            boton="Generar su retrato",
        )

    if artista.get("status") != CanonStatus.APPROVED.value:
        return _paso(
            "aprobar_cara",
            "Aprueba su cara",
            "Al aprobarla queda fijada, y a partir de ahí viaja como referencia "
            "en todo lo que se genere: es lo que hace que siempre sea la misma persona.",
            ir_a="characters",
            boton="Ir a aprobarla",
        )

    canciones = Repository(studio.db, uid, SONGS).list(limit=50)
    if not canciones:
        return _paso(
            "cancion",
            "Su primera canción",
            "Un videoclip se monta sobre una canción aprobada, así que la "
            "música va antes que el video.",
            ir_a="songs",
            boton="Empezar una canción",
        )

    if not any(c.get("status") == CanonStatus.APPROVED.value for c in canciones):
        return _paso(
            "aprobar_cancion",
            "Termina su canción",
            "Cuando esté aprobada se puede montar el videoclip encima.",
            ir_a="songs",
            boton="Ir a la canción",
        )

    proyectos = Repository(studio.db, uid, VIDEO_PROJECTS).list(limit=50)
    if not proyectos:
        return _paso(
            "videoclip",
            "Su primer videoclip",
            "Ya hay cara aprobada y canción aprobada: es justo lo que hace falta "
            "para empezar a rodar.",
            ir_a="projects",
            boton="Montar el videoclip",
        )

    return _paso(
        "seguir",
        "Sigue produciendo",
        "Lo básico está: tiene cara, tiene música y tiene video. Desde aquí, "
        "más canciones, más videoclips y contenido para redes.",
        ir_a="projects",
        boton="Ver sus videoclips",
    )


def _paso(
    clave: str,
    titulo: str,
    porque: str,
    *,
    ir_a: str = "",
    accion: str = "",
    boton: str = "",
) -> dict[str, str]:
    return {"clave": clave, "titulo": titulo, "porque": porque,
            "ir_a": ir_a, "accion": accion, "boton": boton}


@router.post("/{universe_id}/artista")
def crear_artista(owner: OwnerDep, studio: StudioDep, universe_id: str) -> dict[str, Any]:
    """Crea el protagonista que falta, con el nombre del estudio.

    Solo hace falta en los estudios creados antes de que el artista se creara
    solo. Si ya hay uno, no toca nada.
    """
    universe = studio.db.get(universe_path(universe_id))
    if universe is None:
        raise NotFound(f"El universe {universe_id} no existe.")
    repo = Repository(studio.db, universe_id, CHARACTERS)
    existente = next(
        (p for p in repo.list(limit=50) if p.get("role") == CharacterRole.LEAD.value), None
    )
    if existente is not None:
        return existente
    return repo.create(new_id("char"), _ficha_en_blanco(universe.get("name", "")))


@router.patch("/{universe_id}")
def patch_universe(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: UniversePatch
) -> dict[str, Any]:
    studio.orchestrator.require_universe(universe_id)
    return studio.db.update(universe_path(universe_id), body.model_dump(exclude_none=True))


@router.delete("/{universe_id}")
def delete_universe(owner: OwnerDep, studio: StudioDep, universe_id: str) -> dict[str, str]:
    studio.orchestrator.require_universe(universe_id)
    studio.db.delete(universe_path(universe_id))
    return {"deleted": universe_id}


# --- Artist Bible ----------------------------------------------------------


class BibleGenerateIn(BaseModel):
    brief: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    idempotency_key: str | None = None


@router.get("/{universe_id}/bible")
def get_bible(owner: OwnerDep, studio: StudioDep, universe_id: str) -> dict[str, Any]:
    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    return {**bible.model_dump(), "summary": summarize_bible(bible)}


@router.put("/{universe_id}/bible")
def put_bible(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """The user can edit any part of the Bible by hand (PRD 3: EDIT)."""
    studio.orchestrator.require_universe(universe_id)
    current = load_bible(studio.db, universe_id).model_dump()
    merged = {**current, **body, "id": "current", "universe_id": universe_id}
    merged["status"] = body.get("status", CanonStatus.DRAFT.value)
    bible = ArtistBible.model_validate(merged)
    save_bible(studio.db, universe_id, bible)
    return bible.model_dump()


@router.post("/{universe_id}/bible/generate")
def generate_bible(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: BibleGenerateIn
) -> dict[str, Any]:
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="artist_bible",
            target_id="current",
            model=body.model,
            role=CreativeRole.CREATIVE_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "artist_bible",
                "brief": body.brief,
                "overrides": body.overrides,
            },
        )
    )


@router.post("/{universe_id}/bible/approve")
def approve_bible(owner: OwnerDep, studio: StudioDep, universe_id: str) -> dict[str, Any]:
    bible = load_bible(studio.db, universe_id)
    bible.status = CanonStatus.APPROVED.value  # type: ignore[assignment]
    save_bible(studio.db, universe_id, bible)
    ApprovalService(studio.db).save_to_canon(
        universe_id,
        entity_type="artist_bible",
        entity_id="current",
        label=bible.identity.stage_name or "Artist Bible",
    )
    return bible.model_dump()


class VoiceProfileIn(BaseModel):
    lines: list[str]
    speaking_voice_secret: str | None = None


@router.put("/{universe_id}/bible/voice-profile")
def put_voice_profile(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: VoiceProfileIn
) -> dict[str, Any]:
    """The Voice Profile travels verbatim in every music prompt (PRD 10)."""
    bible = load_bible(studio.db, universe_id)
    bible.voice_profile.lines = body.lines
    if body.speaking_voice_secret is not None:
        bible.voice_profile.speaking_voice_secret = body.speaking_voice_secret
    save_bible(studio.db, universe_id, bible)
    return bible.voice_profile.model_dump()


class PreferencesIn(BaseModel):
    preferred_image_model: str | None = None
    preferred_image_variant: str | None = None
    preferred_video_model: str | None = None
    preferred_video_variant: str | None = None
    working_resolution: str | None = None


@router.put("/{universe_id}/bible/preferences")
def put_preferences(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: PreferencesIn
) -> dict[str, Any]:
    """Fallback models when the user does not pick one for a generation
    (PRD 9, 42.8). The per-generation choice always wins."""
    bible = load_bible(studio.db, universe_id)
    patch = body.model_dump(exclude_none=True)
    for key, value in patch.items():
        setattr(bible.preferences, key, value)
    save_bible(studio.db, universe_id, bible)
    return bible.preferences.model_dump()


# --- Canon -----------------------------------------------------------------


class CanonIn(BaseModel):
    entity_type: str
    entity_id: str
    label: str = ""
    storage_path: str | None = None
    note: str = ""


@router.get("/{universe_id}/canon")
def list_canon(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, CANON).list(limit=200)


@router.post("/{universe_id}/canon")
def add_canon(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: CanonIn
) -> dict[str, Any]:
    studio.orchestrator.require_universe(universe_id)
    return ApprovalService(studio.db).save_to_canon(
        universe_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        label=body.label,
        storage_path=body.storage_path,
        note=body.note,
    )


@router.delete("/{universe_id}/canon/{entry_id}")
def archive_canon(
    owner: OwnerDep, studio: StudioDep, universe_id: str, entry_id: str
) -> dict[str, Any]:
    return ApprovalService(studio.db).archive(universe_id, CANON, entry_id)
