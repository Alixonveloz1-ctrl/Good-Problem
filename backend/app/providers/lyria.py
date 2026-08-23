"""Lyria 3 Pro (PRD 14).

The only music model in the system. Lyria 3 and Lyria 2 make 30 second clips,
so they are not in the selector and the orchestrator is forbidden from reaching
for them, including as a fallback after a failure. ``assert_music_model`` runs
on every call, which is why that rule cannot be bypassed by passing a different
id from anywhere else in the code.

Lyria accepts text and reference images but not reference audio, so there is no
way to pin a sung voice. The Voice Profile is text that travels with every
request; it is the best the MVP can do and the PRD accepts that (PRD 4).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from ..domain.guards import assert_music_model
from ..errors import InvalidGenerationRequest, ProviderError
from .vertex import VertexClient

MAX_DURATION_SECONDS = 180


@dataclass
class AudioResult:
    data: bytes
    mime_type: str
    model: str
    duration_seconds: int
    prompt: str
    parameters: dict[str, Any] = field(default_factory=dict)


def generate_song(
    client: VertexClient,
    *,
    model: str = "lyria-3-pro",
    prompt: str,
    duration_seconds: int,
    negative_prompt: str = "",
    seed: int | None = None,
    lyrics: str = "",
) -> AudioResult:
    model_id = assert_music_model(model)
    if duration_seconds <= 0 or duration_seconds > MAX_DURATION_SECONDS:
        raise InvalidGenerationRequest(
            f"Lyria 3 Pro genera canciones de hasta {MAX_DURATION_SECONDS} s. "
            f"Se pidio {duration_seconds}."
        )

    instance: dict[str, Any] = {"prompt": prompt}
    if lyrics:
        instance["lyrics"] = lyrics
    if negative_prompt:
        instance["negative_prompt"] = negative_prompt
    if seed is not None:
        instance["seed"] = seed

    parameters = {"duration_seconds": duration_seconds, "sample_count": 1}
    response = client.call(model_id, "predict", {"instances": [instance], "parameters": parameters})

    predictions = response.get("predictions") or []
    if not predictions:
        raise ProviderError("Lyria no devolvio audio.", details={"response": str(response)[:800]})
    first = predictions[0]
    encoded = first.get("bytesBase64Encoded") or first.get("audioContent")
    if not encoded:
        raise ProviderError("La respuesta de Lyria no contiene audio.")
    return AudioResult(
        data=base64.b64decode(encoded),
        mime_type=first.get("mimeType", "audio/wav"),
        model=model_id,
        duration_seconds=duration_seconds,
        prompt=prompt,
        parameters=parameters,
    )
