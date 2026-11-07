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
from ..services.context import (
    load_bible,
    nombre_en_su_ficha,
    summarize_bible,
    summarize_canon,
)
from . import schemas_json as S
from .roles import TAREAS_DE_CANCION, system_instruction

TASK_ROLES: dict[str, CreativeRole] = {
    "artist_bible": CreativeRole.CREATIVE_DIRECTOR,
    "music_concept": CreativeRole.MUSIC_DIRECTOR,
    "lyrics": CreativeRole.MUSIC_DIRECTOR,
    "lyrics_analysis": CreativeRole.MUSIC_DIRECTOR,
    "video_concept": CreativeRole.DIRECTOR,
    "storyboard": CreativeRole.CINEMATOGRAPHER,
    "character": CreativeRole.CASTING_DIRECTOR,
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


def _fixed_music_blocks(payload: dict[str, Any], task: str = "") -> list[str]:
    """What is fixed for this artist and this song, handed to the Director as
    given: the singing voice text, the genre combination and the inspiration
    summaries. The handlers impose them again on the result, so a Director
    that paraphrases them has not changed anything that reaches Lyria.

    The song concept is the exception that the owner ordered: in that call
    the song's OWN reference goes first and with rank — it sets the form —
    the artist's inspiration summaries do not enter at all (they already
    shaped the artist; repeating them buried the song's reference), and the
    genre combination is presented as the artist's usual ground, not as
    "(fixed)": when the reference asks for another mix, the proposal follows
    the reference. The singing voice stays fixed in every task, verbatim.
    """
    blocks: list[str] = []
    if task == "music_concept":
        referencia = (payload.get("song_inspiration_text") or "").strip()
        if referencia:
            blocks.append(
                "THIS SONG'S REFERENCE — IT SETS THE FORM. Take from it the "
                "rhythm, the structure, the kind of lyrics, the kind of "
                "story and the mood: what made that song work. Build an "
                "ORIGINAL song with that form, sung in this artist's style "
                "and voice. This reference outranks the artist's background "
                f"themes and usual genres wherever they differ.\n{referencia}"
            )
    voz = (payload.get("singing_voice_text") or "").strip()
    if voz:
        blocks.append(
            "SINGING VOICE OF THIS ARTIST (fixed, include verbatim in the "
            f"music prompt, never reword it):\n{voz}"
        )
    generos = (payload.get("genres_text") or "").strip()
    if generos:
        if task == "music_concept":
            blocks.append(
                "GENRE COMBINATION (the artist's usual ground — the "
                "reference's mix wins wherever they differ): "
                f"{generos}"
            )
        else:
            blocks.append(f"GENRE COMBINATION (fixed): {generos}")
    if task != "music_concept":
        inspiracion = (payload.get("inspiration_text") or "").strip()
        if inspiracion:
            blocks.append(
                "REFERENCE INSPIRATION. Take the style, the kind of music and the "
                "way the lyrics are written. Create ORIGINAL lyrics and melody: "
                f"never copy the reference's lyrics or melody.\n{inspiracion}"
            )
    return blocks


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
        sections.append(
            "Rebuild it from the artist's own concept and life story and from "
            "the CRAFT of the references: the identity and the themes are the "
            "artist's, born of their own story — the references teach how the "
            "music is made, never what it is about. The decided facts of the "
            "artist and the current draft travel further down, each labelled "
            "as what it is."
        )
        if brief:
            sections.append(f"USER BRIEF\n{brief}")

    elif task == "music_concept":
        sections.append(
            "Develop a song concept for this artist: title, concept, hook, genre, BPM, mood, "
            "structure, production and vocal interpretation. Then write the prompt that will be "
            "sent to Lyria 3 Pro in US English, including the artist's singing voice "
            "description verbatim and the requested duration."
        )
        sections.extend(_fixed_music_blocks(payload, task))
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
        sections.extend(_fixed_music_blocks(payload, task))
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
            "Then write the Lyria 3 Pro prompt in US English including the artist's singing "
            "voice description verbatim."
        )
        sections.extend(_fixed_music_blocks(payload, task))
        sections.append(f"USER LYRICS\n{lyrics}")

    elif task == "video_concept":
        sections.append(
            "Propose the music video for this approved song: type, concept and story arc. "
            "The only character is the artist. Also write, as text inside this same proposal, "
            "the wardrobe the artist wears in the video (wardrobe_notes) and where it happens "
            "(location_notes): they are part of this proposal and are approved with the story, "
            "not separate sections of the studio."
        )
        sections.append(
            "The music sounds from second 0 and the artist is already on screen in the first "
            "shot, performing. A silent or empty opening is forbidden: nobody waits through a "
            "dead intro in a music video."
        )
        song = payload.get("song") or {}
        if song:
            sections.append(f"APPROVED SONG\n{_kv(song)}")
        if brief:
            sections.append(f"USER DIRECTION\n{brief}")

    elif task == "storyboard":
        seconds = int(payload.get("song_duration_seconds") or 150)
        blocks = max(1, -(-seconds // 8))
        planos = max(blocks * 2, -(-seconds // 4))
        sections.append(
            f"Build the storyboard. The song lasts {seconds} seconds, so plan about {blocks} "
            "scenes of exactly 8 seconds each. Veo only generates 4, 6 or 8 second clips and 8 is "
            "mandatory at 1080p and whenever reference images are used, which is always the case "
            "here, so every scene lasts 8 seconds."
        )
        sections.append(
            "Cut rhythm: the finished video must cut every 3 to 5 seconds, like a professional "
            f"music video, so plan about {planos} short shots (planos) in total. Each 8 second "
            "scene carries two or three planos: list them in the scene's planos field, and write "
            "the scene's video_prompt so it asks for those internal cuts explicitly, in order, "
            "with their framing (wide, medium, close-up, detail). A scene that sits in a single "
            "static framing for 8 seconds is a failed scene."
        )
        sections.append(
            "Second 0 rule: the music sounds from the first frame and the artist is already on "
            "screen in the first plano, performing the first line. No empty landscapes, no "
            "silent build-up, no titles before the artist appears."
        )
        sections.append(
            "The artist is the only character. Keep the same face, the same hair and the base "
            "wardrobe in every scene; each scene states its location (location_description) and "
            "what the artist wears in it (wardrobe_description) as text, following the "
            "wardrobe and location notes of the approved story."
        )
        sections.append(
            "Before proposing a new shot, look for one you can reuse: a repeated chorus, a "
            "location already on screen, a framing that works again. Set reuses_scene_index to "
            "the index of the scene being reused, or -1 when the shot has to be generated. "
            "Explain the reuse plan in notes, in Spanish."
        )
        for key in ("story", "characters", "wardrobe_notes", "location_notes", "lyrics"):
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


_OFICIO_NO_CONTENIDO = (
    "THE REFERENCES TEACH CRAFT, NOT CONTENT. The reference summaries in "
    "the Artist Bible describe how those songs are MADE — their technique, "
    "flow, metrics, structure, delivery and sound — and that craft is what "
    "this artist learned from them. What those songs SING ABOUT is not "
    "imported: never turn a reference song's lyric themes or story into "
    "this artist's recurring themes or lyric themes. The artist's themes "
    "come from the artist's own concept and brief above."
)


def _secciones_reescritura(studio, universe_id: str, bible) -> list[str]:
    """El encargo de reescribir la Biblia, en dos bloques rotulados.

    Primero lo que el artista ya ES: los datos decididos en sus propias
    fichas (su nombre, su sexo, los rasgos que el usuario eligio, su
    origen, su voz fija, sus generos, su estilo visual, sus elementos
    prohibidos). Se conservan porque son suyos, no porque el borrador los
    repita — y viajan aparte del borrador para que no se confundan con el.

    Despues, la version vigente ROTULADA COMO BORRADOR. Antes viajaba en
    la instruccion de sistema como canon («trátala como verdad de fondo»)
    y el Director la transcribia tal cual: el resumen que aqui se incluye
    es el mismo de siempre, con las referencias encuadradas como oficio,
    pero su sitio y su rotulo son otros.
    """
    from ..db.repositories import CHARACTERS, Repository, universe_path
    from ..domain import artist as artist_domain

    universo = studio.db.get(universe_path(universe_id)) or {}
    personajes = Repository(studio.db, universe_id, CHARACTERS).list(limit=50)
    protagonista = next(
        (c for c in personajes if c.get("role") == "lead"),
        personajes[0] if personajes else {},
    )
    lineas = [
        "THE ARTIST, AS DECIDED. These facts are set in the artist's own "
        "sheets; keep them exactly. They stay because they are the "
        "artist's, not because the draft below repeats them."
    ]
    # El nombre artistico sale de la FICHA del personaje primero: es su
    # casa — ahi se escribe, en su campo, y de ahi lo toma la identidad
    # (sync_bible_identity). El guardado en la Biblia es el recurso
    # cuando la ficha aun no tiene un nombre de verdad: recien creado el
    # artista, la ficha lleva el nombre del formulario de creacion (el
    # del universo) y el unico nombre de artista que existe es el que el
    # Director escribio en la primera Biblia — que la ficha adopta en
    # cuanto la Biblia se lee o se aplica (la adopcion vive en la
    # sincronia). 4321e98 lo dejo al reves, guardado primero, y eso
    # congelaba cualquier nombre mal guardado: el de «Verso Oscuro»
    # pisando a «K-Ronte» se volvia la fuente y la ficha corregida
    # nunca llegaba al encargo. El nombre del universo viaja aparte,
    # rotulado como lo que es: el proyecto, no el artista.
    nombre = (
        nombre_en_su_ficha(studio.db, universe_id)
        or bible.identity.stage_name
        or protagonista.get("name")
    )
    if nombre:
        lineas.append(f"Stage name: {nombre}")
        lineas.append(
            "That is the artist's name, decided by the user. The "
            "Director never renames the artist."
        )
    if universo.get("name"):
        lineas.append(
            f"Universe: {universo['name']} — the project this artist "
            "belongs to. The universe's name is NOT the artist's name."
        )
    if universo.get("tagline"):
        lineas.append(f"The universe in one line: {universo['tagline']}")
    if protagonista.get("gender"):
        lineas.append(f"Gender: {protagonista['gender']}")
    for clave, valor in (protagonista.get("rasgos") or {}).items():
        if valor not in (None, "", []):
            lineas.append(f"Chosen trait ({clave}): {valor}")
    if bible.identity.origin:
        lineas.append(f"Origin: {bible.identity.origin}")
    if bible.identity.languages:
        lineas.append(f"Languages: {', '.join(bible.identity.languages)}")
    generos = artist_domain.genres_text(
        bible.music_genres, bible.music_genre_free
    )
    if generos:
        lineas.append(
            f"Genre combination chosen on the artist's sheet: {generos}"
        )
        lineas.append(
            "In the musical identity you write, the genre field holds "
            "only the short label of the artist's main genre (e.g. "
            "'Rap / hip-hop') — never the full combination above and "
            "never the free-text mix."
        )
    voz = (bible.singing_voice.text or "").strip() or bible.voice_profile.as_prompt()
    if voz:
        lineas.append(f"Fixed singing voice (verbatim — it is the artist's voice):\n{voz}")
    estilo = bible.visual.style_label or bible.visual.style_key
    if estilo:
        lineas.append(f"Visual style (fixed, chosen by the user): {estilo}")
    if bible.visual.forbidden_elements:
        lineas.append(
            "Forbidden elements (the user's own limits for what gets "
            "generated — carry them over unchanged): "
            + ", ".join(bible.visual.forbidden_elements)
        )
    borrador = (
        "CURRENT VERSION TO REWRITE. This is the Bible as it stands today: "
        "a draft, not the truth. Rebuild it from the artist above and the "
        "brief — rewrite the wording, rethink the themes from the artist's "
        "own story, and keep only what still earns its place. Do not "
        "transcribe it back.\n" + summarize_bible(bible, vista="biblia_artista")
    )
    return ["\n".join(lineas), borrador]


def run(studio, universe_id: str, model_id: str, payload: dict[str, Any]):
    """Execute one Director task and return the raw TextResult."""
    task = payload.get("task", "")
    if task not in TASK_SCHEMAS:
        raise InvalidGenerationRequest(f"Tarea de Director desconocida: '{task}'.")
    bible = load_bible(studio.db, universe_id)
    if task == "artist_bible":
        # La reescritura es su propio reparto: la Biblia vigente NO viaja
        # en la instruccion de sistema como canon (ahi el Director la
        # transcribia), sino en el prompt, rotulada como borrador, junto a
        # los datos que el artista ya ES. Sin resumen de Biblia y sin
        # canon en la instruccion: nada que «respetar» palabra por palabra.
        instruction = system_instruction(
            TASK_ROLES[task],
            reescritura_biblia=True,
        )
        prompt = build_prompt(task, payload)
        prompt = "\n\n".join(
            [prompt, *_secciones_reescritura(studio, universe_id, bible)]
        )
        if bible.inspirations:
            prompt = f"{prompt}\n\n{_OFICIO_NO_CONTENIDO}"
        return gemini_text.generate(
            studio.vertex,
            model_id,
            system_instruction=instruction,
            prompt=prompt,
            schema=TASK_SCHEMAS[task],
            temperature=float(payload.get("temperature", 0.9)),
        )
    # Each task reads the Bible with the framing its job needs: the song
    # concept gets background-labelled themes and no artist inspirations,
    # and the song tasks swap the censorship block for the reference/Bible
    # split. Every other task gets the Bible as canon, as before.
    vista = "concepto_cancion" if task == "music_concept" else "general"
    instruction = system_instruction(
        TASK_ROLES[task],
        bible_summary=summarize_bible(bible, vista=vista),
        canon=summarize_canon(studio.db, universe_id),
        reparto_canciones=task in TAREAS_DE_CANCION,
    )
    prompt = build_prompt(task, payload)
    return gemini_text.generate(
        studio.vertex,
        model_id,
        system_instruction=instruction,
        prompt=prompt,
        schema=TASK_SCHEMAS[task],
        temperature=float(payload.get("temperature", 0.9)),
    )
