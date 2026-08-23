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
        "needed_characters": _arr(
            {
                "type": "OBJECT",
                "properties": {
                    "name": _str(),
                    "apparent_age": _str(),
                    "appearance": _str(),
                    "personality": _str(),
                    "why": _str("Por que la produccion lo necesita"),
                },
                "required": ["name", "appearance"],
            }
        ),
        "needed_locations": _arr(
            {
                "type": "OBJECT",
                "properties": {
                    "name": _str(),
                    "description": _str(),
                    "lighting": _str(),
                    "time_of_day": _str(),
                    "mood": _str(),
                },
                "required": ["name", "description"],
            }
        ),
        "needed_wardrobe": _arr(
            {
                "type": "OBJECT",
                "properties": {
                    "name": _str(),
                    "category": _str(),
                    "description": _str(),
                },
                "required": ["name"],
            }
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
                    "location_name": _str(),
                    "wardrobe_names": _arr(_str()),
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

CONTENT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _str(),
        "script": _str("Lo que se dice o se lee en pantalla, en espanol"),
        "spoken_text": _str("Texto exacto para Chirp, en espanol"),
        "shot_notes": _arr(_str()),
        "video_prompt": _str("En ingles de Estados Unidos"),
    },
    "required": ["title", "script"],
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

INTERVIEW_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _str(),
        "exchanges": _arr(
            {
                "type": "OBJECT",
                "properties": {"question": _str(), "answer": _str()},
                "required": ["question", "answer"],
            }
        ),
        "spoken_text": _str("Las respuestas encadenadas, listas para Chirp"),
    },
    "required": ["title", "exchanges"],
}
