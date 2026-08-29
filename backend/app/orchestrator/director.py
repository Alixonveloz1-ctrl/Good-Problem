"""The Director's text tasks (PRD 11, 12, 13, 21, 22, 23, 33, 35).

Each task builds a prompt out of the Artist Bible, the Canon and whatever the
user supplied, asks Gemini for a structured proposal, and writes it into the
target entity as DRAFT. Nothing here approves anything.

The Director proposes; if the user changes the genre from ballad to hip hop, the
next call receives that change as an override and rebuilds the proposal from it
(PRD 11).
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import CreativeRole
from ..errors import InvalidGenerationRequest
from ..providers import gemini_text
from ..services.context import load_bible, summarize_bible, summarize_canon
from . import schemas_json as S
from .roles import system_instruction

TASK_ROLES: dict[str, CreativeRole] = {
    "artist_bible": CreativeRole.CREATIVE_DIRECTOR,
    "music_concept": CreativeRole.MUSIC_DIRECTOR,
    "lyrics": CreativeRole.MUSIC_DIRECTOR,
    "lyrics_analysis": CreativeRole.MUSIC_DIRECTOR,
    "video_concept": CreativeRole.DIRECTOR,
    "storyboard": CreativeRole.CINEMATOGRAPHER,
    "character": CreativeRole.CASTING_DIRECTOR,
    "wardrobe_set": CreativeRole.CREATIVE_DIRECTOR,
    "location_set": CreativeRole.CREATIVE_DIRECTOR,
    "cast_set": CreativeRole.CASTING_DIRECTOR,
    "content_script": CreativeRole.DIRECTOR,
    "interview": CreativeRole.DIRECTOR,
    "edit_plan": CreativeRole.EDITOR,
}

TASK_SCHEMAS: dict[str, dict[str, Any]] = {
    "artist_bible": S.ARTIST_BIBLE_SCHEMA,
    "music_concept": S.MUSIC_CONCEPT_SCHEMA,
    "lyrics": S.LYRICS_SCHEMA,
    "lyrics_analysis": S.LYRICS_ANALYSIS_SCHEMA,
    "video_concept": S.VIDEO_CONCEPT_SCHEMA,
    "storyboard": S.STORYBOARD_SCHEMA,
    "character": S.CHARACTER_SCHEMA,
    "wardrobe_set": S.WARDROBE_SET_SCHEMA,
    "location_set": S.LOCATION_SET_SCHEMA,
    "cast_set": S.CAST_SET_SCHEMA,
    "content_script": S.CONTENT_SCHEMA,
    "interview": S.INTERVIEW_SCHEMA,
    "edit_plan": S.EDIT_PLAN_SCHEMA,
}


def _overrides_block(overrides: dict[str, Any]) -> str:
    """What the user changed by hand. It wins over anything proposed before."""
    if not overrides:
        return ""
    lines = [f"- {key}: {value}" for key, value in overrides.items() if value not in (None, "", [])]
    if not lines:
        return ""
    return (
        "USER OVERRIDES. The user changed these by hand. Rebuild the proposal from them; "
        "do not argue them back.\n" + "\n".join(lines)
    )


def build_prompt(task: str, payload: dict[str, Any]) -> str:
    overrides = _overrides_block(payload.get("overrides") or {})
    brief = (payload.get("brief") or "").strip()
    sections: list[str] = []

    if task == "artist_bible":
        sections.append(
            "Build a complete Artist Bible for a virtual music artist. "
            "Fill every field. Be specific enough that two different generations "
            "of the same character would look like the same person."
        )
        if brief:
            sections.append(f"USER BRIEF\n{brief}")

    elif task == "music_concept":
        sections.append(
            "Develop a song concept for this artist: title, concept, hook, genre, BPM, mood, "
            "structure, production and vocal interpretation. Then write the prompt that will be "
            "sent to Lyria 3 Pro in US English, including the artist's Voice Profile verbatim and "
            "the requested duration."
        )
        if brief:
            sections.append(f"USER IDEA\n{brief}")
        duration = payload.get("duration_seconds")
        if duration:
            sections.append(f"Requested song duration: {duration} seconds (Lyria 3 Pro, max 180).")

    elif task == "lyrics":
        sections.append(
            "Write the full lyrics for this song. Mark sections in square brackets, "
            "e.g. [Verse 1], [Chorus]. Keep the hook intact."
        )
        concept = payload.get("concept") or {}
        if concept:
            sections.append(f"APPROVED CONCEPT\n{_kv(concept)}")

    elif task == "lyrics_analysis":
        lyrics = (payload.get("lyrics") or "").strip()
        if not lyrics:
            raise InvalidGenerationRequest("No hay letra que analizar.")
        sections.append(
            "The user supplied these lyrics. Analyse theme and structure, detect the hooks, and "
            "propose genre, BPM, vocal interpretation and production. Do NOT rewrite the lyrics. "
            "Then write the Lyria 3 Pro prompt in US English including the Voice Profile verbatim."
        )
        sections.append(f"USER LYRICS\n{lyrics}")

    elif task == "video_concept":
        sections.append(
            "Propose the music video for this approved song: type, concept and story arc. "
            "List the characters, locations and wardrobe the production actually needs, and only "
            "those. Reuse what already exists in the Canon before asking for anything new."
        )
        song = payload.get("song") or {}
        if song:
            sections.append(f"APPROVED SONG\n{_kv(song)}")
        if brief:
            sections.append(f"USER DIRECTION\n{brief}")

    elif task == "storyboard":
        seconds = int(payload.get("song_duration_seconds") or 150)
        blocks = max(1, -(-seconds // 8))
        sections.append(
            f"Build the storyboard. The song lasts {seconds} seconds, so plan about {blocks} "
            "scenes of exactly 8 seconds each. Veo only generates 4, 6 or 8 second clips and 8 is "
            "mandatory at 1080p and whenever reference images are used, which is always the case "
            "here, so every scene lasts 8 seconds."
        )
        sections.append(
            "Before proposing a new shot, look for one you can reuse: a repeated chorus, a "
            "location already on screen, a framing that works again. Set reuses_scene_index to "
            "the index of the scene being reused, or -1 when the shot has to be generated. "
            "Explain the reuse plan in notes, in Spanish."
        )
        for key in ("story", "characters", "locations", "wardrobe", "lyrics"):
            value = payload.get(key)
            if value:
                sections.append(f"{key.upper()}\n{_kv(value)}")

    elif task == "character":
        sections.append(
            "Define a character for this production and write the prompts for the Character "
            "Master shots: portrait, full body, profile, three-quarter, neutral expression, "
            "emotional expressions and relevant poses. The prompts go to a Gemini image model in "
            "US English and must describe the same person every time."
        )
        # Lo que el usuario ya decidio no se propone: se obedece. Sin esto, el
        # Director devolvia otro nombre y otro sexo -"Feri" entraba y salia
        # "Leo Castillo"- y lo que el usuario habia escrito desaparecia.
        fijo = payload.get("locked") or {}
        if fijo:
            sections.append(
                "THESE ARE GIVEN, NOT YOURS TO CHOOSE. The user decided them. Use every one "
                "of them exactly as written, in the description and in every single image "
                "prompt. Never rename, never change the gender, never swap a chosen trait "
                "for one you like better, never propose an alternative:\n" + _kv(fijo) +
                "\n\nWhatever is NOT listed above is yours to decide, and you must decide it: "
                "the description has to be precise enough that two separate generations look "
                "like the same person."
            )
        if brief:
            sections.append(f"WHAT THE PRODUCTION NEEDS\n{brief}")

    elif task == "wardrobe_set":
        cuantos = int(payload.get("count") or 4)
        sections.append(
            f"Propose {cuantos} outfits that this artist would actually wear, as their stylist "
            "would build a wardrobe: one signature look that reads as theirs on sight, and the "
            "rest covering what the year needs -stage, video, interview, off duty. Each one "
            "coherent with the artist's identity, era and genre, and distinct from the others. "
            "Name them the way a wardrobe department does, short and recognisable."
        )
        if brief:
            sections.append(f"USER DIRECTION\n{brief}")

    elif task == "location_set":
        cuantos = int(payload.get("count") or 4)
        sections.append(
            f"Propose {cuantos} locations where this artist's videos happen. Places that belong "
            "to this artist's world, not a stock list: somewhere intimate, somewhere with scale, "
            "somewhere that says where they are from. Say what is seen, the light and the time "
            "of day, concretely enough to shoot."
        )
        if brief:
            sections.append(f"USER DIRECTION\n{brief}")

    elif task == "cast_set":
        cuantos = int(payload.get("count") or 3)
        sections.append(
            f"Propose {cuantos} secondary characters around this artist -the people who appear "
            "in their videos and their story. Not extras: each one with a reason to be there and "
            "a relation to the artist. Describe each face precisely enough that two separate "
            "generations look like the same person."
        )
        principal = payload.get("lead") or {}
        if principal:
            sections.append(f"THE ARTIST THEY ORBIT\n{_kv(principal)}")
        if brief:
            sections.append(f"USER DIRECTION\n{brief}")

    elif task == "content_script":
        kind = payload.get("content_kind", "short")
        sections.append(
            f"Write a {kind} for this artist. Give the on screen script and the exact spoken text "
            "for the cloned voice, in Spanish, plus one video prompt in US English. "
            "The video is generated without audio; the voice is added in the edit."
        )
        if brief:
            sections.append(f"USER DIRECTION\n{brief}")

    elif task == "edit_plan":
        escenas = payload.get("scenes") or []
        sections.append(
            "Decide how this music video is cut. For every join between two consecutive shots, "
            "choose one of: cut (hard cut, the default in a music video), fade (crossfade), "
            "fadeblack (through black, for a break in time or place) or dissolve (slow, for a "
            "dreamy or reflective passage)."
        )
        sections.append(
            f"There are {len(escenas)} shots, so there are {max(len(escenas) - 1, 0)} joins to "
            "decide, one after each shot except the last. Index them by the shot they follow."
        )
        sections.append(
            "Most joins in a music video are hard cuts. Use a soft transition only where the "
            "music or the story asks for it: a change of place, a passage of time, the end of a "
            "section. Do not decorate. A crossfade lasts between 0.25 and 1 second, and every "
            "one of them makes the picture shorter than the song, so they are not free."
        )
        for key in ("song", "story"):
            value = payload.get(key)
            if value:
                sections.append(f"{key.upper()}\n{_kv(value)}")
        if escenas:
            sections.append("SHOTS\n" + _kv(escenas))

    elif task == "interview":
        sections.append(
            "Write a short interview with this artist. The personality comes from the Artist "
            "Bible. Questions and answers in Spanish. Then join the answers into spoken_text, "
            "ready for the cloned voice."
        )
        if brief:
            sections.append(f"ANGLE\n{brief}")

    else:
        raise InvalidGenerationRequest(f"Tarea de Director desconocida: '{task}'.")

    if overrides:
        sections.append(overrides)
    return "\n\n".join(sections)


def _kv(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        return "\n".join(
            f"{pad}{k}: {_kv(v, indent + 1).lstrip() if isinstance(v, dict | list) else v}"
            for k, v in value.items()
            if v not in (None, "", [], {})
        )
    if isinstance(value, list):
        return "\n".join(f"{pad}- {_kv(v, indent + 1).lstrip()}" for v in value)
    return f"{pad}{value}"


def run(studio, universe_id: str, model_id: str, payload: dict[str, Any]):
    """Execute one Director task and return the raw TextResult."""
    task = payload.get("task", "")
    if task not in TASK_SCHEMAS:
        raise InvalidGenerationRequest(f"Tarea de Director desconocida: '{task}'.")
    bible = load_bible(studio.db, universe_id)
    instruction = system_instruction(
        TASK_ROLES[task],
        bible_summary=summarize_bible(bible),
        canon=summarize_canon(studio.db, universe_id),
    )
    return gemini_text.generate(
        studio.vertex,
        model_id,
        system_instruction=instruction,
        prompt=build_prompt(task, payload),
        schema=TASK_SCHEMAS[task],
        temperature=float(payload.get("temperature", 0.9)),
    )
