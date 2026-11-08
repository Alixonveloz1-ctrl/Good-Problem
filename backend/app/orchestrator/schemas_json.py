"""Response schemas handed to Gemini so proposals come back structured.

Vertex uses the OpenAPI subset, so types are upper case strings.
"""

from __future__ import annotations

from typing import Any


def _str(description: str = "") -> dict[str, Any]:
    return {"type": "STRING", "description": description} if description else {"type": "STRING"}


def _arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ARRAY", "items": items}


MUSIC_CONCEPT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _str("Titulo de la cancion, en el idioma del artista"),
        "concept": _str("Dos o tres frases en espanol"),
        "hook": _str("El gancho, tal y como se cantaria"),
        "genre": _str(),
        "bpm": {"type": "INTEGER"},
        "mood": _str(),
        "structure": _arr(_str("Ej. Intro, Verse 1, Pre-chorus, Chorus")),
        "production": _str("Como suena la produccion, en espanol"),
        "interpretation": _str("Como se canta, en espanol"),
        "visual_concept": _str("Idea visual asociada, en espanol"),
        "music_prompt": _str("Prompt para Lyria 3 Pro, en ingles de Estados Unidos"),
    },
    "required": ["title", "concept", "hook", "genre", "bpm", "structure", "music_prompt"],
}

LYRICS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _str(),
        "lyrics": _str("Letra completa con marcas de seccion entre corchetes"),
        "notes": _str("Que se busco con la letra, en espanol"),
    },
    "required": ["lyrics"],
}

LYRICS_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "theme": _str(),
        "structure": _arr(_str()),
        "hooks": _arr(_str()),
        "proposed_genre": _str(),
        "proposed_bpm": {"type": "INTEGER"},
        "proposed_interpretation": _str(),
        "proposed_production": _str(),
        "music_prompt": _str("Prompt para Lyria 3 Pro, en ingles de Estados Unidos"),
        "summary": _str("La propuesta explicada al usuario, en espanol"),
    },
    "required": ["theme", "proposed_genre", "music_prompt", "summary"],
}

VIDEO_CONCEPT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _str(),
        "video_type": {
            "type": "STRING",
            "enum": ["performance", "narrative", "cinematic", "minimal", "hybrid"],
        },
        "concept": _str("En espanol"),
        "story": {
            "type": "OBJECT",
            "properties": {
                "premise": _str(),
                "beginning": _str(),
                "development": _str(),
                "conflict": _str(),
                "climax": _str(),
                "resolution": _str(),
            },
        },
        "wardrobe_notes": _str(
            "El vestuario del artista en este video, en espanol: que lleva en "
            "cada tramo y por que. Es texto de la propuesta, no una seccion aparte."
        ),
        "location_notes": _str(
            "Donde ocurre este video, en espanol: los sitios, su luz y su "
            "momento del dia. Es texto de la propuesta, no una seccion aparte."
        ),
    },
    "required": ["title", "video_type", "concept", "story"],
}

STORYBOARD_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "scenes": _arr(
            {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "duration_seconds": {"type": "INTEGER", "enum": [8]},
                    "song_timestamp": _str("mm:ss-mm:ss"),
                    "character_names": _arr(_str()),
                    "location_description": _str(
                        "Donde ocurre el plano, en espanol, con su luz"
                    ),
                    "wardrobe_description": _str(
                        "Que lleva puesto el artista en este plano, en espanol"
                    ),
                    "planos": _arr(
                        _str(
                            "Un plano corto dentro del bloque, en espanol: "
                            "encuadre y accion. Dos o tres por bloque."
                        )
                    ),
                    "action": _str("En espanol"),
                    "emotion": _str(),
                    "camera": _str(),
                    "lighting": _str(),
                    "environment": _str(),
                    "dialogue": _str(),
                    "visual_objective": _str(),
                    "reuses_scene_index": {
                        "type": "INTEGER",
                        "description": "-1 si la toma se genera nueva",
                    },
                    "reuse_note": _str("Por que se puede reaprovechar"),
                    "image_prompt": _str("Prompt de imagen, en ingles de Estados Unidos"),
                    "video_prompt": _str("Prompt de video, en ingles de Estados Unidos"),
                },
                "required": ["index", "action", "camera", "image_prompt", "video_prompt"],
            }
        ),
        "notes": _str("Como se organizo la reutilizacion de tomas, en espanol"),
    },
    "required": ["scenes"],
}

CHARACTER_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "name": _str(),
        "apparent_age": _str(),
        "appearance": _str("Descripcion fisica detallada, en espanol"),
        "personality": _str(),
        "master_prompts": _arr(
            {
                "type": "OBJECT",
                "properties": {
                    "key": {
                        "type": "STRING",
                        "enum": [
                            "portrait",
                            "full_body",
                            "profile",
                            "three_quarter",
                            "neutral",
                            "emotions",
                            "poses",
                        ],
                    },
                    "prompt": _str("En ingles de Estados Unidos"),
                },
                "required": ["key", "prompt"],
            }
        ),
    },
    "required": ["name", "appearance", "master_prompts"],
}

ARTIST_BIBLE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "identity": {
            "type": "OBJECT",
            "properties": {
                "stage_name": _str(),
                "fictional_name": _str(),
                "apparent_age": _str(),
                "origin": _str(),
                "languages": _arr(_str()),
                "personality": _str(),
                "backstory": _str(),
                "target_audience": _str(),
                "recurring_themes": _arr(_str()),
            },
        },
        "musical": {
            "type": "OBJECT",
            "properties": {
                "genre": _str(),
                "subgenres": _arr(_str()),
                "bpm_range": _str(),
                "instrumentation": _arr(_str()),
                "production": _str(),
                "structures": _arr(_str()),
                "lyrical_themes": _arr(_str()),
                "language": _str(),
                "mood": _str(),
                "vocal_characteristics": _str(),
            },
        },
        "visual": {
            "type": "OBJECT",
            "properties": {
                "appearance": _str(),
                "aesthetic": _str(),
                "palette": _arr(_str()),
                "lighting": _str(),
                "photography": _str(),
                "cinematography": _str(),
                "architecture": _str(),
                "settings": _arr(_str()),
                "recurring_motifs": _arr(_str()),
                "forbidden_elements": _arr(_str()),
            },
        },
        "communication": {
            "type": "OBJECT",
            "properties": {
                "speech_style": _str(),
                "humour": _str(),
                "catchphrases": _arr(_str()),
                "interview_style": _str(),
                "recurring_topics": _arr(_str()),
            },
        },
        "voice_profile_lines": _arr(_str("Una caracteristica vocal por linea, en ingles")),
    },
    "required": ["identity", "musical", "visual"],
}


EDIT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "cuts": _arr(
            {
                "type": "OBJECT",
                "properties": {
                    "after_scene_index": {
                        "type": "INTEGER",
                        "description": "El corte que va DESPUES de esta escena",
                    },
                    "type": {
                        "type": "STRING",
                        "enum": ["cut", "fade", "fadeblack", "dissolve"],
                        "description": (
                            "cut: corte seco. fade: fundido encadenado. "
                            "fadeblack: pasa por negro. dissolve: disolvencia lenta."
                        ),
                    },
                    "seconds": {
                        "type": "NUMBER",
                        "description": "Duracion del fundido, entre 0,25 y 1. Se ignora en cut.",
                    },
                    "why": _str("Por que ese corte y no otro, en espanol y en una linea"),
                },
                "required": ["after_scene_index", "type"],
            }
        ),
        "notes": _str("Como se ha montado el videoclip, en espanol, en dos o tres frases"),
    },
    "required": ["cuts"],
}






# --- Inspiration and photo style (simplified studio) ------------------------

# ``title`` es obligatorio a proposito: un analisis que no nombra el video
# que vio no es un analisis del video. Cuando era opcional, una respuesta
# sin titulo (o con el titulo de la pagina de error de YouTube) pasaba el
# esquema y se guardaba como resumen «valido»; sin titulo, ahora es un
# error de esquema en vez de un resumen.
INSPIRATION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _str("Titulo del video analizado"),
        "genres": _str("Generos y mezcla que se oyen, en espanol"),
        "genre_keys": _arr(
            _str(
                "Una clave del catalogo fijo de generos de la app, escrita "
                "exactamente como viene en la instruccion"
            )
        ),
        "rhythm": _str("Ritmo, velocidad y sensacion, en espanol"),
        "instruments": _arr(_str("Un instrumento dominante por elemento")),
        "structure": _str("Estructura: verso, coro, puente..., en espanol"),
        "mood": _str("Ambiente, en espanol"),
        "lyric_themes": _arr(_str("Un tema de la letra por elemento")),
        "lyric_style": _str("Manera de escribir la letra, en espanol"),
    },
    "required": ["title", "genres", "rhythm", "structure"],
}

PHOTO_STYLE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "style_description": _str(
            "The visual style of the photo as one prompt-ready description in "
            "US English: medium (photograph, anime, oil painting...), rendering, "
            "lighting, palette and finish. No mention of who the person is."
        ),
        "medium": _str("photograph, anime, oil painting, 3D render..."),
        "palette": _str("Dominant colours, in US English"),
        "lighting": _str("Lighting, in US English"),
    },
    "required": ["style_description"],
}
