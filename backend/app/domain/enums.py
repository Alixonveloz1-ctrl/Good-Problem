"""Vocabulary of the system. Values are stored verbatim in Firestore."""

from __future__ import annotations

from enum import StrEnum


class ModelKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    MUSIC = "music"
    VIDEO = "video"
    SPEECH = "speech"


class CanonStatus(StrEnum):
    """PRD 16."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class JobState(StrEnum):
    """PRD 37."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobState.APPROVED,
            JobState.REJECTED,
            JobState.FAILED,
            JobState.CANCELLED,
        }


class StageKey(StrEnum):
    """The production rail shown on the phone (PRD 38)."""

    CONCEPT = "concept"
    MUSIC = "music"
    STORY = "story"
    CHARACTERS = "characters"
    STORYBOARD = "storyboard"
    IMAGES = "images"
    VIDEO = "video"
    ASSEMBLY = "assembly"
    EXPORT = "export"


STAGE_ORDER: tuple[StageKey, ...] = (
    StageKey.CONCEPT,
    StageKey.MUSIC,
    StageKey.STORY,
    StageKey.CHARACTERS,
    StageKey.STORYBOARD,
    StageKey.IMAGES,
    StageKey.VIDEO,
    StageKey.ASSEMBLY,
    StageKey.EXPORT,
)


class StageStatus(StrEnum):
    LOCKED = "LOCKED"
    """Waiting for the previous stage to be approved."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CreativeRole(StrEnum):
    """PRD 43. Roles inside one orchestrator, not seven agents."""

    DIRECTOR = "director"
    MUSIC_DIRECTOR = "music_director"
    PRODUCER = "producer"
    CREATIVE_DIRECTOR = "creative_director"
    CASTING_DIRECTOR = "casting_director"
    CINEMATOGRAPHER = "cinematographer"
    EDITOR = "editor"


class VideoType(StrEnum):
    """PRD 21."""

    PERFORMANCE = "performance"
    NARRATIVE = "narrative"
    CINEMATIC = "cinematic"
    MINIMAL = "minimal"
    HYBRID = "hybrid"


class LyricsAuthor(StrEnum):
    """PRD 15."""

    USER = "user"
    AI = "ai"
    MIXED = "mixed"


class AspectRatio(StrEnum):
    LANDSCAPE = "16:9"
    VERTICAL = "9:16"


class CharacterRole(StrEnum):
    LEAD = "lead"
    SUPPORTING = "supporting"
    """Kept for reading old documents. The simplified studio creates only the
    lead: one Universe, one artist."""


class UserAction(StrEnum):
    """PRD 36. Recorded on every asset as part of provenance (PRD 46)."""

    APPROVE = "APPROVE"
    REGENERATE = "REGENERATE"
    EDIT = "EDIT"
    REJECT = "REJECT"
    SAVE_TO_CANON = "SAVE_TO_CANON"
    CONTINUE = "CONTINUE"
