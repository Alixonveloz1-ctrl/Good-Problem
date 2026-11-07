"""The artist (PRD 17-18).

Simplified studio: a Universe has ONE character, the artist. There is no cast
to propose, no wardrobe department and no location department — wardrobe and
locations are written inside each video's storyboard and approved with it.

What lives here: the artist's file, their design, their Character Master and
the photo the user can upload as the Master's source.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from ..db.repositories import CHARACTERS, Repository
from ..domain import artist as artist_domain
from ..domain.enums import CanonStatus, CharacterRole, CreativeRole, UserAction
from ..domain.schemas import MASTER_SHOTS
from ..errors import Conflict, InvalidGenerationRequest
from ..ids import new_id
from ..orchestrator import schemas_json as director_schemas
from ..orchestrator.orchestrator import GenerationRequest
from ..orchestrator.roles import system_instruction
from ..providers import gemini_text
from ..providers.storage import character_path
from ..services.approvals import ApprovalService
from ..services.context import load_bible, save_bible, sync_bible_identity
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}", tags=["characters"])


def _repo(studio, universe_id: str, collection: str) -> Repository:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, collection)


def _lead(studio, universe_id: str) -> dict[str, Any] | None:
    repo = _repo(studio, universe_id, CHARACTERS)
    return next(
        (c for c in repo.list(limit=50) if c.get("role") == CharacterRole.LEAD.value),
        None,
    )


# --- The artist ------------------------------------------------------------


class CharacterIn(BaseModel):
    name: str
    gender: str = ""
    rasgos: dict[str, str] = Field(default_factory=dict)
    apparent_age: str = ""
    appearance: str = ""
    personality: str = ""


class CharacterPatch(BaseModel):
    name: str | None = None
    gender: str | None = None
    rasgos: dict[str, str] | None = None
    apparent_age: str | None = None
    appearance: str | None = None
    personality: str | None = None


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
    """Creates THE artist. A Universe has exactly one: asking for a second
    one is a conflict, not a cast."""
    repo = _repo(studio, universe_id, CHARACTERS)
    if _lead(studio, universe_id) is not None:
        raise Conflict(
            "Este estudio ya tiene su artista. Cada universo es un solo artista: "
            "para otro artista, crea otro universo."
        )
    return repo.create(
        new_id("char"),
        {
            **body.model_dump(),
            "role": CharacterRole.LEAD.value,
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
    if body.rasgos is not None:
        # Los rasgos son la fuente: lo que duplican otras fichas (la edad
        # aparente de la identidad) se actualiza en el acto, sin que el
        # usuario tenga que ir a tocarlo a ningun otro sitio.
        sync_bible_identity(studio.db, universe_id)
        updated = repo.require(character_id)
    return updated


@router.post("/characters/{character_id}/design")
def design_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str, body: DesignIn
) -> dict[str, Any]:
    """The Casting Director writes the artist and the Master shot prompts."""
    personaje = _repo(studio, universe_id, CHARACTERS).require(character_id)
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="character",
            target_id=character_id,
            model=body.model,
            role=CreativeRole.CASTING_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "character",
                "brief": body.brief,
                "overrides": body.overrides,
                "locked": _lo_que_ya_decidio(personaje),
            },
        )
    )


def _lo_que_ya_decidio(personaje: dict[str, Any]) -> dict[str, Any]:
    """Lo que el usuario escribio y el Director no puede tocar.

    Escribio "Feri", una artista, y el Director devolvio "Leo Castillo". Un
    generador que cambia el nombre y el sexo de lo que le das no esta
    proponiendo: esta empezando otra cosa.
    """
    fijo = {
        "Stage name": personaje["name"],
        "Gender": personaje["gender"],
    }
    fijo = {k: v for k, v in fijo.items() if v}
    # Y como es, si lo eligio. Lo que dejo en blanco lo decide el Director, que
    # para eso esta; lo que eligio no se discute.
    for clave, valor in (personaje.get("rasgos") or {}).items():
        if valor:
            fijo[ETIQUETAS.get(clave, clave.replace("_", " "))] = valor
    return fijo


ETIQUETAS = {
    "edad": "Exact age",
    "piel": "Skin tone",
    "pelo_color": "Hair colour",
    "pelo_corte": "Hair cut and style",
    "cuerpo": "Body type",
    "estatura": "Height",
    "rostro": "Face shape",
    "ojos": "Eyes",
    "cejas": "Eyebrows",
    "labios": "Lips",
    "vello_facial": "Facial hair",
    "estilo": "Style and wardrobe",
    "actitud": "Attitude on camera",
    "detalles": "Distinctive features",
}
"""Como se lee cada rasgo en el encargo al Director.

Los prompts de imagen van en ingles, asi que la ficha que se le pasa tambien:
un "pelo_corte" suelto entre texto en ingles se lee peor que "Hair cut and
style", y aqui lo que se juega es que salga la persona que se pidio."""


# --- Character Master --------------------------------------------------------


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
    prompt = _con_rasgos_actuales(character, body.prompt or _shot_prompt(character, shot_key))
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
                "reference_paths": _con_retrato_de_referencia(
                    character, shot_key, body.reference_paths
                ),
            },
        )
    )


def _ruta_del_retrato(character: dict[str, Any]) -> str | None:
    """La ruta de la primera ficha, el Portrait, si ya tiene imagen."""
    for shot in character.get("master_shots") or []:
        if shot.get("key") == "portrait" and shot.get("storage_path"):
            return shot["storage_path"]
    return None


def _con_retrato_de_referencia(
    character: dict[str, Any], shot_key: str, pedidas: list[str]
) -> list[str]:
    """Toda toma del Master se apoya en el rostro: el Portrait va primero.

    El Portrait es la primera ficha y la que fija la cara del artista. Si las
    demas tomas se piden solo con el texto, cada una reinterpreta el rostro y
    el artista sale distinto en cada angulo; con el retrato adjunto, el modelo
    copia ESA cara. Lo pone el servidor y no el cliente, porque la regla es
    «siempre»: un cliente que lo olvide no puede dejar una toma sin su
    referencia. Si el cliente mando otras referencias, el retrato va incluido
    y primero, sin duplicarse.

    El retrato no se adjunta a si mismo: nace del texto (o de la foto subida,
    que sigue su propio camino en ``upload_artist_photo``). Y si todavia no
    hay retrato con imagen, no hay nada que adjuntar: la generacion sigue
    como siempre, sin bloquear ni inventar un error nuevo.
    """
    referencias = list(pedidas or [])
    if shot_key == "portrait":
        return referencias
    retrato = _ruta_del_retrato(character)
    if retrato and retrato not in referencias:
        return [retrato, *referencias]
    return referencias


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


def _con_rasgos_actuales(character: dict[str, Any], prompt: str) -> str:
    """Suma al prompt los rasgos que el usuario tiene elegidos AHORA.

    El prompt guardado de la toma y el texto ``appearance`` los escribio el
    Director con los rasgos de aquel momento. Si despues se cambia la edad,
    la barba o los tatuajes con los selectores y nadie reescribe esos textos,
    regenerar pide la cara vieja con las mismas palabras: salia la misma
    cara aunque la ficha ya dijera otra cosa. Este bloque se compone en el
    momento de generar, desde la ficha viva (es texto determinista, no
    cuesta ninguna llamada), y declara que manda sobre cualquier descripcion
    anterior que no coincida. Lo elegido por el usuario manda siempre: es la
    misma garantia que ``_lo_que_ya_decidio`` aplica sobre el Director.
    """
    decidio = _lo_que_ya_decidio(character)
    if not decidio:
        return prompt
    rasgos = "; ".join(f"{clave}: {valor}" for clave, valor in decidio.items())
    bloque = (
        "Current traits chosen by the user (authoritative: they define this "
        "person and override any earlier description that disagrees): "
        f"{rasgos}."
    )
    if bloque in prompt:
        return prompt
    return f"{prompt}\n\n{bloque}" if prompt else bloque


def _approve_master(studio, universe_id: str, character_id: str) -> dict[str, Any]:
    """Approving the Master is what turns those images into the references
    attached to every later generation with this artist (PRD 18). It also
    clears the stale flag: a fresh Master is by definition in the current
    visual style."""
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
        master_stale=False,
    )
    bible = load_bible(studio.db, universe_id)
    if bible.visual.master_stale:
        bible.visual.master_stale = False
        save_bible(studio.db, universe_id, bible)
    approvals.record_user_action(universe_id, CHARACTERS, character_id, UserAction.APPROVE)
    approvals.save_to_canon(
        universe_id,
        entity_type="character",
        entity_id=character_id,
        label=character.get("name", ""),
        storage_path=shots[0]["storage_path"],
    )
    return updated


@router.post("/characters/{character_id}/approve")
def approve_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str
) -> dict[str, Any]:
    """Compatibilidad: ya no hay nada que aprobar.

    Lo generado nace aprobado y en uso desde que se genera (eso lo hace el
    handler de imagenes en el acto), asi que este endpoint devuelve la ficha
    tal cual esta, sin tocar nada. Se queda porque clientes antiguos aun
    pueden llamarlo.
    """
    return _repo(studio, universe_id, CHARACTERS).require(character_id)


@router.delete("/characters/{character_id}")
def delete_character(
    owner: OwnerDep, studio: StudioDep, universe_id: str, character_id: str
) -> dict[str, str]:
    """Borra al artista.

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
    """Compatibilidad: rechazar ya no existe como gesto.

    Si algo no gusta, se regenera, y lo regenerado sustituye a lo anterior.
    Este endpoint devuelve la ficha tal cual esta, sin tocar nada.
    """
    return _repo(studio, universe_id, CHARACTERS).require(character_id)


# --- The uploaded photo ------------------------------------------------------

PHOTO_MODES = {"use_as_master", "base_for_master", "copy_style"}


@router.post("/characters/{character_id}/photo")
async def upload_artist_photo(
    owner: OwnerDep,
    studio: StudioDep,
    universe_id: str,
    character_id: str,
    file: UploadFile = File(...),
    mode: str = Form("use_as_master"),
    model: str | None = Form(None),
) -> dict[str, Any]:
    """Una foto del usuario como origen del Master, con tres caminos:

    - ``use_as_master``: la foto ES el retrato del artista, tal cual, y queda
      aprobado como Master.
    - ``base_for_master``: se genera un retrato nuevo desde la foto, en el
      estilo elegido, conservando la cara. Es tambien la salida cuando una
      foto de persona real hace que el filtro de Google bloquee los clips.
    - ``copy_style``: no se usa la cara; se lee el ESTILO de la foto y ese
      estilo queda como el estilo visual fijo del artista.
    """
    if mode not in PHOTO_MODES:
        raise InvalidGenerationRequest(
            "Modo de foto no valido: usa la foto tal cual, genera desde ella o copia su estilo."
        )
    repo = _repo(studio, universe_id, CHARACTERS)
    character = repo.require(character_id)
    data = await file.read()
    if not data:
        raise InvalidGenerationRequest("La foto llego vacia.")
    mime = file.content_type or "image/jpeg"
    suffix = "png" if "png" in mime else "jpg"
    stored = studio.storage.write_bytes(
        character_path(universe_id, f"{character_id}_photo.{suffix}"), data, mime
    )
    repo.update(character_id, {"source_photo_path": stored.path})

    if mode == "use_as_master":
        shots = list(character.get("master_shots") or [])
        for shot in shots:
            if shot.get("key") == "portrait":
                shot["storage_path"] = stored.path
                shot["status"] = CanonStatus.DRAFT.value
                # La foto se guarda siempre en la misma ruta: al subir otra,
                # la version es lo unico que distingue la nueva de la vieja
                # en la URL que pinta la vista.
                shot["version"] = int(shot.get("version") or 0) + 1
        if not any(s.get("key") == "portrait" for s in shots):
            shots.append(
                {"key": "portrait", "label": "Retrato", "image_id": None,
                 "storage_path": stored.path, "status": CanonStatus.DRAFT.value,
                 "prompt": "", "version": 1}
            )
        repo.update(character_id, {"master_shots": shots})
        actualizado = _approve_master(studio, universe_id, character_id)
        return {**actualizado, "photo_mode": mode, "photo_path": stored.path}

    if mode == "copy_style":
        spec = studio.registry.default_for("text")
        resultado = gemini_text.generate(
            studio.vertex,
            spec.id if spec else "gemini-3.1-pro-preview",
            system_instruction=system_instruction(CreativeRole.CREATIVE_DIRECTOR),
            prompt=(
                "Describe the visual style of this image so it can be applied "
                "to every future image of one fictional music artist. Style "
                "only: do not identify or describe the person."
            ),
            schema=director_schemas.PHOTO_STYLE_SCHEMA,
            references=[(data, mime)],
        )
        descripcion = (resultado.data or {}).get("style_description", "")
        bible = load_bible(studio.db, universe_id)
        bible.visual.style_key = artist_domain.PHOTO_STYLE_KEY
        bible.visual.style_label = artist_domain.visual_style_label(
            artist_domain.PHOTO_STYLE_KEY
        )
        bible.visual.photo_style_description = descripcion
        artista = repo.require(character_id)
        if any(s.get("storage_path") for s in artista.get("master_shots") or []):
            bible.visual.master_stale = True
            repo.update(character_id, {"master_stale": True})
        save_bible(studio.db, universe_id, bible)
        return {
            "photo_mode": mode,
            "photo_path": stored.path,
            "visual": bible.visual.model_dump(),
        }

    # base_for_master: a new portrait from the photo, in the chosen style.
    bible = load_bible(studio.db, universe_id)
    estilo = artist_domain.visual_style_prompt(bible)
    base = _con_rasgos_actuales(character, _shot_prompt(character, "portrait"))
    prompt = (
        (base + "\n\n") if base else ""
    ) + (
        "New portrait of this same person, generated from the attached photo. "
        "Keep the face and the recognisable features exactly; render the "
        "person in the artist's fixed visual style."
        + (f"\nStyle: {estilo}" if estilo else "")
    )
    trabajo = studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="character",
            target_id=character_id,
            model=model,
            payload={
                "purpose": "character_master",
                "shot_key": "portrait",
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "reference_paths": [stored.path],
            },
        )
    )
    return {"photo_mode": mode, "photo_path": stored.path, "job": trabajo}
