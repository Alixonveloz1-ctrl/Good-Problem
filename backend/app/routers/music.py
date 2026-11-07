"""Music Studio (PRD 12, 13, 14, 15).

The rail is: idea or lyrics -> Director -> music concept -> lyrics -> Lyria 3
Pro -> song version, and the version just generated IS the song master.

No step asks for an approval: each step only needs the previous one to exist.
The concept has to exist before the Director writes lyrics from it, the
lyrics have to exist before Lyria is called, and the generated version
becomes the current one in the act — regenerating replaces it. The old
approve/reject endpoints stay as harmless no-ops for compatibility.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.repositories import SONGS, Repository
from ..domain import artist as artist_domain
from ..domain.enums import CanonStatus, CreativeRole, LyricsAuthor, UserAction
from ..errors import Conflict, DomainError, NotFound
from ..ids import new_id
from ..orchestrator.orchestrator import GenerationRequest
from ..services import approvals as approval_rules
from ..services import inspiration as inspiration_service
from ..services.approvals import ApprovalService
from ..services.context import load_bible
from .deps import OwnerDep, StudioDep

router = APIRouter(prefix="/api/universes/{universe_id}/songs", tags=["music"])


def _repo(studio, universe_id: str) -> Repository:
    studio.orchestrator.require_universe(universe_id)
    return Repository(studio.db, universe_id, SONGS)


class SongIn(BaseModel):
    title: str = ""
    requested_duration_seconds: int = 150
    genres: list[str] | None = None
    """La combinacion de generos de esta cancion. Si no viene, hereda la del
    artista; ajustarla aqui cambia solo esta cancion."""
    genre_free: str | None = None


class DirectorIn(BaseModel):
    brief: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)
    """What the user changed by hand: genre, BPM, mood... The Director rebuilds
    its proposal from these instead of arguing them back (PRD 11)."""
    model: str | None = None
    idempotency_key: str | None = None


class LyricsIn(BaseModel):
    lyrics: str
    author: LyricsAuthor = LyricsAuthor.USER


class GenerateIn(BaseModel):
    duration_seconds: int | None = None
    prompt: str | None = None
    negative_prompt: str = ""
    seed: int | None = None
    idempotency_key: str | None = None


def _bloques_fijos(studio, universe_id: str, cancion: dict[str, Any]) -> dict[str, str]:
    """Lo fijo que acompana a cada encargo de esta cancion: la voz cantada
    del artista palabra por palabra, su combinacion de generos y los
    resumenes de inspiracion. El handler los vuelve a imponer sobre el
    resultado, asi que no dependen de que el Director los copie bien."""
    bible = load_bible(studio.db, universe_id)
    resumenes = inspiration_service.bible_inspiration_text(bible)
    if (cancion.get("inspiration_summary") or "").strip():
        resumenes = (resumenes + "\n\n" + cancion["inspiration_summary"]).strip()
    return {
        "singing_voice_text": bible.singing_voice.text or bible.voice_profile.as_prompt(),
        "genres_text": artist_domain.genres_text(
            cancion.get("genres") or bible.music_genres,
            cancion.get("genre_free") or bible.music_genre_free,
        ),
        "inspiration_text": resumenes,
        # La referencia de ESTA cancion, por separado: en la llamada de
        # concepto viaja en su propio bloque, primero y con rango, sin
        # mezclarse con las inspiraciones del artista.
        "song_inspiration_text": (cancion.get("inspiration_summary") or "").strip(),
    }


def _referencia_no_utilizable(cancion: dict[str, Any]) -> str | None:
    """Why this song's reference link cannot feed a concept, or None.

    A pasted link is a promise: the concept must not be generated "as if"
    the reference had entered when its analysis failed, came back empty or
    was fabricated from an error page. The failure mark written by the
    inspiration endpoint is checked first; a stored summary is checked
    too, so a phantom summary saved before the guard existed (the
    «Falsos Positivos» case) is caught here as well.
    """
    if cancion.get("inspiration_failed"):
        return (
            cancion.get("inspiration_error")
            or "el analisis de ese enlace fallo y no dejo resumen"
        )
    if not (cancion.get("inspiration_url") or "").strip():
        return None
    return inspiration_service.motivo_resumen_no_utilizable(
        cancion.get("inspiration_summary") or ""
    )


@router.post("")
def create_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, body: SongIn
) -> dict[str, Any]:
    bible = load_bible(studio.db, universe_id)
    generos = (
        [g for g in body.genres if g in artist_domain.MUSIC_GENRE_KEYS][
            : artist_domain.MAX_MAIN_GENRES
        ]
        if body.genres is not None
        else list(bible.music_genres)
    )
    libre = body.genre_free if body.genre_free is not None else bible.music_genre_free
    return _repo(studio, universe_id).create(
        new_id("song"),
        {
            "title": body.title,
            "requested_duration_seconds": min(max(body.requested_duration_seconds, 15), 180),
            "voice_profile": bible.voice_profile.model_dump(),
            "genres": generos,
            "genre_free": libre,
            "genre": artist_domain.genres_text(generos, libre) or bible.musical.genre,
            "status": CanonStatus.DRAFT.value,
            "lyrics_status": CanonStatus.DRAFT.value,
            "versions": [],
        },
    )


@router.get("")
def list_songs(owner: OwnerDep, studio: StudioDep, universe_id: str) -> list[dict[str, Any]]:
    return _repo(studio, universe_id).list(limit=200)


@router.get("/{song_id}")
def get_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    versions = []
    for version in song.get("versions") or []:
        versions.append(
            {**version, "url": studio.storage.signed_url(version["audio_path"])
             if version.get("audio_path") else None}
        )
    return {**song, "versions": versions}


@router.patch("/{song_id}")
def patch_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    repo = _repo(studio, universe_id)
    repo.require(song_id)
    allowed = {
        k: v
        for k, v in body.items()
        if k in {"title", "genre", "genres", "genre_free", "bpm", "mood",
                 "structure", "music_prompt", "requested_duration_seconds",
                 "concept", "metadata", "inspiration_summary"}
    }
    if "genres" in allowed:
        allowed["genres"] = [
            g for g in allowed["genres"] if g in artist_domain.MUSIC_GENRE_KEYS
        ][: artist_domain.MAX_MAIN_GENRES]
    if (allowed.get("inspiration_summary") or "").strip():
        # Un resumen escrito a mano sustituye al analisis que fallo: la
        # marca de fallo ya no describe esta ficha.
        allowed["inspiration_failed"] = False
        allowed["inspiration_error"] = ""
    updated = repo.update(song_id, allowed)
    ApprovalService(studio.db).record_user_action(universe_id, SONGS, song_id, UserAction.EDIT)
    return updated


# --- Director on the song --------------------------------------------------


@router.delete("/{song_id}")
def delete_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, str]:
    """Borra una cancion.

    Los archivos generados se quedan: pueden estar dentro de un videoclip ya
    montado, y borrarlos dejaria ese video sin audio sin que nadie se entere.
    """
    repo = Repository(studio.db, universe_id, SONGS)
    repo.require(song_id)
    repo.delete(song_id)
    return {"deleted": song_id}


@router.post("/{song_id}/concept")
def propose_concept(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: DirectorIn
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    motivo = _referencia_no_utilizable(song)
    if motivo:
        raise Conflict(
            "Esta cancion tiene un enlace de referencia que no se pudo "
            f"analizar: {motivo}. Vuelve a analizar el enlace desde la "
            "ficha de la cancion y luego pide la propuesta: no se genera "
            "un concepto fingiendo que la referencia entro."
        )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="song",
            target_id=song_id,
            model=body.model,
            role=CreativeRole.MUSIC_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "music_concept",
                "brief": body.brief,
                "overrides": body.overrides,
                "duration_seconds": song.get("requested_duration_seconds", 150),
                **_bloques_fijos(studio, universe_id, song),
            },
        )
    )


@router.post("/{song_id}/concept/approve")
def approve_concept(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    """Compatibilidad: el concepto generado ya esta en uso. No-op."""
    return _repo(studio, universe_id).require(song_id)


@router.post("/{song_id}/lyrics/generate")
def generate_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: DirectorIn
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    if not (song.get("concept") or {}):
        raise Conflict(
            "Pide primero la propuesta de concepto: el Director escribe la "
            "letra a partir de ella."
        )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="song",
            target_id=song_id,
            model=body.model,
            role=CreativeRole.MUSIC_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "lyrics",
                "concept": song.get("concept") or {},
                "overrides": body.overrides,
                **_bloques_fijos(studio, universe_id, song),
            },
        )
    )


@router.put("/{song_id}/lyrics")
def put_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: LyricsIn
) -> dict[str, Any]:
    """The user pastes or edits the lyrics. They are never modified
    automatically (PRD 12), and the lyrics just saved are the ones in use:
    no approval step stands between them and Lyria."""
    repo = _repo(studio, universe_id)
    repo.require(song_id)
    updated = repo.update(
        song_id,
        {
            "lyrics": body.lyrics,
            "lyrics_author": body.author.value,
            "lyrics_status": CanonStatus.APPROVED.value,
        },
    )
    ApprovalService(studio.db).record_user_action(
        universe_id, SONGS, song_id, UserAction.EDIT, written=body.lyrics[:2000]
    )
    return updated


@router.post("/{song_id}/lyrics/analyze")
def analyze_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: DirectorIn
) -> dict[str, Any]:
    """User supplied lyrics: the Director analyses them and proposes genre, BPM,
    interpretation and production, without rewriting a line (PRD 12)."""
    song = _repo(studio, universe_id).require(song_id)
    if not song.get("lyrics"):
        raise Conflict("Sube o pega una letra antes de pedir el analisis.")
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="text",
            target_type="song",
            target_id=song_id,
            model=body.model,
            role=CreativeRole.MUSIC_DIRECTOR,
            idempotency_key=body.idempotency_key,
            payload={
                "task": "lyrics_analysis",
                "lyrics": song["lyrics"],
                "overrides": body.overrides,
                "brief": body.brief,
                **_bloques_fijos(studio, universe_id, song),
            },
        )
    )


@router.post("/{song_id}/lyrics/approve")
def approve_lyrics(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    """Compatibilidad: la letra que hay es la que vale. No-op."""
    return _repo(studio, universe_id).require(song_id)


# --- Lyria -----------------------------------------------------------------


@router.post("/{song_id}/generate")
def generate_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: GenerateIn
) -> dict[str, Any]:
    """Always Lyria 3 Pro. There is no model selector here because there is
    nothing to select: the other two Lyria models make 30 second clips."""
    song = _repo(studio, universe_id).require(song_id)
    approval_rules.assert_lyrics_ready(studio.db, universe_id, song_id)
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="music",
            target_type="song",
            target_id=song_id,
            model=None,  # resolved to lyria-3-pro-preview by the orchestrator
            idempotency_key=body.idempotency_key,
            payload={
                "duration_seconds": body.duration_seconds
                or song.get("requested_duration_seconds", 150),
                "prompt": body.prompt,
                "negative_prompt": body.negative_prompt,
                "seed": body.seed,
            },
        )
    )


@router.post("/{song_id}/versions/{version}/approve")
def approve_version(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, version: int
) -> dict[str, Any]:
    """Compatibilidad: la ultima version generada ya es el master (PRD 30).

    El handler de musica la deja como vigente en el acto de generarla, asi
    que no hay gesto que hacer aqui. No-op: devuelve la cancion tal cual.
    """
    return _repo(studio, universe_id).require(song_id)


@router.post("/{song_id}/reject")
def reject_song(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str
) -> dict[str, Any]:
    """Compatibilidad: rechazar ya no existe como gesto.

    Si la cancion no gusta, se regenera y la nueva sustituye a la actual.
    No-op: devuelve la cancion tal cual.
    """
    return _repo(studio, universe_id).require(song_id)


@router.post("/{song_id}/cover")
def generate_cover(
    owner: OwnerDep,
    studio: StudioDep,
    universe_id: str,
    song_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    song = _repo(studio, universe_id).require(song_id)
    prompt = body.get("prompt") or (
        f"Album cover for '{song.get('title','')}'. "
        f"{(song.get('concept') or {}).get('visual_concept','')}"
    )
    return studio.orchestrator.submit(
        GenerationRequest(
            universe_id=universe_id,
            kind="image",
            target_type="song",
            target_id=song_id,
            model=body.get("model"),
            variant=body.get("variant"),
            idempotency_key=body.get("idempotency_key"),
            payload={
                "purpose": "cover",
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "reference_paths": body.get("reference_paths") or [],
            },
        )
    )


class SongInspirationIn(BaseModel):
    url: str


@router.post("/{song_id}/inspiration")
def song_inspiration(
    owner: OwnerDep, studio: StudioDep, universe_id: str, song_id: str, body: SongInspirationIn
) -> dict[str, Any]:
    """Un enlace de YouTube solo para esta cancion. Se analiza al momento y
    su resumen queda guardado en la cancion, editable, alimentando su letra
    y su encargo a Lyria.

    Si el analisis falla — o vuelve fabricado de una pagina de error, que
    la guardia del servicio detecta — la cancion queda con una marca
    persistente y visible de que ese enlace no se pudo analizar, y el error
    sube tal cual: nunca se guarda un "analizado" fantasma.
    """
    repo = _repo(studio, universe_id)
    repo.require(song_id)
    try:
        inspiracion = inspiration_service.analyse_youtube(studio, body.url)
    except DomainError as exc:
        repo.update(
            song_id,
            {
                "inspiration_url": body.url,
                "inspiration_summary": "",
                "inspiration_failed": True,
                "inspiration_error": exc.message,
            },
        )
        raise
    return repo.update(
        song_id,
        {
            "inspiration_url": inspiracion.url,
            "inspiration_summary": inspiracion.summary_text,
            "inspiration_failed": False,
            "inspiration_error": "",
        },
    )
