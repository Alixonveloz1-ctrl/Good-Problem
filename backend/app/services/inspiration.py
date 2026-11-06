"""YouTube links as inspiration, analysed by the app itself.

The user pastes a link to a famous song. Nothing is downloaded and no
transcription service is involved: the link goes to Vertex AI as a fileData
part next to the analysis prompt, the same approach already proven in the
user's other studio. Gemini watches the video and returns a summary of the
STYLE — genres, rhythm, instruments, structure, the themes of the lyrics and
how they are written — never the lyrics themselves, and the songs built from
it are original material.

A long video is analysed whole first; if Vertex refuses it for its length,
the analysis is repeated in 20 minute chunks and the chunk summaries are
merged by one more text call.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..domain.enums import CreativeRole
from ..domain.schemas import ArtistBible, Inspiration
from ..errors import InvalidGenerationRequest, ProviderError
from ..orchestrator import schemas_json as S
from ..orchestrator.roles import system_instruction
from ..providers import gemini_text

logger = logging.getLogger("aaus.inspiration")

CHUNK_SECONDS = 1200
MAX_CHUNKS = 3

INSTRUCTION = (
    "Analyse this music video as INSPIRATION for writing a different, original "
    "song. Describe only the style: the genres and how they are mixed, the "
    "rhythm, tempo and feel, the dominant instruments, the song structure "
    "(verse, chorus, bridge...), the mood, the THEMES of the lyrics and the "
    "way they are written (voice, register, rhyme habits). NEVER transcribe "
    "or quote the lyrics, and never describe the melody note by note: the new "
    "song must be original material, not a copy."
)


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if host in {"youtu.be"}:
        return bool(urlparse(url).path.strip("/"))
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        parsed = urlparse(url)
        if parsed.path == "/watch":
            return bool(parse_qs(parsed.query).get("v"))
        return parsed.path.startswith(("/shorts/", "/embed/", "/live/"))
    return False


def _video_part(url: str, *, start: int | None = None, end: int | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"fileData": {"fileUri": url, "mimeType": "video/mp4"}}
    if start is not None and end is not None:
        part["videoMetadata"] = {
            "startOffset": f"{start}s",
            "endOffset": f"{end}s",
        }
    return part


def _analyse(studio, url: str, *, video_part: dict[str, Any]) -> dict[str, Any]:
    spec = studio.registry.default_for("text")
    resultado = gemini_text.generate(
        studio.vertex,
        spec.id if spec else "gemini-3.1-pro-preview",
        system_instruction=system_instruction(CreativeRole.MUSIC_DIRECTOR),
        prompt=INSTRUCTION,
        schema=S.INSPIRATION_SCHEMA,
        extra_parts=[video_part],
    )
    return resultado.data or {}


def analyse_youtube(studio, url: str) -> Inspiration:
    """Watch the video at ``url`` and return its style summary."""
    url = (url or "").strip()
    if not is_youtube_url(url):
        raise InvalidGenerationRequest(
            "Ese enlace no es de YouTube. Pega el enlace de la cancion de YouTube."
        )
    try:
        data = _analyse(studio, url, video_part=_video_part(url))
    except ProviderError:
        # Long video: Vertex refuses the whole file. Analyse it in chunks and
        # merge the partial summaries into one.
        logger.info("inspiration_chunked url=%s", url)
        parciales: list[dict[str, Any]] = []
        for i in range(MAX_CHUNKS):
            try:
                parciales.append(
                    _analyse(
                        studio,
                        url,
                        video_part=_video_part(
                            url, start=i * CHUNK_SECONDS, end=(i + 1) * CHUNK_SECONDS
                        ),
                    )
                )
            except ProviderError:
                break
        if not parciales:
            raise
        data = _merge(studio, parciales)
    return _to_inspiration(url, data)


def _merge(studio, parciales: list[dict[str, Any]]) -> dict[str, Any]:
    spec = studio.registry.default_for("text")
    texto = "\n\n".join(
        "CHUNK SUMMARY:\n"
        + "\n".join(f"{k}: {v}" for k, v in parcial.items() if v)
        for parcial in parciales
    )
    resultado = gemini_text.generate(
        studio.vertex,
        spec.id if spec else "gemini-3.1-pro-preview",
        system_instruction=system_instruction(CreativeRole.MUSIC_DIRECTOR),
        prompt=(
            "These are partial summaries of chunks of ONE music video, all "
            "describing its style as inspiration. Merge them into a single "
            "summary of the whole song.\n\n" + texto
        ),
        schema=S.INSPIRATION_SCHEMA,
    )
    return resultado.data or {}


def _to_inspiration(url: str, data: dict[str, Any]) -> Inspiration:
    inspiracion = Inspiration(
        url=url,
        title=str(data.get("title") or ""),
        genres=str(data.get("genres") or ""),
        rhythm=str(data.get("rhythm") or ""),
        instruments=[str(x) for x in (data.get("instruments") or [])],
        structure=str(data.get("structure") or ""),
        mood=str(data.get("mood") or ""),
        lyric_themes=[str(x) for x in (data.get("lyric_themes") or [])],
        lyric_style=str(data.get("lyric_style") or ""),
    )
    inspiracion.summary_text = summary_text(inspiracion)
    return inspiracion


def summary_text(inspiracion: Inspiration) -> str:
    """The editable one-text version of a summary: this is what feeds songs."""
    lineas = [
        f"Reference: {inspiracion.title}" if inspiracion.title else "",
        f"Genres and mix: {inspiracion.genres}" if inspiracion.genres else "",
        f"Rhythm and feel: {inspiracion.rhythm}" if inspiracion.rhythm else "",
        "Instruments: " + ", ".join(inspiracion.instruments)
        if inspiracion.instruments
        else "",
        f"Structure: {inspiracion.structure}" if inspiracion.structure else "",
        f"Mood: {inspiracion.mood}" if inspiracion.mood else "",
        "Lyric themes: " + ", ".join(inspiracion.lyric_themes)
        if inspiracion.lyric_themes
        else "",
        f"Lyric writing style: {inspiracion.lyric_style}" if inspiracion.lyric_style else "",
    ]
    return "\n".join(linea for linea in lineas if linea)


def bible_inspiration_text(bible: ArtistBible) -> str:
    """All of the artist's inspiration summaries as one block for a prompt."""
    return "\n\n".join(
        inspiracion.summary_text for inspiracion in bible.inspirations if inspiracion.summary_text
    )
