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
    BtsKind,
    CanonStatus,
    CharacterRole,
    ContentKind,
    JobState,
    LyricsAuthor,
    StageKey,
    StageStatus,
    UserAction,
    VideoType,
    WardrobeCategory,
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
    interview_style: str = ""
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
    speaking_voice_secret: str | None = None
    """Secret Manager resource holding the Chirp 3 voice cloning key."""

    def as_prompt(self) -> str:
        return "\n".join(line.strip() for line in self.lines if line.strip())


class ArtistBible(Entity):
    identity: Identity = Field(default_factory=Identity)
    musical: MusicalIdentity = Field(default_factory=MusicalIdentity)
    visual: VisualIdentity = Field(default_factory=VisualIdentity)
    communication: Communication = Field(default_factory=Communication)
    preferences: GenerationPreferences = Field(default_factory=GenerationPreferences)
    voice_profile: VoiceProfile = Field(default_factory=VoiceProfile)
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
    apparent_age: str = ""
    appearance: str = ""
    personality: str = ""
    wardrobe_ids: list[str] = Field(default_factory=list)
    master_shots: list[MasterShot] = Field(default_factory=list)
    reference_image_paths: list[str] = Field(default_factory=list)
    """Approved master shots, attached to every later generation (PRD 18)."""
    status: CanonStatus = CanonStatus.DRAFT
    provenance: Provenance | None = None

    @property
    def is_master_approved(self) -> bool:
        return self.status == CanonStatus.APPROVED and bool(self.reference_image_paths)


class Outfit(Entity):
    name: str
    category: WardrobeCategory = WardrobeCategory.SIGNATURE
    description: str = ""
    image_path: str | None = None
    pieces: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    usage: str = ""
    restrictions: list[str] = Field(default_factory=list)
    status: CanonStatus = CanonStatus.DRAFT
    provenance: Provenance | None = None


class Location(Entity):
    name: str
    description: str = ""
    reference_paths: list[str] = Field(default_factory=list)
    lighting: str = ""
    time_of_day: str = ""
    architecture: str = ""
    mood: str = ""
    status: CanonStatus = CanonStatus.DRAFT
    provenance: Provenance | None = None


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
    content_ids: list[str] = Field(default_factory=list)
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
    location_ids: list[str] = Field(default_factory=list)
    wardrobe_ids: list[str] = Field(default_factory=list)
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
    location_id: str | None = None
    wardrobe_ids: list[str] = Field(default_factory=list)
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


# --- Content studio (PRD 33-35) --------------------------------------------


class ContentPiece(Entity):
    kind: ContentKind
    bts_kind: BtsKind | None = None
    title: str = ""
    song_id: str | None = None
    project_id: str | None = None
    script: str = ""
    spoken_text: str = ""
    video_prompt: str = ""
    spoken_audio_path: str | None = None
    source_image_path: str | None = None
    """The still the clip is generated from, kept apart from the finished video."""
    storage_path: str | None = None
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    source_clip_ids: list[str] = Field(default_factory=list)
    status: CanonStatus = CanonStatus.DRAFT
    cost_usd: float = 0.0
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
