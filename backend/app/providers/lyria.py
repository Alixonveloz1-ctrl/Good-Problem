"""Lyria: canciones completas por dos puertas (PRD 14).

The only music model in the system. Lyria 3 and Lyria 2 make 30 second clips,
so they are not in the selector and the orchestrator is forbidden from reaching
for them, including as a fallback after a failure. ``assert_music_model`` runs
on every call, which is why that rule cannot be bypassed by passing a different
id from anywhere else in the code.

Lyria 3.5 lives behind Google's other door, and that is proven, not
assumed: on 2026-11-07 the system was switched to ``lyria-3.5`` on the
Vertex door for one real test song and Vertex answered 400, "Model
'lyria-3.5' is not supported by the Interactions API". The switch was
reverted the same day. That evening the owner ordered the second door
opened: when he sets his own Gemini API key in the studio's settings,
music goes out through the Gemini API with that key and sings with
Lyria 3.5; with no key set, music stays on the Vertex door with Lyria
3 Pro. The composed text (prompt, duration, the diction order in
``_con_duracion``, lyrics, fixed voice) is identical on both doors —
only the door and the model change.

Lyria accepts text and reference images but not reference audio, so there is no
way to pin a sung voice. The Voice Profile is text that travels with every
request; it is the best the MVP can do and the PRD accepts that (PRD 4).

The call itself goes through the interactions API (v1beta1, "global"), in the
exact shape the owner's Drama studio uses to generate long Lyria pieces every
day: ``{"model": ..., "input": [{"type": "text", "text": ...}]}``, with the
audio coming back in ``outputs[]`` as MP3. It used to go through the
Gemini-style ``:generateContent`` route with ``responseModalities: [AUDIO]``,
which is not the documented Lyria route in Vertex: the first real generation
(the owner's own song, 180 s) came back HTTP 200 with no candidates at all,
and this provider reported it as "sin respuesta" because it never looked at
why. The dry run could not catch that — it simulated the same wrong shape the
code expected.
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
    gemini_api_key: str = "",
    prompt: str = "",
    duration_seconds: int,
    negative_prompt: str = "",
    seed: int | None = None,
    lyrics: str = "",
) -> AudioResult:
    model_id = assert_music_model(model, gemini=bool(gemini_api_key))
    if duration_seconds <= 0 or duration_seconds > MAX_DURATION_SECONDS:
        raise InvalidGenerationRequest(
            f"Lyria genera canciones de hasta {MAX_DURATION_SECONDS} s. "
            f"Se pidio {duration_seconds}."
        )

    # La puerta es la API de interacciones, no :generateContent ni :predict:
    # el modelo va nombrado dentro del cuerpo y el texto viaja como una
    # entrada de texto, igual que en la instalacion hermana que si genera.
    # Y la duracion no es un parametro: se pide dentro del propio texto. El
    # texto compuesto (prompt + duracion en prosa + letra + voz fija palabra
    # por palabra, que impone el handler) no cambia en una coma.
    #
    # El seed no viaja: la API de interacciones no lo acepta como campo y la
    # referencia que funciona no lo manda. Mandar campos que la API no
    # documenta es como se gana un "invalid argument" el dia del estreno; el
    # seed queda registrado en la procedencia de la version, no en la llamada.
    texto = _con_duracion(prompt, duration_seconds, lyrics, negative_prompt)
    payload: dict[str, Any] = {"model": model_id, "input": [{"type": "text", "text": texto}]}

    if gemini_api_key:
        response = client.call_interactions_gemini_api(model_id, payload, gemini_api_key)
    else:
        response = client.call_interactions(model_id, payload)
    audio = _extraer_audio(response)
    if audio is None:
        raise ProviderError(
            f"Lyria no devolvio audio: {_motivo(response)}.",
            details={"response": str(response)[:800]},
        )
    datos, mime = audio
    parameters = {"duration_seconds": duration_seconds}
    if seed is not None:
        parameters["seed"] = seed

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
        f"LENGTH: sung at the tempo above, this lyric naturally lasts about "
        f"{segundos} seconds. Deliver the whole song at that natural length: "
        "do NOT cut it short, do NOT deliver a 30-second clip and do NOT "
        "stretch it with filler."
    )
    # Ritmo: sin esta orden, Lyria resolvía el choque entre una letra
    # larga y la duración pedida ACELERANDO — la canción salía «a mil
    # por hora» escogiera el dueño el género que escogiera (reporte
    # del 2026-11-07). La orden fija el tempo del género como ley: si
    # el material no cabe a ese tempo, se repite menos el coro; no se
    # canta más rápido. Y si el género ES rápido, rápido canta — pero
    # con el tempo firme, no a la desesperada.
    partes.append(
        "PACING: hold the song's tempo steady from the first line to the "
        "last, with the genre's natural phrasing and its pauses. Never speed "
        "up, compress lines or rush syllables to make the lyrics fit the "
        "length: if the material does not fit at that tempo, repeat the "
        "chorus fewer times instead of singing faster. Sing fast only "
        "where the genre itself is fast — the tempo never moves."
    )
    # Diccion: el cantante comprime silabas para caber en el ritmo y se come
    # letras («cuando» sale «cundo»), unas cinco veces por cancion segun el
    # dueno, que lo oye y lo rechaza. La orden viaja en el propio texto,
    # pegada a la letra, porque es ahi donde el modelo la necesita: palabra
    # completa siempre, y si un verso aprieta, que afloje el tempo en vez
    # de recortar la palabra.
    partes.append(
        "DICTION: sing with crystal-clear diction. Pronounce every word in "
        "full, syllable by syllable. Never swallow, clip or merge syllables "
        "or drop letters to fit the rhythm: if a line feels tight, ease the "
        "tempo instead of cutting the word. Every word of the lyrics must "
        "be heard whole and said correctly."
    )
    if lyrics:
        partes.append(f"LYRICS:\n{lyrics.strip()}")
    if negative_prompt:
        partes.append(f"AVOID: {negative_prompt.strip()}")
    return "\n\n".join(partes)


def _salidas_de_audio(respuesta: dict[str, Any]) -> list[dict[str, Any]]:
    """Every audio-looking item in an interactions response, in both shapes.

    The Drama shape is a flat ``outputs[]``; the official Lyria documentation
    also shows ``steps[] -> content[]``. Both carry the same item:
    ``{"type": "audio", "mime_type": "audio/mpeg", "data": "<base64>"}``.
    """
    salidas: list[dict[str, Any]] = []
    for salida in respuesta.get("outputs") or []:
        if isinstance(salida, dict):
            salidas.append(salida)
    for paso in respuesta.get("steps") or []:
        if not isinstance(paso, dict):
            continue
        for contenido in paso.get("content") or []:
            if isinstance(contenido, dict):
                salidas.append(contenido)
    return [s for s in salidas if s.get("type") == "audio"]


def _extraer_audio(respuesta: dict[str, Any]) -> tuple[bytes, str] | None:
    """The song, if the interaction brought one.

    An interaction that did not complete has no song even if something
    audio-shaped came back — that is the working reference's rule too. And
    the bytes decide the format, not the label: if the content is a WAV
    (RIFF header) it is stored as WAV, whatever the mime claims.
    """
    estado = respuesta.get("status")
    if estado is not None and estado != "completed":
        return None
    for salida in _salidas_de_audio(respuesta):
        crudo = salida.get("data")
        if not crudo:
            continue
        try:
            datos = base64.b64decode("".join(str(crudo).split()))
        except ValueError:
            continue
        if not datos:
            continue
        mime = salida.get("mime_type") or salida.get("mimeType") or ""
        if datos[:4] == b"RIFF":
            mime = "audio/wav"
        return datos, mime or "audio/mpeg"
    return None


def _motivo(respuesta: dict[str, Any]) -> str:
    """Por que no vino audio, dicho con lo que la respuesta trae de verdad.

    Nunca un "sin respuesta" vacio: si Google bloqueo la peticion, si la
    interaccion quedo a medias o si devolvio un error, eso viene escrito en
    la respuesta y es lo que el dueno tiene que leer en la pantalla. La
    primera generacion real se perdio sin saber por que porque nadie miraba
    ``promptFeedback`` y el extracto de la respuesta se tiraba por el camino.
    """
    motivos: list[str] = []
    error = respuesta.get("error")
    if isinstance(error, dict):
        texto = error.get("message") or error.get("status") or error.get("code")
        if texto:
            motivos.append(f"Google devolvio un error: {texto}")
    elif error:
        motivos.append(f"Google devolvio un error: {error}")
    estado = respuesta.get("status")
    if estado is not None and estado != "completed":
        motivos.append(f"la interaccion quedo en estado '{estado}'")
    feedback = respuesta.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        motivo = f"la peticion fue bloqueada (blockReason: {feedback['blockReason']}"
        if feedback.get("blockReasonMessage"):
            motivo += f": {feedback['blockReasonMessage']}"
        motivos.append(motivo + ")")
    for candidato in respuesta.get("candidates") or []:
        if isinstance(candidato, dict) and candidato.get("finishReason"):
            motivos.append(f"finishReason del candidato: {candidato['finishReason']}")
            break
    if not motivos:
        claves = ", ".join(sorted(respuesta.keys())) or "ninguna"
        motivos.append(
            "la respuesta llego sin audio y sin un motivo declarado "
            f"(estado: {estado or 'sin estado'}; claves de la respuesta: {claves})"
        )
    return "; ".join(motivos)
