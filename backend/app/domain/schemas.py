"""Entities of a Universe (PRD 8-23, 33-35, 46).

Every model inherits ``Entity`` so that ``universe_id`` is never optional and
Firestore documents round trip cleanly. ``protected_namespaces`` is cleared
because the domain genuinely has fields called ``model`` and ``model_version``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..clock import now_iso
from .enums import (
    AspectRatio,
    CanonStatus,
    CharacterRole,
    JobState,
    LyricsAuthor,
    StageKey,
    StageStatus,
    UserAction,
    VideoType,
)


class Base(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), extra="ignore", use_enum_values=True)


class Entity(Base):
    id: str
    universe_id: str
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# --- Provenance (PRD 46) ---------------------------------------------------


class UserContribution(Base):
    """What the human actually did, kept next to what the machine did."""

    action: UserAction | None = None
    written: str | None = None
    edited: str | None = None
    note: str | None = None
    at: str | None = None


class Provenance(Base):
    parent_id: str | None = None
    model: str | None = None
    model_version: str | None = None
    variant: str | None = None
    prompt: str | None = None
    references: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=now_iso)
    output: list[dict[str, Any]] = Field(default_factory=list)
    status: CanonStatus = CanonStatus.DRAFT
    version: int = 1
    cost_usd: float = 0.0
    user_contributions: list[UserContribution] = Field(default_factory=list)


# --- Artist Bible (PRD 9) --------------------------------------------------


class Identity(Base):
    stage_name: str = ""
    fictional_name: str | None = None
    apparent_age: str = ""
    origin: str = ""
    languages: list[str] = Field(default_factory=list)
    personality: str = ""
    backstory: str = ""
    target_audience: str = ""
    recurring_themes: list[str] = Field(default_factory=list)


class MusicalIdentity(Base):
    genre: str = ""
    subgenres: list[str] = Field(default_factory=list)
    bpm_range: str = ""
    instrumentation: list[str] = Field(default_factory=list)
    production: str = ""
    structures: list[str] = Field(default_factory=list)
    lyrical_themes: list[str] = Field(default_factory=list)
    language: str = ""
    mood: str = ""
    vocal_characteristics: str = ""


class VisualIdentity(Base):
    style_key: str = ""
    """Chosen from domain.artist.VISUAL_STYLES. Fixed for this artist: the
    Master and every shot of every video are generated in this style."""
    style_label: str = ""
    photo_style_description: str = ""
    """When style_key is 'photo': the style read from the uploaded photo, in
    English, ready to travel inside image and video prompts."""
    master_stale: bool = False
    """The style changed after the Master was approved: the Master no longer
    represents the artist and has to be redone before new videos."""
    appearance: str = ""
    aesthetic: str = ""
    palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    photography: str = ""
    cinematography: str = ""
    architecture: str = ""
    settings: list[str] = Field(default_factory=list)
    recurring_motifs: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)


class Communication(Base):
    speech_style: str = ""
    humour: str = ""
    catchphrases: list[str] = Field(default_factory=list)
    recurring_topics: list[str] = Field(default_factory=list)


class GenerationPreferences(Base):
    """PRD 9. Fallback when the user does not pick a model for a generation."""

    preferred_image_model: str | None = None
    preferred_image_variant: str | None = None
    preferred_video_model: str | None = None
    preferred_video_variant: str | None = None
    working_resolution: str = "1K"


class VoiceProfile(Base):
    """PRD 10. Free text lines, reused in every music generation."""

    lines: list[str] = Field(default_factory=list)

    def as_prompt(self) -> str:
        return "\n".join(line.strip() for line in self.lines if line.strip())


class SingingVoice(Base):
    """The artist's singing voice, as ONE fixed text.

    Lyria takes no reference audio, so a voice cannot be pinned; what can be
    pinned is the description. The parts are composed into ``text`` by
    domain.artist.compose_singing_voice, and that text is inserted verbatim
    into every lyric brief and every Lyria prompt of this artist, enforced by
    code after the Director answers. Editing it only affects future songs.
    """

    sex: str = ""
    apparent_age: str = ""
    """The age the voice sounds like, not the artist's age."""
    pitch: str = ""
    """Grave, media, aguda... as the user words it."""
    timbre: str = ""
    language_accent: str = ""
    singing_style: str = ""
    text: str = ""
    """The composed description, exactly as it travels to Lyria."""


class Inspiration(Base):
    """One YouTube reference, analysed by the app itself into an editable
    summary. Inspiration only: the instruction to the Director and to Lyria
    is to create original material, never to copy lyrics or melody."""

    url: str = ""
    title: str = ""
    genres: str = ""
    rhythm: str = ""
    instruments: list[str] = Field(default_factory=list)
    structure: str = ""
    mood: str = ""
    lyric_themes: list[str] = Field(default_factory=list)
    lyric_style: str = ""
    genre_keys: list[str] = Field(default_factory=list)
    """What was heard, matched to the app's fixed genre catalogue: keys of
    domain.artist.MUSIC_GENRES, validated when the analysis lands (the
    model's raw picks never reach a sheet unfiltered). A song's own sheet
    fills its genre combination from these after an analysis, so analysing
    a reference leaves the song ready instead of asking the user to mark
    the genres by hand. The summary stays the piece that feeds concepts."""
    summary_text: str = ""
    """The whole summary as one editable text: this is what feeds the songs."""
    created_at: str = Field(default_factory=now_iso)


class ArtistBible(Entity):
    identity: Identity = Field(default_factory=Identity)
    musical: MusicalIdentity = Field(default_factory=MusicalIdentity)
    visual: VisualIdentity = Field(default_factory=VisualIdentity)
    communication: Communication = Field(default_factory=Communication)
    preferences: GenerationPreferences = Field(default_factory=GenerationPreferences)
    voice_profile: VoiceProfile = Field(default_factory=VoiceProfile)
    singing_voice: SingingVoice = Field(default_factory=SingingVoice)
    music_genres: list[str] = Field(default_factory=list)
    """Up to three main genres from domain.artist.MUSIC_GENRES. They define
    the artist; each song inherits them and may adjust them for itself."""
    music_genre_free: str = ""
    """The user's own mix in their own words, on top of the picked genres."""
    inspirations: list[Inspiration] = Field(default_factory=list)
    inspirations_failed: list[str] = Field(default_factory=list)
    """Enlaces pegados al crear el artista cuyo analisis fallo.

    Antes ese fallo se tragaba en silencio (una linea de log) y el enlace
    desaparecia: «Como Mario» nunca llego a ser referencia y nadie lo
    supo. Ahora quedan a la vista en la ficha, para volver a pegarlos.
    """
    inspirations_pending: list[str] = Field(default_factory=list)
    """Enlaces pegados al crear el artista cuyo analisis esta EN COLA.

    Crear el artista analizaba los enlaces dentro de la peticion, y un
    analisis tarda mas que los 45 segundos que la pantalla espera: el
    artista se creaba igual en el servidor, pero la pantalla decia que
    no, y el reintento que el propio error invitaba a hacer lo dejaba
    DUPLICADO. Ahora la creacion es inmediata y deja los enlaces aqui,
    pendientes: el trabajo de creacion los analiza en la cola y los va
    moviendo a ``inspirations`` (o a ``inspirations_failed``). Mientras
    esta lista no este vacia, el analisis sigue en camino y se ve —
    y la Biblia no se reescribe, porque saldria sin esas referencias.
    Las Biblias guardadas antes de este campo se leen sin pendientes.
    """
    status: CanonStatus = CanonStatus.DRAFT
    version: int = 1


class Universe(Entity):
    """PRD 8. One artist, fully isolated."""

    name: str
    tagline: str = ""
    cover_image: str | None = None
    status: CanonStatus = CanonStatus.DRAFT


# --- Characters, wardrobe, locations (PRD 17-20) ---------------------------


class MasterShot(Base):
    """One of the canonical reference frames of a character (PRD 18)."""

    key: str
    label: str
    image_id: str | None = None
    storage_path: str | None = None
    status: CanonStatus = CanonStatus.DRAFT
    # Cuantas veces se ha sustituido la imagen de esta toma. La ruta es
    # canonica y no cambia al regenerar, asi que sin esto la vista pinta
    # siempre la misma direccion y el telefono sigue ensenando la copia
    # vieja de su cache: la version viaja en la URL como marca nueva.
    version: int = 0


MASTER_SHOTS: tuple[tuple[str, str], ...] = (
    ("portrait", "Portrait"),
    ("full_body", "Full body"),
    ("profile", "Profile"),
    ("three_quarter", "Three-quarter"),
    ("neutral", "Neutral expression"),
    ("emotions", "Emotional expressions"),
    ("poses", "Relevant poses"),
)


class Character(Entity):
    name: str
    role: CharacterRole = CharacterRole.SUPPORTING
    gender: str = ""
    """Lo decide quien crea al artista, y el Director no puede cambiarlo."""
    rasgos: dict[str, str] = Field(default_factory=dict)
    """Como es: piel, pelo, cuerpo, estilo. Lo elegido manda sobre el Director.

    Lo que se deje en blanco si lo decide el, que para eso esta. Pero lo que se
    elige no se discute: si aqui pone pelo morado, sale con el pelo morado.
    """
    apparent_age: str = ""
    appearance: str = ""
    personality: str = ""
    wardrobe_ids: list[str] = Field(default_factory=list)
    """Legacy field from when wardrobe was its own section. Unused: wardrobe
    is now proposed inside each video's storyboard, as text."""
    master_shots: list[MasterShot] = Field(default_factory=list)
    reference_image_paths: list[str] = Field(default_factory=list)
    """Approved master shots, attached to every later generation (PRD 18)."""
    source_photo_path: str | None = None
    """A photo the user uploaded: used as the Master itself, or as the base
    a new Master was generated from, or as the source of the visual style."""
    master_stale: bool = False
    """The artist's visual style changed after this Master was approved."""
    status: CanonStatus = CanonStatus.DRAFT
    provenance: Provenance | None = None

    @property
    def is_master_approved(self) -> bool:
        return self.status == CanonStatus.APPROVED and bool(self.reference_image_paths)


# --- Music (PRD 14, 15) ----------------------------------------------------


class SongVersion(Base):
    version: int
    job_id: str | None = None
    audio_path: str | None = None
    duration_seconds: int = 0
    model: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    status: CanonStatus = CanonStatus.DRAFT
    created_at: str = Field(default_factory=now_iso)


class MusicConcept(Base):
    title: str = ""
    concept: str = ""
    hook: str = ""
    genre: str = ""
    bpm: int | None = None
    mood: str = ""
    structure: list[str] = Field(default_factory=list)
    production: str = ""
    interpretation: str = ""
    visual_concept: str = ""
    status: CanonStatus = CanonStatus.DRAFT


class Song(Entity):
    title: str = ""
    concept: MusicConcept = Field(default_factory=MusicConcept)
    lyrics: str = ""
    lyrics_author: LyricsAuthor = LyricsAuthor.AI
    lyrics_status: CanonStatus = CanonStatus.DRAFT
    music_prompt: str = ""
    voice_profile: VoiceProfile = Field(default_factory=VoiceProfile)
    genres: list[str] = Field(default_factory=list)
    """This song's genre combination. Inherited from the artist; adjusting it
    here changes this song only."""
    genre_free: str = ""
    inspiration_url: str = ""
    """An extra YouTube reference for this song only."""
    inspiration_summary: str = ""
    """The editable summary of that reference, fed to lyrics and to Lyria."""
    genre: str = ""
    bpm: int | None = None
    mood: str = ""
    structure: list[str] = Field(default_factory=list)
    requested_duration_seconds: int = 150
    model: str = ""
    model_version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    versions: list[SongVersion] = Field(default_factory=list)
    approved_version: int | None = None
    approved_master_path: str | None = None
    cover_path: str | None = None
    video_project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: CanonStatus = CanonStatus.DRAFT
    cost_usd: float = 0.0

    @property
    def is_approved(self) -> bool:
        return self.status == CanonStatus.APPROVED and bool(self.approved_master_path)


# --- Video project, story, storyboard (PRD 21-23) --------------------------


class Story(Base):
    premise: str = ""
    beginning: str = ""
    development: str = ""
    conflict: str = ""
    climax: str = ""
    resolution: str = ""
    status: CanonStatus = CanonStatus.DRAFT


class StageState(Base):
    key: StageKey
    status: StageStatus = StageStatus.LOCKED
    model: str | None = None
    variant: str | None = None
    cost_usd: float = 0.0
    updated_at: str = Field(default_factory=now_iso)
    note: str = ""


class VideoProject(Entity):
    song_id: str
    title: str = ""
    video_type: VideoType = VideoType.NARRATIVE
    concept: str = ""
    story: Story = Field(default_factory=Story)
    character_ids: list[str] = Field(default_factory=list)
    """The artist, and only the artist: set when the project is created."""
    wardrobe_notes: str = ""
    """Wardrobe for this video, proposed by the Director inside the video
    concept and approved with the story. Text, not a separate section."""
    location_notes: str = ""
    """Locations for this video, same treatment as the wardrobe."""
    storyboard_status: CanonStatus = CanonStatus.DRAFT
    stages: list[StageState] = Field(default_factory=list)
    production_plan: dict[str, Any] | None = None
    master_16x9_path: str | None = None
    master_9x16_path: str | None = None
    status: CanonStatus = CanonStatus.DRAFT
    cost_usd: float = 0.0


class Scene(Entity):
    """PRD 23. Designed in 8 second blocks because that is what Veo allows
    when reference images or 1080p are involved (PRD 26)."""

    project_id: str
    index: int
    duration_seconds: int = 8
    song_timestamp: str = ""
    character_ids: list[str] = Field(default_factory=list)
    location_description: str = ""
    """Where this shot happens, as text proposed inside the storyboard.
    Locations are no longer entities with their own section."""
    wardrobe_description: str = ""
    """What the artist wears in this shot, as text from the storyboard."""
    planos: list[str] = Field(default_factory=list)
    """The short shots inside this 8 second block. The montage target is a
    cut every 3-5 seconds, so each block is planned as two or three planos
    and its video prompt asks for those internal cuts explicitly."""
    action: str = ""
    emotion: str = ""
    camera: str = ""
    lighting: str = ""
    environment: str = ""
    dialogue: str = ""
    visual_objective: str = ""
    reuses_scene_id: str | None = None
    """Set when the Director proposes reusing an already approved take."""
    reuse_note: str = ""
    reuse_forced_by_user: bool = False
    image_id: str | None = None
    image_status: CanonStatus = CanonStatus.DRAFT
    clip_id: str | None = None
    clip_status: CanonStatus = CanonStatus.DRAFT
    status: CanonStatus = CanonStatus.DRAFT
    cost_usd: float = 0.0

    @property
    def is_reused(self) -> bool:
        return bool(self.reuses_scene_id)


class SceneImage(Entity):
    scene_id: str
    project_id: str | None = None
    storage_path: str = ""
    prompt: str = ""
    model: str = ""
    variant: str = ""
    references: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    status: CanonStatus = CanonStatus.DRAFT
    locked: bool = False
    cost_usd: float = 0.0
    job_id: str | None = None
    provenance: Provenance | None = None


class SceneClip(Entity):
    scene_id: str
    project_id: str | None = None
    storage_path: str = ""
    source_image_id: str = ""
    prompt: str = ""
    model: str = ""
    variant: str = ""
    duration_seconds: int = 8
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    generate_audio: bool = False
    """Always false. Kept as an explicit field so logs prove it (PRD 26, 53.27)."""
    references: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    status: CanonStatus = CanonStatus.DRAFT
    locked: bool = False
    cost_usd: float = 0.0
    job_id: str | None = None
    provenance: Provenance | None = None


# --- Jobs, spend, canon, exports -------------------------------------------


class Job(Entity):
    """PRD 37. Runs in Google Cloud whether or not the phone stays open."""

    kind: str
    state: JobState = JobState.QUEUED
    model: str = ""
    variant: str = ""
    target_type: str = ""
    target_id: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    idempotency_key: str | None = None
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    started_at: str | None = None
    finished_at: str | None = None


class CanonEntry(Entity):
    entity_type: str
    entity_id: str
    label: str = ""
    storage_path: str | None = None
    status: CanonStatus = CanonStatus.APPROVED
    note: str = ""


class ExportPackage(Entity):
    song_id: str
    project_id: str | None = None
    root_path: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    manifest_path: str | None = None
    archive_path: str | None = None
    status: CanonStatus = CanonStatus.DRAFT
