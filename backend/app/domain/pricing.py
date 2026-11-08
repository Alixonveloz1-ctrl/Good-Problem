"""Cost estimation (PRD 27, 28, 44).

Video is billed per second of generated video. The Vertex console labels the
unit "1 count", which reads as "per video" but is not: an 8 second clip at
$0.05 bills $0.40. That single misreading is worth more than every other line
of the budget put together, so the arithmetic lives in one place and is tested.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import InvalidGenerationRequest
from .enums import ModelKind
from .registry import ModelRegistry, ModelSpec, Variant


@dataclass(frozen=True)
class CostEstimate:
    amount_usd: float
    unit: str
    quantity: float
    model: str
    variant: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "amount_usd": round(self.amount_usd, 4),
            "unit": self.unit,
            "quantity": self.quantity,
            "model": self.model,
            "variant": self.variant,
            "detail": self.detail,
        }


def _price_for(spec: ModelSpec, variant: Variant, quantity: float) -> float:
    if variant.unit == "second":
        return variant.price * quantity
    if variant.unit == "image":
        return variant.price * quantity
    if variant.unit == "song":
        return variant.price * quantity
    if variant.unit == "1m_characters":
        return variant.price * (quantity / 1_000_000)
    if variant.unit == "1m_tokens":
        # Input and output are priced differently; there is no single number to
        # multiply by. estimate_text handles this unit.
        raise InvalidGenerationRequest(
            f"Usa estimate_text para {spec.id}: los tokens de entrada y salida tienen precios "
            "distintos."
        )
    return variant.price * quantity


def estimate(
    registry: ModelRegistry,
    model_id: str,
    variant_key: str | None,
    quantity: float,
    *,
    detail: str = "",
) -> CostEstimate:
    spec = registry.get(model_id)
    variant = spec.variant(variant_key)
    return CostEstimate(
        amount_usd=_price_for(spec, variant, quantity),
        unit=variant.unit,
        quantity=quantity,
        model=spec.id,
        variant=variant.key,
        detail=detail,
    )


def estimate_video(
    registry: ModelRegistry,
    model_id: str,
    variant_key: str | None,
    *,
    seconds: int,
    clips: int = 1,
) -> CostEstimate:
    """Seconds are per clip. Total = price per second x seconds x clips."""
    spec = registry.require_active(model_id, ModelKind.VIDEO)
    variant = spec.variant(variant_key)
    total_seconds = seconds * clips
    return CostEstimate(
        amount_usd=variant.price * total_seconds,
        unit="second",
        quantity=total_seconds,
        model=spec.id,
        variant=variant.key,
        detail=f"{clips} clip(s) x {seconds}s x ${variant.price:.2f}/s, sin audio",
    )


def estimate_images(
    registry: ModelRegistry, model_id: str, variant_key: str | None, *, images: int
) -> CostEstimate:
    spec = registry.require_active(model_id, ModelKind.IMAGE)
    variant = spec.variant(variant_key)
    return CostEstimate(
        amount_usd=variant.price * images,
        unit="image",
        quantity=images,
        model=spec.id,
        variant=variant.key,
        detail=f"{images} imagen(es) x ${variant.price:.3f}",
    )


def estimate_song(
    registry: ModelRegistry, *, attempts: int = 1, model_id: str | None = None
) -> CostEstimate:
    spec = (
        registry.require_active(model_id, ModelKind.MUSIC)
        if model_id
        else registry.music_model()
    )
    variant = spec.variant(None)
    return CostEstimate(
        amount_usd=variant.price * attempts,
        unit="song",
        quantity=attempts,
        model=spec.id,
        variant=variant.key,
        detail=f"{attempts} intento(s) x ${variant.price:.2f}",
    )


def estimate_text(
    registry: ModelRegistry,
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
) -> CostEstimate:
    spec = registry.require_active(model_id, ModelKind.TEXT)
    variant = spec.variant(None)
    amount = (
        variant.price_input * (input_tokens / 1_000_000)
        + variant.price_output * (output_tokens / 1_000_000)
    )
    return CostEstimate(
        amount_usd=amount,
        unit="1m_tokens",
        quantity=input_tokens + output_tokens,
        model=spec.id,
        variant=variant.key,
        detail=f"{input_tokens} in / {output_tokens} out",
    )


def estimate_speech(
    registry: ModelRegistry, model_id: str, *, characters: int
) -> CostEstimate:
    spec = registry.require_active(model_id, ModelKind.SPEECH)
    variant = spec.variant(None)
    return CostEstimate(
        amount_usd=variant.price * (characters / 1_000_000),
        unit="1m_characters",
        quantity=characters,
        model=spec.id,
        variant=variant.key,
        detail=f"{characters} caracteres",
    )
