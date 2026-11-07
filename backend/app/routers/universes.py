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
from ..domain import artist as artist_domain
from ..domain.enums import CanonStatus, CharacterRole, CreativeRole
from ..domain.schemas import MASTER_SHOTS, ArtistBible, Inspiration, SingingVoice, Universe
from ..errors import InvalidGenerationRequest, NotFound
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services import approvals as approval_rules
from ..services import inspiration as inspiration_service
from ..services.approvals import ApprovalService
from ..services.context import load_bible, save_bible, summarize_bible, sync_bible_identity
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
    visual_style: str = ""
    """Clave de estilo de domain.artist.VISUAL_STYLES. Fijo para el artista."""
    music_genres: list[str] = Field(default_factory=list)
    """Hasta tres generos principales, combinables."""
    inspiration_urls: list[str] = Field(default_factory=list)
    """Enlaces de YouTube de referencia: la app los analiza sola."""


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
    # to read (PRD 42.4). What the form already decided goes in now: the
    # visual style, the genre combination and the analysed inspirations.
    bible = ArtistBible(id="current", universe_id=universe_id)
    if body.visual_style in artist_domain.VISUAL_STYLE_KEYS:
        bible.visual.style_key = body.visual_style
        bible.visual.style_label = artist_domain.visual_style_label(body.visual_style)
    bible.music_genres = [
        g for g in body.music_genres if g in artist_domain.MUSIC_GENRE_KEYS
    ][: artist_domain.MAX_MAIN_GENRES]
    if body.genre and not bible.music_genres:
        bible.musical.genre = body.genre
    for enlace in body.inspiration_urls:
        try:
            bible.inspirations.append(inspiration_service.analyse_youtube(studio, enlace))
        except Exception:
            # Un enlace que no se puede analizar no puede tumbar la creacion
            # del artista: se puede volver a pegar desde su ficha. Pero ya
            # no desaparece en silencio: queda en la lista visible de
            # enlaces fallidos de la ficha, para que se sepa que falta.
            logger.exception("no se pudo analizar la inspiracion %s", enlace)
            bible.inspirations_failed.append(enlace)
    save_bible(studio.db, universe_id, bible)

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
    generada no sabe a quien esta grabando- asi que ensenar los cuatro a la vez
    es ensenar tres callejones. Ningun paso pide aprobar nada: lo que existe
    es lo que vale.
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

    bible = load_bible(studio.db, uid)
    if not bible.visual.style_key:
        return _paso(
            "estilo",
            f"Elige cómo se ve {artista.get('name') or nombre}",
            "Su estilo visual queda fijo: realista, un anime, óleo... Todas "
            "sus fotos y todos sus videos salen con ese mismo estilo.",
            ir_a="bible",
            boton="Elegir su estilo",
        )

    if artista.get("master_stale") or bible.visual.master_stale:
        return _paso(
            "rehacer_cara",
            "Su estilo cambió: hay que rehacer su cara",
            "Cambiaste su estilo visual después de generar su cara, así que "
            "esa cara ya no es su estilo. Se genera otra con el estilo nuevo "
            "y a partir de ahí todo sale en el estilo nuevo.",
            ir_a="characters",
            boton="Rehacer su cara",
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

    # Con la cara generada ya esta en uso: viaja como referencia en todo lo
    # que se genere, sin aprobarla nadie. Lo siguiente es la musica.

    canciones = Repository(studio.db, uid, SONGS).list(limit=50)
    if not canciones:
        return _paso(
            "cancion",
            "Su primera canción",
            "Un videoclip se monta sobre una canción, así que la música va "
            "antes que el video.",
            ir_a="songs",
            boton="Empezar una canción",
        )

    if not any(approval_rules.current_audio_path(c) for c in canciones):
        return _paso(
            "terminar_cancion",
            "Termina su canción",
            "Cuando tenga su audio generado se puede montar el videoclip encima.",
            ir_a="songs",
            boton="Ir a la canción",
        )

    proyectos = Repository(studio.db, uid, VIDEO_PROJECTS).list(limit=50)
    if not proyectos:
        return _paso(
            "videoclip",
            "Su primer videoclip",
            "Ya hay cara y canción con audio: es justo lo que hace falta "
            "para empezar a rodar.",
            ir_a="projects",
            boton="Montar el videoclip",
        )

    return _paso(
        "seguir",
        "Sigue produciendo",
        "Lo básico está: tiene cara, tiene música y tiene video. Desde aquí, "
        "más canciones y más videoclips.",
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
    # Leer la Bible tambien la pone al dia: la identidad toma sus datos de
    # las otras fichas (la edad, de los rasgos del artista), asi que un
    # universo creado antes de la sincronia se corrige solo al abrirla.
    bible = sync_bible_identity(studio.db, universe_id)
    datos = bible.model_dump()
    # Cada resumen viaja con su marca de utilizable, recalculada del
    # texto guardado en esta misma lectura (nunca guardada como dato ni
    # fiada al cliente): un resumen fabricado se ve como tal en la
    # ficha, y las puertas de prompt lo excluyen por la misma
    # comprobacion.
    datos["inspirations"] = [
        inspiration_service.con_marca(inspiracion) for inspiracion in bible.inspirations
    ]
    return {**datos, "summary": summarize_bible(bible)}


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
    # La marca de entrada: un envio que muere antes de crear el trabajo
    # no dejaba rastro en ninguna parte, y sin rastro no hay manera de
    # saber si la peticion llego siquiera. Con esta linea y la de
    # «job_created» en submit, los registros cuentan si llego, si creo
    # el trabajo y cual.
    logger.info(
        "generate_bible universe=%s idempotency_key=%s brief=%s",
        universe_id,
        "presente" if body.idempotency_key else "ausente",
        "presente" if body.brief else "vacio",
    )
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
    """Compatibilidad: ya no hay nada que aprobar.

    La identidad esta en uso tal cual esta escrita, y sus datos duplicados
    se sincronizan solos desde las otras fichas. Este endpoint devuelve la
    Bible vigente (ya sincronizada) sin tocar nada.
    """
    studio.orchestrator.require_universe(universe_id)
    return sync_bible_identity(studio.db, universe_id).model_dump()


class SingingVoiceIn(BaseModel):
    sex: str = ""
    apparent_age: str = ""
    pitch: str = ""
    timbre: str = ""
    language_accent: str = ""
    singing_style: str = ""


@router.put("/{universe_id}/bible/singing-voice")
def put_singing_voice(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: SingingVoiceIn
) -> dict[str, Any]:
    """La voz cantada del artista, como UN texto fijo.

    Las partes se componen en un solo texto y ese texto es el que viaja
    palabra por palabra en cada letra y en cada encargo a Lyria de este
    artista. Editarla solo cambia las canciones futuras: las ya generadas
    conservan la voz con la que salieron.
    """
    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    voz = SingingVoice(**body.model_dump())
    voz.text = artist_domain.compose_singing_voice(body.model_dump())
    bible.singing_voice = voz
    bible.voice_profile.lines = [linea for linea in voz.text.split("\n") if linea.strip()]
    save_bible(studio.db, universe_id, bible)
    return bible.singing_voice.model_dump()


class VisualStyleIn(BaseModel):
    style_key: str
    photo_style_description: str = ""


@router.put("/{universe_id}/bible/visual-style")
def put_visual_style(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: VisualStyleIn
) -> dict[str, Any]:
    """El estilo visual fijo del artista.

    Si cambia despues de generada la cara, la cara queda marcada como
    desactualizada: sigue ahi, pero hay que rehacerla en el estilo nuevo
    antes de rodar videos nuevos.
    """
    studio.orchestrator.require_universe(universe_id)
    if body.style_key not in artist_domain.VISUAL_STYLE_KEYS:
        raise InvalidGenerationRequest(
            "Ese estilo no esta en la lista. Elige uno de los estilos del artista."
        )
    bible = load_bible(studio.db, universe_id)
    cambio = bible.visual.style_key != body.style_key
    bible.visual.style_key = body.style_key
    bible.visual.style_label = artist_domain.visual_style_label(body.style_key)
    if body.photo_style_description:
        bible.visual.photo_style_description = body.photo_style_description
    repo = Repository(studio.db, universe_id, CHARACTERS)
    artista = next(
        (c for c in repo.list(limit=50) if c.get("role") == CharacterRole.LEAD.value), None
    )
    if (
        cambio
        and artista is not None
        and any(s.get("storage_path") for s in artista.get("master_shots") or [])
    ):
        bible.visual.master_stale = True
        repo.update(artista["id"], {"master_stale": True})
    save_bible(studio.db, universe_id, bible)
    return bible.visual.model_dump()


class GenresIn(BaseModel):
    music_genres: list[str] = Field(default_factory=list)
    music_genre_free: str = ""


@router.put("/{universe_id}/bible/genres")
def put_genres(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: GenresIn
) -> dict[str, Any]:
    """La combinacion de generos del artista: hasta tres principales mas su
    mezcla escrita. Cada cancion la hereda y puede ajustarla solo para ella."""
    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    bible.music_genres = [
        g for g in body.music_genres if g in artist_domain.MUSIC_GENRE_KEYS
    ][: artist_domain.MAX_MAIN_GENRES]
    bible.music_genre_free = body.music_genre_free
    if bible.music_genres:
        bible.musical.genre = artist_domain.genres_text(bible.music_genres)
    save_bible(studio.db, universe_id, bible)
    return {
        "music_genres": bible.music_genres,
        "music_genre_free": bible.music_genre_free,
        "genres_text": artist_domain.genres_text(bible.music_genres, bible.music_genre_free),
    }


class InspirationIn(BaseModel):
    url: str


class InspirationPatch(BaseModel):
    inspirations: list[Inspiration]


@router.post("/{universe_id}/bible/inspirations")
def add_inspiration(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: InspirationIn
) -> dict[str, Any]:
    """Pega un enlace de YouTube y la app lo analiza sola: guarda el resumen
    de su estilo, no la cancion. Ese resumen alimenta las canciones de este
    artista como inspiracion, con material siempre original."""
    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    inspiracion = inspiration_service.analyse_youtube(studio, body.url)
    bible.inspirations.append(inspiracion)
    # Si este enlace era de los que no se pudieron analizar al crear el
    # artista, ya no falta: sale de la lista visible de fallidos.
    video_id = inspiration_service.youtube_video_id(inspiracion.url)
    if video_id:
        bible.inspirations_failed = [
            enlace
            for enlace in bible.inspirations_failed
            if inspiration_service.youtube_video_id(enlace) != video_id
        ]
    save_bible(studio.db, universe_id, bible)
    return inspiration_service.con_marca(inspiracion)


@router.put("/{universe_id}/bible/inspirations")
def put_inspirations(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: InspirationPatch
) -> list[dict[str, Any]]:
    """El resumen es editable: lo que quede escrito aqui es lo que leen las
    canciones. Con un limite: la marca de utilizable no la pone el cliente,
    se recalcula del texto al guardar y al leer, asi que un resumen
    fabricado no puede re-guardarse como si fuera valido."""
    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    bible.inspirations = body.inspirations
    save_bible(studio.db, universe_id, bible)
    return [inspiration_service.con_marca(i) for i in bible.inspirations]


@router.delete("/{universe_id}/bible/inspirations/{indice}")
def delete_inspiration(
    owner: OwnerDep, studio: StudioDep, universe_id: str, indice: int
) -> dict[str, Any]:
    studio.orchestrator.require_universe(universe_id)
    bible = load_bible(studio.db, universe_id)
    if 0 <= indice < len(bible.inspirations):
        bible.inspirations.pop(indice)
        save_bible(studio.db, universe_id, bible)
    return {
        "inspirations": [
            inspiration_service.con_marca(i) for i in bible.inspirations
        ]
    }


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
