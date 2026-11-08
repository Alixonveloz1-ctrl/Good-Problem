"""Invariants that no configuration change can undo.

The model registry lives in Firestore so prices and availability can be edited
from a phone without a deploy (PRD 41). That flexibility must not be able to
reintroduce the four mistakes the PRD v2.1 exists to correct, so those rules are
hardcoded here and the registry is validated against them on load.

  1. Music is Lyria 3.5 and nothing else, not even as a fallback after a
     failure (PRD 14).
  2. Veo is always called with audio disabled, in every format (PRD 5, 26).
  3. Veo clips last 4, 6 or 8 seconds, and 8 is mandatory whenever the request
     asks for 1080p, 4K or reference images, which is always the case here
     (PRD 23, 26).
  4. A failed job retries with the same model that was requested. The system
     never substitutes a different or weaker model (PRD 37).
"""

from __future__ import annotations

from ..errors import InvalidGenerationRequest, ModelNotAllowed

# --- 1. Music --------------------------------------------------------------

MUSIC_MODEL_ID = "lyria-3.5"

BANNED_MODEL_IDS: frozenset[str] = frozenset(
    {
        # 30 second clip models. Excluded from the selector and from fallback.
        "lyria-3-clip-preview",
        "lyria-3",
        "lyria-2",
        "lyria-002",
        # Imagen never accepted reference images and the endpoints were shut
        # down on 2026-08-17.
        "imagen-3.0-generate-001",
        "imagen-3.0-generate-002",
        "imagen-4.0-generate-001",
        "imagen-4.0-fast-generate-001",
        "imagen-4.0-ultra-generate-001",
    }
)

BANNED_REASONS: dict[str, str] = {
    "lyria-3-clip-preview": "Genera clips de 30 s. Solo se usa Lyria 3.5.",
    "lyria-3": "Genera clips de 30 s. Solo se usa Lyria 3.5.",
    "lyria-2": "Genera clips de 30 s. Solo se usa Lyria 3.5.",
    "lyria-002": "Genera clips de 30 s. Solo se usa Lyria 3.5.",
}

# --- 2. Video audio --------------------------------------------------------

VIDEO_AUDIO_ALWAYS_DISABLED = True
"""The pista comes from Lyria. Generating audio in Veo would double the price
per second for something the edit throws away."""

# --- 3. Video durations ----------------------------------------------------

VALID_CLIP_DURATIONS: tuple[int, ...] = (4, 6, 8)
MANDATORY_8S_RESOLUTIONS: frozenset[str] = frozenset({"1080p", "4K"})
DEFAULT_CLIP_DURATION = 8
MAX_REFERENCE_IMAGES = 3
VALID_ASPECT_RATIOS: frozenset[str] = frozenset({"16:9", "9:16"})


def assert_not_banned(model_id: str) -> None:
    key = (model_id or "").strip()
    if key in BANNED_MODEL_IDS:
        reason = BANNED_REASONS.get(key, "Modelo excluido del sistema.")
        raise ModelNotAllowed(f"{key} esta prohibido en este sistema. {reason}")


def assert_music_model(model_id: str) -> str:
    """Music generation only ever reaches Lyria 3.5."""
    key = (model_id or "").strip() or MUSIC_MODEL_ID
    assert_not_banned(key)
    if key != MUSIC_MODEL_ID:
        raise ModelNotAllowed(
            f"La musica se genera unicamente con {MUSIC_MODEL_ID}. Se pidio '{key}'."
        )
    return key


def enforce_video_audio_disabled(parameters: dict) -> dict:
    """Return parameters with audio switched off, refusing an explicit request
    to switch it on. Called on every single Veo request."""
    requested = parameters.get("generateAudio", parameters.get("generate_audio", False))
    if requested:
        raise InvalidGenerationRequest(
            "Veo se llama siempre sin audio. La pista sale de Lyria."
        )
    cleaned = {k: v for k, v in parameters.items() if k not in {"generate_audio"}}
    cleaned["generateAudio"] = False
    return cleaned


def resolve_clip_duration(
    duration_seconds: int | None,
    *,
    resolution: str,
    reference_image_count: int = 0,
) -> int:
    """Validate a clip length against what Veo actually accepts."""
    needs_eight = resolution in MANDATORY_8S_RESOLUTIONS or reference_image_count > 0
    if duration_seconds is None:
        # Scenes are designed in 8 second blocks (PRD 23).
        return DEFAULT_CLIP_DURATION
    if duration_seconds not in VALID_CLIP_DURATIONS:
        raise InvalidGenerationRequest(
            f"Veo genera clips de {VALID_CLIP_DURATIONS} segundos. Se pidio {duration_seconds}."
        )
    if needs_eight and duration_seconds != 8:
        why = (
            f"la resolucion {resolution}"
            if resolution in MANDATORY_8S_RESOLUTIONS
            else "el uso de imagenes de referencia"
        )
        raise InvalidGenerationRequest(
            f"Ocho segundos es obligatorio con {why}. Se pidio {duration_seconds}."
        )
    return duration_seconds


def assert_reference_images(count: int, *, maximum: int = MAX_REFERENCE_IMAGES) -> None:
    if count > maximum:
        raise InvalidGenerationRequest(
            f"Veo acepta hasta {maximum} imagenes de referencia por generacion. Se pasaron {count}."
        )


def assert_aspect_ratio(aspect_ratio: str) -> str:
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        raise InvalidGenerationRequest(
            f"Veo solo genera {sorted(VALID_ASPECT_RATIOS)}. Se pidio '{aspect_ratio}'."
        )
    return aspect_ratio


def assert_same_model_on_retry(requested_model: str, retry_model: str) -> None:
    """PRD 37: a failed job retries with the model that was asked for."""
    if requested_model != retry_model:
        raise ModelNotAllowed(
            "Un reintento no puede cambiar de modelo. "
            f"Se pidio '{requested_model}' y se intento '{retry_model}'."
        )
