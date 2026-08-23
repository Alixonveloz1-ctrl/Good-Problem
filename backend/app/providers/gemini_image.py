"""Gemini Image (PRD 24).

Three models, chosen by the user on every generation. The registry holds the
prices and the reference limits; this module refuses a request that would
silently drop the character references, because those references are the only
thing keeping the artist looking like the same person (PRD 18).

Imagen is not here on purpose: it never accepted reference images and its
endpoints were shut down on 2026-08-17.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Literal

from ..domain.registry import ModelSpec
from ..errors import InvalidGenerationRequest, ProviderError
from .vertex import VertexClient

ReferenceKind = Literal["character", "object", "style"]


@dataclass(frozen=True)
class ReferenceImage:
    data: bytes
    mime_type: str = "image/png"
    kind: ReferenceKind = "character"
    label: str = ""


@dataclass
class ImageResult:
    data: bytes
    mime_type: str
    model: str
    variant: str
    prompt: str
    references: list[str]
    parameters: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int = 0


def check_references(spec: ModelSpec, references: list[ReferenceImage]) -> None:
    limits = {
        "character": int(spec.cap("reference_characters_max", 0)),
        "object": int(spec.cap("reference_objects_max", 0)),
        "style": int(spec.cap("reference_styles_max", 0)),
    }
    counts: dict[str, int] = {"character": 0, "object": 0, "style": 0}
    for ref in references:
        counts[ref.kind] += 1
    for kind, used in counts.items():
        allowed = limits[kind]
        if used == 0:
            continue
        if allowed == 0:
            raise InvalidGenerationRequest(
                f"{spec.label} ({spec.id}) no acepta referencias de {kind}. "
                "Elige otro modelo o quita esas referencias."
            )
        if used > allowed:
            raise InvalidGenerationRequest(
                f"{spec.label} acepta {allowed} referencia(s) de {kind}; se pasaron {used}."
            )


def generate(
    client: VertexClient,
    spec: ModelSpec,
    *,
    prompt: str,
    variant: str,
    references: list[ReferenceImage] | None = None,
    aspect_ratio: str = "16:9",
    negative_prompt: str = "",
) -> ImageResult:
    references = references or []
    check_references(spec, references)
    if variant not in spec.cap("resolutions", [variant]):
        raise InvalidGenerationRequest(
            f"{spec.id} no genera a {variant}. Resoluciones: {spec.cap('resolutions')}."
        )

    parts: list[dict[str, Any]] = [{"text": _compose_prompt(prompt, negative_prompt)}]
    for ref in references:
        parts.append(
            {
                "inlineData": {
                    "mimeType": ref.mime_type,
                    "data": base64.b64encode(ref.data).decode(),
                }
            }
        )

    parameters = {
        "responseModalities": ["IMAGE"],
        "imageConfig": {"imageSize": variant, "aspectRatio": aspect_ratio},
    }
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": parameters,
    }
    response = client.call(spec.id, "generateContent", payload)

    blob = _first_inline_image(response)
    if blob is None:
        raise ProviderError(
            f"{spec.id} no devolvio ninguna imagen.", details={"response": str(response)[:1000]}
        )
    data, mime = blob
    usage = response.get("usageMetadata", {})
    return ImageResult(
        data=data,
        mime_type=mime,
        model=spec.id,
        variant=variant,
        prompt=prompt,
        references=[ref.label or ref.kind for ref in references],
        parameters=parameters,
        prompt_tokens=int(usage.get("promptTokenCount", 0)),
    )


def _compose_prompt(prompt: str, negative_prompt: str) -> str:
    if not negative_prompt:
        return prompt
    return f"{prompt}\n\nAvoid: {negative_prompt}"


def _first_inline_image(response: dict[str, Any]) -> tuple[bytes, str] | None:
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return base64.b64decode(inline["data"]), mime
    return None
