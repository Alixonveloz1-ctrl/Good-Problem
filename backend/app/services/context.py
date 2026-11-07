"""Assembling the context a generation runs with (PRD 42.4-42.6).

Before anything is generated the orchestrator recovers the Artist Bible, the
Canon and the reference images of everyone who appears in the shot. The
approved Character Master is what keeps the artist looking like the same person
across a whole video, so it travels with every request where that character
appears (PRD 18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..clock import now_iso
from ..db.client import Database
from ..db.repositories import CANON, CHARACTERS, Repository, doc_path
from ..domain import artist as artist_domain
from ..domain.enums import CanonStatus
from ..domain.schemas import ArtistBible
from .inspiration import inspiracion_utilizable

BIBLE_DOC = "artist_bible/current"


def bible_path(universe_id: str) -> str:
    return f"universes/{universe_id}/{BIBLE_DOC}"


def load_bible(db: Database, universe_id: str) -> ArtistBible:
    doc = db.get(bible_path(universe_id))
    if doc is None:
        return ArtistBible(id="current", universe_id=universe_id)
    return ArtistBible.model_validate(doc)


def save_bible(db: Database, universe_id: str, bible: ArtistBible) -> dict[str, Any]:
    # updated_at es un dato de la ESCRITURA, no del contenido: cada
    # guardado lo estampa. Antes el volcado conservaba el que trajera el
    # objeto —normalmente el del documento leido— y una Biblia cuyo
    # contenido habia cambiado varias veces (reescrituras, inspiraciones,
    # la sincronia de identidad) seguia ensenando la fecha de su creacion,
    # como si nunca se hubiera guardado: en produccion el documento de un
    # artista real quedo con updated_at == created_at tras un trabajo
    # READY que lo habia aplicado. created_at no se toca: es el del
    # documento y viaja en el propio modelo.
    bible.updated_at = now_iso()
    return db.set(bible_path(universe_id), bible.model_dump())


def sync_bible_identity(db: Database, universe_id: str) -> ArtistBible:
    """La identidad toma sus datos de las otras fichas, no se escribe a mano.

    Regla del estudio: cada dato vive en UNA ficha y las demas lo leen de
    ahi. La edad del artista vive en los rasgos de su ficha (la elige el
    usuario con el selector de edad exacta), asi que la edad aparente de la
    identidad —y la de la propia ficha del artista— se recalcula desde esos
    rasgos cada vez que se guardan y cada vez que se lee la Bible. Sin esto,
    el usuario puso 21 en los rasgos y la identidad siguio diciendo 29 para
    siempre, sin que nadie se enterara.

    Solo se sincroniza lo que tiene una correspondencia inequivoca:

    * ``identity.apparent_age`` <- ``rasgos["edad"]`` del artista, con el
      formato de la Bible («21 años»).
    * ``character.apparent_age`` <- el mismo valor, en la ficha del artista.

    Y deliberadamente NO se sincroniza:

    * ``identity.stage_name``: el nombre de la ficha puede ser el nombre
      real del personaje ficticio y el artistico lo escribe el Director;
      pisarlo desde la ficha podria borrar «K-Ronte» por otro nombre.
    * ``identity.origin`` / ``identity.languages``: no tienen fuente en
      ninguna otra ficha (los rasgos no traen origen ni idiomas); los
      escribe el Director y no hay nada con que sincronizarlos.
    * ``singing_voice.apparent_age``: es la edad que SE OYE en la voz, un
      dato artistico distinto de la edad de la persona, con su propio
      editor en la pantalla de Identidad.
    """
    bible = load_bible(db, universe_id)
    characters = Repository(db, universe_id, CHARACTERS).list(limit=50)
    lead = next(
        (c for c in characters if c.get("role") == "lead"),
        characters[0] if characters else None,
    )
    if lead is None:
        return bible
    edad = (lead.get("rasgos") or {}).get("edad")
    if edad is None or str(edad).strip() == "":
        return bible
    texto = str(edad).strip()
    aparente = texto if texto.endswith("años") else f"{texto} años"
    if lead.get("apparent_age") != aparente:
        Repository(db, universe_id, CHARACTERS).update(
            lead["id"], {"apparent_age": aparente}
        )
    if bible.identity.apparent_age != aparente:
        bible.identity.apparent_age = aparente
        save_bible(db, universe_id, bible)
    return bible


def summarize_bible(bible: ArtistBible, *, vista: str = "general") -> str:
    """A compact rendering that fits comfortably in a system instruction.

    ``vista`` adjusts the framing for one reading, without touching the data:

    * ``"concepto_cancion"`` (the song-concept call): the artist's themes are
      labelled as background identity — NOT the topic of this song — the
      genre combination loses its "(fixed)" label (usual ground, not a
      filter), and the artist's inspiration summaries are left out entirely:
      in that call the song's own reference travels in the prompt, first and
      with rank, and the artist summaries only duplicated it into noise.
    * ``"biblia_artista"`` (the Bible-generation call): the inspiration
      summaries are framed as CRAFT ONLY — technique, flow, metrics,
      structure, delivery and sound. What the reference songs SING ABOUT is
      never imported as the artist's recurring or lyric themes: an artist
      whose references sing about betrayal is not thereby an artist about
      betrayal.
    * ``"general"``: the plain rendering every other reader gets, including
      the Bible screen's own summary.
    """
    en_concepto = vista == "concepto_cancion"
    identity = bible.identity
    musical = bible.musical
    visual = bible.visual
    comms = bible.communication
    texto_generos = (
        artist_domain.genres_text(bible.music_genres, bible.music_genre_free)
        or musical.genre
    )
    if en_concepto:
        temas = (
            f"Recurring themes (background identity of the artist — NOT the "
            f"topic of this song unless the song's reference or the user's "
            f"idea asks for them): {', '.join(identity.recurring_themes)}"
        )
        temas_letra = (
            f"Lyric themes (background identity, same rule — not this song's "
            f"topic by default): {', '.join(musical.lyrical_themes)}"
        )
        generos = (
            "Genres (the artist's usual combination — background ground, "
            f"not a filter): {texto_generos} / {', '.join(musical.subgenres)}"
        )
    else:
        temas = f"Recurring themes: {', '.join(identity.recurring_themes)}"
        temas_letra = f"Lyric themes: {', '.join(musical.lyrical_themes)}"
        generos = (
            f"Genres (fixed combination): {texto_generos}"
            f" / {', '.join(musical.subgenres)}"
        )
    lines = [
        f"Stage name: {identity.stage_name or '(sin definir)'}",
        f"Apparent age: {identity.apparent_age}",
        f"Origin: {identity.origin}",
        f"Languages: {', '.join(identity.languages)}",
        f"Personality: {identity.personality}",
        f"Backstory: {identity.backstory}",
        f"Audience: {identity.target_audience}",
        temas,
        "",
        generos,
        f"BPM range: {musical.bpm_range}",
        f"Instrumentation: {', '.join(musical.instrumentation)}",
        f"Production: {musical.production}",
        f"Song structures: {', '.join(musical.structures)}",
        temas_letra,
        f"Lyrics language: {musical.language}",
        f"Mood: {musical.mood}",
        f"Vocal characteristics: {musical.vocal_characteristics}",
        "",
        f"Visual style (fixed): {visual.style_label or visual.style_key or '(sin elegir)'}",
        artist_domain.style_block(bible),
        f"Appearance: {visual.appearance}",
        f"Aesthetic: {visual.aesthetic}",
        f"Palette: {', '.join(visual.palette)}",
        f"Lighting: {visual.lighting}",
        f"Photography: {visual.photography}",
        f"Cinematography: {visual.cinematography}",
        f"Architecture: {visual.architecture}",
        f"Recurring motifs: {', '.join(visual.recurring_motifs)}",
        f"FORBIDDEN, never generate: {', '.join(visual.forbidden_elements) or '(nada)'}",
        "",
        f"Speech style: {comms.speech_style}",
        f"Humour: {comms.humour}",
        "",
        "SINGING VOICE (fixed text, include verbatim in every music prompt):",
        bible.singing_voice.text or bible.voice_profile.as_prompt() or "(sin definir)",
    ]
    if not en_concepto:
        for inspiracion in bible.inspirations:
            if not inspiracion.summary_text:
                continue
            # Un resumen fabricado (el que «vio» la pagina de error de
            # YouTube) no entra en ningun prompt, tampoco por esta puerta:
            # se queda en la ficha, marcado, hasta que se vuelva a pegar
            # el enlace y se analice de verdad.
            if not inspiracion_utilizable(inspiracion):
                continue
            lines.append("")
            if vista == "biblia_artista":
                lines.append(
                    "REFERENCE CRAFT (craft only: technique, flow, metrics, "
                    "song structure, delivery and sound. NEVER import what "
                    "this reference's lyrics are about: its themes and its "
                    "story are not the artist's themes):\n"
                    f"{inspiracion.summary_text}"
                )
            else:
                lines.append(
                    "REFERENCE INSPIRATION (style only; create original material, "
                    f"never copy lyrics or melody):\n{inspiracion.summary_text}"
                )
    return "\n".join(line for line in lines if line is not None)


def summarize_canon(db: Database, universe_id: str, *, limit: int = 40) -> str:
    entries = Repository(db, universe_id, CANON).list(limit=limit)
    if not entries:
        return ""
    return "\n".join(
        f"- {e.get('entity_type')}: {e.get('label') or e.get('entity_id')}"
        + (f" ({e['note']})" if e.get("note") else "")
        for e in entries
    )


@dataclass
class SceneContext:
    """Everything a scene generation needs, already resolved.

    Simplified studio: the only character is the artist. Location and
    wardrobe are text inside the scene itself (proposed in the storyboard),
    so the context is the artist's approved Master references plus the
    artist's fixed visual style.
    """

    characters: list[dict[str, Any]] = field(default_factory=list)
    reference_paths: list[str] = field(default_factory=list)
    unapproved_characters: list[str] = field(default_factory=list)
    style_prompt: str = ""

    def describe(self) -> str:
        parts = []
        for char in self.characters:
            parts.append(
                f"CHARACTER {char.get('name')}: {char.get('appearance')} "
                f"({char.get('apparent_age')})"
            )
        if self.style_prompt:
            parts.append(f"VISUAL STYLE (fixed for this artist): {self.style_prompt}")
        return "\n".join(parts)


def load_scene_context(
    db: Database,
    universe_id: str,
    *,
    character_ids: list[str],
    max_references: int = 3,
) -> SceneContext:
    ctx = SceneContext()
    for char_id in character_ids:
        doc = db.get(doc_path(universe_id, CHARACTERS, char_id))
        if doc is None:
            continue
        ctx.characters.append(doc)
        if doc.get("status") == CanonStatus.APPROVED.value:
            ctx.reference_paths.extend(doc.get("reference_image_paths") or [])
        else:
            ctx.unapproved_characters.append(doc.get("name") or char_id)
    ctx.style_prompt = artist_domain.visual_style_prompt(load_bible(db, universe_id))
    ctx.reference_paths = list(dict.fromkeys(ctx.reference_paths))[:max_references]
    return ctx
