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

from ..db.client import Database
from ..db.repositories import CANON, CHARACTERS, Repository, doc_path
from ..domain import artist as artist_domain
from ..domain.enums import CanonStatus
from ..domain.schemas import ArtistBible

BIBLE_DOC = "artist_bible/current"


def bible_path(universe_id: str) -> str:
    return f"universes/{universe_id}/{BIBLE_DOC}"


def load_bible(db: Database, universe_id: str) -> ArtistBible:
    doc = db.get(bible_path(universe_id))
    if doc is None:
        return ArtistBible(id="current", universe_id=universe_id)
    return ArtistBible.model_validate(doc)


def save_bible(db: Database, universe_id: str, bible: ArtistBible) -> dict[str, Any]:
    return db.set(bible_path(universe_id), bible.model_dump())


def summarize_bible(bible: ArtistBible) -> str:
    """A compact rendering that fits comfortably in a system instruction."""
    identity = bible.identity
    musical = bible.musical
    visual = bible.visual
    comms = bible.communication
    lines = [
        f"Stage name: {identity.stage_name or '(sin definir)'}",
        f"Apparent age: {identity.apparent_age}",
        f"Origin: {identity.origin}",
        f"Languages: {', '.join(identity.languages)}",
        f"Personality: {identity.personality}",
        f"Backstory: {identity.backstory}",
        f"Audience: {identity.target_audience}",
        f"Recurring themes: {', '.join(identity.recurring_themes)}",
        "",
        f"Genres (fixed combination): "
        f"{artist_domain.genres_text(bible.music_genres, bible.music_genre_free) or musical.genre}"
        f" / {', '.join(musical.subgenres)}",
        f"BPM range: {musical.bpm_range}",
        f"Instrumentation: {', '.join(musical.instrumentation)}",
        f"Production: {musical.production}",
        f"Song structures: {', '.join(musical.structures)}",
        f"Lyric themes: {', '.join(musical.lyrical_themes)}",
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
    for inspiracion in bible.inspirations:
        if inspiracion.summary_text:
            lines.append("")
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
