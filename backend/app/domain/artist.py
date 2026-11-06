"""The artist's fixed identity: visual style, singing voice and genres.

Simplified studio (2026-11): a Universe is ONE artist, and three things about
that artist never change from song to song, because they are what makes the
artist recognisable:

* the **visual style** (photorealistic, an anime flavour, oil painting...),
  applied to the Character Master and to every shot of every video;
* the **singing voice description**, one fixed text. Lyria cannot pin a voice
  (it takes no reference audio), so the same words are sent verbatim in every
  lyric brief and in every Lyria prompt for this artist. It is the strongest
  approximation the model allows, and it is enforced by code after the
  Director answers, not merely requested in a prompt;
* the **musical genres** (up to three, combinable, plus a free text mix),
  inherited by every song unless that song adjusts them for itself.
"""

from __future__ import annotations

from typing import Any

# --- Visual styles -----------------------------------------------------------

PHOTO_STYLE_KEY = "photo"
"""The style is read from an uploaded photo instead of picked from the list."""

VISUAL_STYLES: tuple[dict[str, str], ...] = (
    {
        "key": "realista",
        "label": "Realista fotográfico",
        "prompt": (
            "Photorealistic, shot on a real camera, natural skin texture, "
            "cinematic lighting, no illustration, no cartoon."
        ),
    },
    {
        "key": "anime_cinematografico",
        "label": "Anime cinematográfico",
        "prompt": (
            "Cinematic anime, detailed mature characters with realistic "
            "proportions, rich shading, film lighting, not childish cel anime."
        ),
    },
    {
        "key": "anime_clasico",
        "label": "Anime clásico años 90",
        "prompt": (
            "Classic 1990s hand-drawn anime, cel shading, slightly grainy film "
            "look, expressive line work of that era."
        ),
    },
    {
        "key": "anime_suave",
        "label": "Anime suave romántico",
        "prompt": (
            "Soft romantic anime, gentle pastel palette, delicate line work, "
            "dreamy diffused light."
        ),
    },
    {
        "key": "oleo",
        "label": "Óleo, pintura clásica",
        "prompt": (
            "Classical oil painting, visible brushstrokes, canvas texture, "
            "chiaroscuro lighting, museum portrait quality."
        ),
    },
    {
        "key": "ilustracion",
        "label": "Ilustración digital pintada",
        "prompt": (
            "Painted digital illustration, painterly rendering, rich colour, "
            "visible brushwork but clean modern finish."
        ),
    },
    {
        "key": "tres_d",
        "label": "3D tipo película animada",
        "prompt": (
            "High-end 3D animated film rendering, stylised realistic "
            "characters, soft global illumination, cinematic depth of field."
        ),
    },
    {
        "key": PHOTO_STYLE_KEY,
        "label": "El estilo de mi foto",
        "prompt": "",
    },
)

VISUAL_STYLE_KEYS: frozenset[str] = frozenset(s["key"] for s in VISUAL_STYLES)


def visual_style_label(key: str) -> str:
    for style in VISUAL_STYLES:
        if style["key"] == key:
            return style["label"]
    return ""


def visual_style_prompt(bible: Any) -> str:
    """The English style instruction that travels with every image and video
    prompt of this artist. Empty when no style was chosen."""
    visual = getattr(bible, "visual", None)
    if visual is None:
        return ""
    key = (getattr(visual, "style_key", "") or "").strip()
    if not key:
        return ""
    if key == PHOTO_STYLE_KEY:
        return (getattr(visual, "photo_style_description", "") or "").strip()
    for style in VISUAL_STYLES:
        if style["key"] == key:
            return style["prompt"]
    return ""


def style_block(bible: Any) -> str:
    prompt = visual_style_prompt(bible)
    if not prompt:
        return ""
    return f"VISUAL STYLE OF THIS ARTIST (fixed, apply to every image): {prompt}"


# --- Musical genres ----------------------------------------------------------

MUSIC_GENRES: tuple[dict[str, str], ...] = tuple(
    {"key": key, "label": label}
    for key, label in (
        ("pop", "Pop"),
        ("rock", "Rock"),
        ("balada", "Balada"),
        ("bachata", "Bachata"),
        ("salsa", "Salsa"),
        ("merengue", "Merengue"),
        ("regueton", "Reguetón"),
        ("trap", "Trap"),
        ("rap", "Rap / hip-hop"),
        ("rnb", "R&B"),
        ("corridos", "Corridos"),
        ("regional", "Ranchera / regional mexicano"),
        ("cumbia", "Cumbia"),
        ("vallenato", "Vallenato"),
        ("electronica", "Electrónica / EDM"),
        ("synthwave", "Synthwave"),
        ("jazz", "Jazz"),
        ("blues", "Blues"),
        ("country", "Country"),
        ("metal", "Metal"),
        ("punk", "Punk"),
        ("indie", "Indie"),
        ("folk", "Folk"),
        ("flamenco", "Flamenco"),
    )
)

MUSIC_GENRE_KEYS: frozenset[str] = frozenset(g["key"] for g in MUSIC_GENRES)
MAX_MAIN_GENRES = 3


def genre_label(key: str) -> str:
    for genre in MUSIC_GENRES:
        if genre["key"] == key:
            return genre["label"]
    return key


def genres_text(genres: list[str] | None, genre_free: str = "") -> str:
    """The genre combination as one line, for prompts and for the phone."""
    labels = [genre_label(g) for g in (genres or []) if g]
    parts = labels + ([genre_free.strip()] if (genre_free or "").strip() else [])
    return " + ".join(parts)


# --- Singing voice -----------------------------------------------------------


def compose_singing_voice(fields: dict[str, Any]) -> str:
    """Compose the ONE fixed singing-voice text from its parts.

    The composed text is what gets stored and what is sent verbatim to Lyria;
    the parts exist so the user can edit one aspect without rewriting the
    whole description.
    """
    bits = [
        ("Voice", fields.get("sex")),
        ("Heard age", fields.get("apparent_age")),
        ("Pitch", fields.get("pitch")),
        ("Timbre", fields.get("timbre")),
        ("Language and accent", fields.get("language_accent")),
        ("Singing style", fields.get("singing_style")),
    ]
    lines = [f"{label}: {str(value).strip()}" for label, value in bits if str(value or "").strip()]
    return "\n".join(lines)
