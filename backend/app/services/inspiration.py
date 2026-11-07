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

from ..domain import artist as artist_domain
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


def instruccion_analisis() -> str:
    """The analysis instruction, with the app's genre catalogue in it.

    On top of the style summary, the analysis matches what it hears to
    the fixed catalogue (``genre_keys``), so a song's sheet can fill its
    own genre combination from the analysis alone — analysing a link and
    then marking the genres by hand anyway made the analysis pointless
    to its owner. The keys are written out here, from the domain
    catalogue (the one source), and the match is validated again in code
    when the result lands: an invented key never reaches a sheet.
    """
    catalogo = ", ".join(
        f"{genero['key']} ({genero['label']})" for genero in artist_domain.MUSIC_GENRES
    )
    return (
        INSTRUCTION
        + "\n\nAlso match the song to the app's fixed genre catalogue. In "
        "genre_keys, return the keys of the catalogue genres that are "
        "actually heard in this song — at most three, the main ones "
        "first, each key written EXACTLY as listed. If no catalogue genre "
        f"honestly fits, return an empty list. The catalogue is: {catalogo}."
    )


def casar_generos(claves: Any) -> list[str]:
    """The keys the analysis returned, matched to the catalogue.

    Anything that is not a catalogue key does not enter (the model can
    reword a genre or invent one), repeats count once, and the cap is
    the usual one: MAX_MAIN_GENRES main genres.
    """
    casadas: list[str] = []
    for clave in claves or []:
        clave = str(clave).strip().lower()
        if clave in artist_domain.MUSIC_GENRE_KEYS and clave not in casadas:
            casadas.append(clave)
    return casadas[: artist_domain.MAX_MAIN_GENRES]


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


def youtube_video_id(url: str) -> str | None:
    """The video id inside any YouTube URL shape, or None."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidato = parsed.path.strip("/").split("/")[0]
        return candidato or None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            valores = parse_qs(parsed.query).get("v") or []
            return valores[0] if valores else None
        for prefijo in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefijo):
                candidato = parsed.path[len(prefijo):].split("/")[0]
                return candidato or None
    return None


def normalize_youtube_url(url: str) -> str:
    """The one canonical watch URL for a YouTube link.

    The link the user pastes travels to Vertex exactly as copied — and a
    music.youtube.com URL made the model "watch" YouTube's deprecated-
    browser page instead of the song, then invent a whole analysis of that
    page (production, «Falsos Positivos»: title "Your browser is
    deprecated", glitch pop that was never in the song). Every URL shape —
    music.youtube.com, youtu.be, shorts, embed, live — is rewritten to the
    plain watch URL of the same video before anything is analysed.
    """
    video_id = youtube_video_id(url)
    if not video_id:
        return (url or "").strip()
    return f"https://www.youtube.com/watch?v={video_id}"


def _video_part(url: str, *, start: int | None = None, end: int | None = None) -> dict[str, Any]:
    # La forma EXACTA de la instalacion hermana que si ve los videos
    # (Drama, inspiracion.js): el enlace declarado como «video/*» y los
    # cortes como objetos {seconds: n}. Declararlo «video/mp4» hacia que
    # Vertex tratara la pagina watch como un archivo remoto que descargar,
    # y lo que hay tras esa URL es la pagina HTML: a una descarga sin
    # navegador real le sirve su version «browser is deprecated», y el
    # modelo analizaba esa pagina en vez de la cancion.
    part: dict[str, Any] = {"fileData": {"fileUri": url, "mimeType": "video/*"}}
    if start is not None and end is not None:
        part["videoMetadata"] = {
            "startOffset": {"seconds": int(start)},
            "endOffset": {"seconds": int(end)},
        }
    return part


def _analyse(studio, url: str, *, video_part: dict[str, Any]) -> dict[str, Any]:
    spec = studio.registry.default_for("text")
    resultado = gemini_text.generate(
        studio.vertex,
        spec.id if spec else "gemini-3.1-pro-preview",
        system_instruction=system_instruction(CreativeRole.MUSIC_DIRECTOR),
        prompt=instruccion_analisis(),
        schema=S.INSPIRATION_SCHEMA,
        extra_parts=[video_part],
        # El video primero y la instruccion despues, como en la forma que
        # funciona: con el texto primero, Vertex no lo miraba como video.
        extra_parts_first=True,
    )
    return resultado.data or {}


def analyse_youtube(studio, url: str) -> Inspiration:
    """Watch the video at ``url`` and return its style summary."""
    url = (url or "").strip()
    if not is_youtube_url(url):
        raise InvalidGenerationRequest(
            "Ese enlace no es de YouTube. Pega el enlace de la cancion de YouTube."
        )
    url = normalize_youtube_url(url)
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
    inspiracion = _to_inspiration(url, data)
    _comprobar_que_vio_el_video(inspiracion)
    return inspiracion


# --- La guardia anti-fabricacion -------------------------------------------
#
# Un analisis puede "funcionar" sin haber visto el video: el modelo recibe
# una pagina de error de YouTube y, en vez de fallar, inventa un analisis
# completo de esa pagina. Paso en produccion («Falsos Positivos»): el
# resumen guardado empezaba «Reference: Your browser is deprecated» y
# describia glitch pop industrial para un duo romantico. Un resumen asi no
# es un resumen malo: es un resumen de otra cosa, y guardarlo como valido
# contamina cada paso siguiente. Las firmas comprobadas son pocas y
# concretas, las que delatan que lo visto fue una pagina de error o que el
# propio modelo declara no haber accedido:
#
# * el titulo viene vacio (un analisis real nombra el video que vio);
# * el titulo o el resumen traen el titulo de una pagina de error conocida
#   de YouTube («Your browser is deprecated», «This video is unavailable»,
#   «Sign in to confirm», ...);
# * el titulo o el resumen declaran que no se pudo acceder al video.

_FIRMAS_PAGINA_ERROR = (
    "browser is deprecated",
    "browser is no longer supported",
    "this video is unavailable",
    "video unavailable",
    "video no disponible",
    "sign in to confirm",
    "private video",
    "page not found",
)

_FIRMAS_SIN_ACCESO = (
    "no pude acceder",
    "no se pudo acceder",
    "no puedo ver el video",
    "no fue posible acceder",
    "could not access",
    "couldn't access",
    "unable to access",
    "cannot access the video",
    "can't access the video",
)

_FIRMAS = _FIRMAS_PAGINA_ERROR + _FIRMAS_SIN_ACCESO


def _firma_en(texto: str) -> str | None:
    bajo = (texto or "").lower()
    for firma in _FIRMAS:
        if firma in bajo:
            return firma
    return None


def motivo_resumen_no_utilizable(summary_text: str) -> str | None:
    """Why a stored summary cannot be used as a song reference, or None.

    Empty is unusable — and so is fabricated: a summary whose text carries
    an error-page signature is the analysis of a page that was not the
    song, however full it looks. The song router checks stored summaries
    with this before proposing a concept, so a phantom analysis saved
    before this guard existed cannot slip into a new concept either.
    """
    texto = (summary_text or "").strip()
    if not texto:
        return "el analisis no dejo ningun resumen guardado"
    firma = _firma_en(texto)
    if firma:
        return (
            f"el resumen guardado no viene de la cancion: trae «{firma}», "
            "la firma de una pagina de error de YouTube"
        )
    return None


def motivo_inspiracion_no_utilizable(inspiracion: Inspiration) -> str | None:
    """Why one STORED Inspiration cannot feed a prompt, or None.

    The same check the analysis passes on its way in, applied to what is
    already saved — to the summary text as it finally sits in the Bible.
    That distinction is the hole this closes: the guard inside
    ``analyse_youtube`` only ever sees the object ``_to_inspiration``
    composes from the model's structured fields, while the text that is
    finally persisted is a free, editable field. The Bible's write
    routes (the verbatim list PUT, the whole-Bible PUT) persist whatever
    summary text they are sent, and until now no read or prompt route
    re-checked it — so a stored summary leading with «Reference: Your
    browser is deprecated» under a perfectly good title (a text the
    composition could never produce from that title) sailed past the
    guard and into every prompt. The check therefore runs on the stored
    text, every time it is read, marked or used.
    """
    motivo = motivo_resumen_no_utilizable(inspiracion.summary_text)
    if motivo is not None:
        return motivo
    firma = _firma_en(inspiracion.title)
    if firma:
        return (
            f"el titulo guardado no es el de la cancion: trae «{firma}», "
            "la firma de una pagina de error de YouTube"
        )
    return None


def inspiracion_utilizable(inspiracion: Inspiration) -> bool:
    return motivo_inspiracion_no_utilizable(inspiracion) is None


def con_marca(inspiracion: Inspiration) -> dict[str, Any]:
    """The inspiration as the screens receive it, with its usability mark.

    The mark is recomputed here, from the stored text, at read time —
    never stored and never trusted from the client — so re-saving a
    fabricated summary cannot launder it into a valid one.
    """
    motivo = motivo_inspiracion_no_utilizable(inspiracion)
    return {
        **inspiracion.model_dump(),
        "inspiration_usable": motivo is None,
        "inspiration_unusable_reason": motivo or "",
    }


def _comprobar_que_vio_el_video(inspiracion: Inspiration) -> None:
    """Raise unless the analysis really saw a video.

    An empty summary, an empty title, or an error-page/no-access signature
    anywhere in the result means the video was not watched: the analysis
    FAILS, visibly, and nothing is saved as a usable summary.
    """
    if not (inspiracion.title or "").strip():
        raise ProviderError(
            "El analisis no devolvio ni el titulo del video: no consta que "
            "lo haya visto, asi que no se guarda ningun resumen. Prueba con "
            "el enlace normal de YouTube (youtube.com/watch?v=...)."
        )
    motivo = motivo_resumen_no_utilizable(inspiracion.summary_text)
    if motivo is None:
        firma = _firma_en(inspiracion.title)
        if firma:
            motivo = (
                f"el titulo devuelto no es el de la cancion: trae «{firma}», "
                "la firma de una pagina de error de YouTube"
            )
    if motivo is not None:
        raise ProviderError(
            f"El analisis de ese enlace no es utilizable: {motivo}. No se "
            "guardo ningun resumen; prueba con el enlace normal de YouTube "
            "(youtube.com/watch?v=...)."
        )


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
            "summary of the whole song. Carry the genre_keys over: the "
            "union of the partial summaries' keys, at most three, main "
            "first.\n\n" + texto
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
        genre_keys=casar_generos(data.get("genre_keys")),
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
    """The artist's USABLE inspiration summaries as one block for a prompt.

    A summary that did not come from its song (empty, or carrying the
    fabricated-analysis signature) is excluded here, at the prompt's
    door: it stays on the artist's sheet, visibly marked, but it never
    reaches a prompt.
    """
    return "\n\n".join(
        inspiracion.summary_text
        for inspiracion in bible.inspirations
        if inspiracion.summary_text and inspiracion_utilizable(inspiracion)
    )
