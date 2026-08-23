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
from ..db.repositories import CANON, CHARACTERS, LOCATIONS, WARDROBE, Repository, doc_path
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
        f"Genre: {musical.genre} / {', '.join(musical.subgenres)}",
        f"BPM range: {musical.bpm_range}",
        f"Instrumentation: {', '.join(musical.instrumentation)}",
        f"Production: {musical.production}",
        f"Song structures: {', '.join(musical.structures)}",
        f"Lyric themes: {', '.join(musical.lyrical_themes)}",
        f"Lyrics language: {musical.language}",
        f"Mood: {musical.mood}",
        f"Vocal characteristics: {musical.vocal_characteristics}",
        "",
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
        f"Interview style: {comms.interview_style}",
        "",
        "VOICE PROFILE (include verbatim in every music prompt):",
        bible.voice_profile.as_prompt() or "(sin definir)",
    ]
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
    """Everything a scene generation needs, already resolved."""

    characters: list[dict[str, Any]] = field(default_factory=list)
    location: dict[str, Any] | None = None
    outfits: list[dict[str, Any]] = field(default_factory=list)
    reference_paths: list[str] = field(default_factory=list)
    unapproved_characters: list[str] = field(default_factory=list)

    def describe(self) -> str:
        parts = []
        for char in self.characters:
            parts.append(
                f"CHARACTER {char.get('name')}: {char.get('appearance')} "
                f"({char.get('apparent_age')})"
            )
        if self.location:
            parts.append(
                f"LOCATION {self.location.get('name')}: {self.location.get('description')}; "
                f"lighting {self.location.get('lighting')}; {self.location.get('time_of_day')}"
            )
        for outfit in self.outfits:
            parts.append(f"WARDROBE {outfit.get('name')}: {outfit.get('description')}")
        return "\n".join(parts)


def load_scene_context(
    db: Database,
    universe_id: str,
    *,
    character_ids: list[str],
    location_id: str | None,
    wardrobe_ids: list[str],
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
    if location_id:
        ctx.location = db.get(doc_path(universe_id, LOCATIONS, location_id))
        if ctx.location and ctx.location.get("status") == CanonStatus.APPROVED.value:
            ctx.reference_paths.extend((ctx.location.get("reference_paths") or [])[:1])
    for outfit_id in wardrobe_ids:
        doc = db.get(doc_path(universe_id, WARDROBE, outfit_id))
        if doc is None:
            continue
        ctx.outfits.append(doc)
        if doc.get("status") == CanonStatus.APPROVED.value and doc.get("image_path"):
            ctx.reference_paths.append(doc["image_path"])
    # Keep the most identity-bearing references first: characters, then place.
    ctx.reference_paths = list(dict.fromkeys(ctx.reference_paths))[:max_references]
    return ctx
