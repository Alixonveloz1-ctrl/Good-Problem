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
    model: str = "lyria-3-pro-preview",
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

    # Lyria NO tiene endpoint propio y NO usa :predict. Se pide igual que un
    # modelo de imagen de Gemini -:generateContent con responseModalities- y
    # siempre en "global". Llamarlo como se llama a un modelo de prediccion
    # devuelve un 404 que parece decir que el modelo no existe.
    #
    # Y la duracion no es un parametro: se pide dentro del propio texto. El
    # unico campo valido en generationConfig es responseModalities; anadir
    # maxOutputTokens hace que Vertex conteste "invalid argument".
    partes = [_con_duracion(prompt, duration_seconds, lyrics, negative_prompt)]
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": partes[0]}]}],
        "generationConfig": {"responseModalities": ["AUDIO", "TEXT"]},
    }
    if seed is not None:
        payload["generationConfig"]["seed"] = seed

    response = client.call(model_id, "generateContent", payload)
    audio = _juntar_audio(response)
    if audio is None:
        raise ProviderError(
            f"Lyria no devolvio audio ({_motivo(response)}).",
            details={"response": str(response)[:800]},
        )
    datos, mime = audio
    parameters = {"duration_seconds": duration_seconds}

    return AudioResult(
        data=datos,
        mime_type=mime,
        model=model_id,
        duration_seconds=duration_seconds,
        prompt=prompt,
        parameters=parameters,
    )


def _con_duracion(prompt: str, segundos: int, lyrics: str, negative_prompt: str) -> str:
    """El texto que se le manda, con la duracion pedida en prosa.

    Lyria no acepta la duracion como parametro. Si no se le dice en el texto que
    no pare antes, entrega treinta segundos y se queda tan ancho.
    """
    partes = [prompt.strip()]
    partes.append(
        f"LENGTH: this piece must last about {segundos} seconds. "
        "Do NOT stop early and do NOT deliver a 30-second clip."
    )
    if lyrics:
        partes.append(f"LYRICS:\n{lyrics.strip()}")
    if negative_prompt:
        partes.append(f"AVOID: {negative_prompt.strip()}")
    return "\n\n".join(partes)


def _juntar_audio(respuesta: dict[str, Any]) -> tuple[bytes, str] | None:
    """El audio puede volver partido en varios trozos de la MISMA respuesta.

    Hay que pegarlos, y si son WAV cada trozo trae su cabecera RIFF de 44 bytes:
    se conserva la del primero y se quita en los demas, o el archivo sale
    corrupto. Falla solo en las piezas largas, que son justo las que se parten.
    """
    candidatos = respuesta.get("candidates") or []
    if not candidatos:
        return None
    trozos: list[bytes] = []
    mime = ""
    for parte in (candidatos[0].get("content") or {}).get("parts") or []:
        datos = parte.get("inlineData") or parte.get("inline_data") or {}
        crudo = datos.get("data")
        if not crudo:
            continue
        tipo = datos.get("mimeType") or datos.get("mime_type") or ""
        if tipo.startswith("image"):
            continue
        mime = mime or tipo
        bytes_ = base64.b64decode(crudo)
        if trozos and len(bytes_) > 44 and bytes_[:4] == b"RIFF":
            bytes_ = bytes_[44:]
        trozos.append(bytes_)
    if not trozos:
        return None
    return b"".join(trozos), mime or "audio/L16;codec=pcm;rate=24000"


def _motivo(respuesta: dict[str, Any]) -> str:
    """Por que no vino audio: casi siempre un filtro o un limite, y lo dice."""
    candidatos = respuesta.get("candidates") or []
    if not candidatos:
        return "sin respuesta"
    return str(candidatos[0].get("finishReason") or "sin finishReason")
