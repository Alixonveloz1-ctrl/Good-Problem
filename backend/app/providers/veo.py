"""Veo 3.1 (PRD 26).

Three models, picked by the user on every generation. Two rules are enforced
here rather than trusted to callers:

* ``generateAudio`` is false in every request, in every format. The track comes
  from Lyria and the spoken voice from Chirp, so paying Veo for audio would be
  paying twice for something the edit discards. It halves the price per second.
* Clips are 4, 6 or 8 seconds, and 8 whenever the request is 1080p, 4K or uses
  reference images, which is always the case in this pipeline.

Generation is a long running operation: start it, then poll. Jobs keep running
in Google Cloud whether or not the phone stays open (PRD 37).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from ..domain.guards import (
    assert_aspect_ratio,
    assert_extend_supported,
    assert_reference_images,
    enforce_video_audio_disabled,
    resolve_clip_duration,
)
from ..domain.registry import ModelSpec
from ..errors import InvalidGenerationRequest, ProviderError
from .vertex import VertexClient


@dataclass(frozen=True)
class SourceImage:
    data: bytes
    mime_type: str = "image/png"


@dataclass
class VideoOperation:
    name: str
    model: str
    parameters: dict[str, Any] = field(default_factory=dict)
    seconds: int = 8


@dataclass
class VideoResult:
    data: bytes | None
    gcs_uri: str | None
    mime_type: str
    model: str
    seconds: int
    parameters: dict[str, Any] = field(default_factory=dict)


def _image_part(image: SourceImage) -> dict[str, Any]:
    return {
        "bytesBase64Encoded": base64.b64encode(image.data).decode(),
        "mimeType": image.mime_type,
    }


def start_generation(
    client: VertexClient,
    spec: ModelSpec,
    *,
    prompt: str,
    variant: str,
    source_image: SourceImage | None = None,
    reference_images: list[SourceImage] | None = None,
    duration_seconds: int | None = None,
    aspect_ratio: str = "16:9",
    negative_prompt: str = "",
    storage_uri: str | None = None,
    seed: int | None = None,
) -> VideoOperation:
    references = reference_images or []
    assert_reference_images(len(references), maximum=int(spec.cap("reference_images_max", 3)))
    assert_aspect_ratio(aspect_ratio)
    seconds = resolve_clip_duration(
        duration_seconds,
        resolution=variant,
        reference_image_count=len(references) + (1 if source_image else 0),
    )
    if seconds not in spec.cap("durations_seconds", [4, 6, 8]):
        raise ProviderError(f"{spec.id} no genera clips de {seconds} s.")

    instance: dict[str, Any] = {"prompt": prompt}
    if source_image is not None:
        instance["image"] = _image_part(source_image)
    if references:
        instance["referenceImages"] = [
            {"image": _image_part(ref), "referenceType": "asset"} for ref in references
        ]
    if negative_prompt:
        instance["negativePrompt"] = negative_prompt

    parameters: dict[str, Any] = {
        "aspectRatio": aspect_ratio,
        "durationSeconds": seconds,
        "resolution": variant,
        "sampleCount": 1,
        "personGeneration": "allow_adult",
    }
    if storage_uri:
        parameters["storageUri"] = storage_uri
    if seed is not None:
        parameters["seed"] = seed
    # Last thing before the request leaves: audio off, always.
    parameters = enforce_video_audio_disabled(parameters)

    response = client.call(
        spec.id, "predictLongRunning", {"instances": [instance], "parameters": parameters}
    )
    name = response.get("name")
    if not name:
        raise ProviderError(
            "Veo no devolvio una operacion.", details={"response": str(response)[:800]}
        )
    return VideoOperation(name=name, model=spec.id, parameters=parameters, seconds=seconds)


EXTENSION_RESOLUTION = "720p"
"""Veo devuelve la extension siempre a 720p, aunque el clip original sea 1080p
o 4K. Documentado por Google y confirmado por los proveedores que exponen la
API. Forzarlo aqui evita cobrar 1080p por algo que llega a 720p."""

EXTENSION_MAX_TOTAL_SECONDS = 148


def start_extension(
    client: VertexClient,
    spec: ModelSpec,
    *,
    prompt: str,
    video_uri: str,
    aspect_ratio: str = "16:9",
    current_seconds: int = 8,
) -> VideoOperation:
    """Continua un clip ya generado, +7 s cada vez, hasta unos 148 s.

    Tres cosas que conviene tener presentes y que el PRD no recoge:

    * la peticion **no acepta imagenes de referencia**: solo el video anterior y
      un texto. Veo deduce quien es el personaje mirando el ultimo segundo del
      clip, asi que si ahi no se le ve la cara, se la inventa;
    * la salida es siempre 720p, sea cual sea la resolucion del clip original;
    * veo-3.1-lite no la soporta.
    """
    assert_extend_supported(spec.id, supports_extend=bool(spec.cap("supports_extend", False)))
    added = int(spec.cap("extend_seconds", 7))
    total = current_seconds + added
    if total > EXTENSION_MAX_TOTAL_SECONDS:
        raise InvalidGenerationRequest(
            f"Una toma no puede pasar de {EXTENSION_MAX_TOTAL_SECONDS} segundos. "
            f"Esta lleva {current_seconds} y quedaria en {total}."
        )
    parameters = enforce_video_audio_disabled(
        {
            "aspectRatio": assert_aspect_ratio(aspect_ratio),
            "resolution": EXTENSION_RESOLUTION,
            "sampleCount": 1,
            "durationSeconds": added,
        }
    )
    response = client.call(
        spec.id,
        "predictLongRunning",
        {"instances": [{"prompt": prompt, "video": {"gcsUri": video_uri}}],
         "parameters": parameters},
    )
    name = response.get("name")
    if not name:
        raise ProviderError("Veo no devolvio una operacion de extension.")
    return VideoOperation(name=name, model=spec.id, parameters=parameters, seconds=added)


def poll(client: VertexClient, operation: VideoOperation) -> VideoResult | None:
    """Returns None while the operation is still running."""
    response = client.fetch_operation(operation.model, operation.name)
    if not response.get("done"):
        return None
    if response.get("error"):
        raise ProviderError(
            "Veo fallo la generacion.", details={"error": response["error"]}
        )
    payload = response.get("response") or {}
    videos = payload.get("videos") or payload.get("generatedSamples") or []
    if not videos:
        # A dry run reaches here; the caller substitutes a placeholder.
        return VideoResult(
            data=None,
            gcs_uri=None,
            mime_type="video/mp4",
            model=operation.model,
            seconds=operation.seconds,
            parameters=operation.parameters,
        )
    first = videos[0]
    encoded = first.get("bytesBase64Encoded")
    return VideoResult(
        data=base64.b64decode(encoded) if encoded else None,
        gcs_uri=first.get("gcsUri") or (first.get("video") or {}).get("uri"),
        mime_type=first.get("mimeType", "video/mp4"),
        model=operation.model,
        seconds=operation.seconds,
        parameters=operation.parameters,
    )
