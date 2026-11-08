"""Lyria por la API de interacciones: lectura del audio y motivos de fallo.

El proveedor se prueba contra respuestas escritas a mano con la forma de la
API real — la de la documentacion oficial de Lyria y la de la instalacion
hermana que genera piezas largas a diario — y no contra la forma que el
propio codigo espera. Esa fue exactamente la ceguera que dejo pasar el fallo
de la primera generacion real: en seco, la respuesta simulada tenia la misma
forma equivocada que el codigo buscaba, y todo parecia funcionar.
"""

from __future__ import annotations

import base64

import pytest

from app.errors import ProviderError
from app.providers import lyria

MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 413
MP3_B64 = base64.b64encode(MP3).decode()


class ClienteFalso:
    """El transporte minimo que el proveedor necesita, con la respuesta dada."""

    def __init__(self, respuesta):
        self._respuesta = respuesta
        self.llamadas: list[tuple[str, dict]] = []

    def call_interactions(self, model, payload):
        self.llamadas.append((model, payload))
        return self._respuesta


def test_el_audio_se_lee_tambien_desde_steps():
    """La documentacion oficial muestra steps -> content; Drama, outputs."""
    cliente = ClienteFalso(
        {
            "status": "completed",
            "steps": [
                {"content": [{"type": "text", "text": "componiendo"}]},
                {
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg", "data": MP3_B64}
                    ]
                },
            ],
        }
    )
    resultado = lyria.generate_song(cliente, prompt="rap triste", duration_seconds=60)
    assert resultado.data == MP3
    assert resultado.mime_type == "audio/mpeg"


def test_el_texto_que_viaja_es_el_de_siempre():
    """El arreglo cambia la puerta, no el encargo: mismo texto compuesto."""
    cliente = ClienteFalso(
        {
            "status": "completed",
            "outputs": [{"type": "audio", "mime_type": "audio/mpeg", "data": MP3_B64}],
        }
    )
    lyria.generate_song(
        cliente,
        prompt="Base del Director",
        duration_seconds=180,
        lyrics="[Verse]\nMi letra",
        negative_prompt="gritos",
    )
    modelo, payload = cliente.llamadas[-1]
    assert modelo == "lyria-3.5"
    assert payload["model"] == "lyria-3.5"
    texto = payload["input"][0]["text"]
    assert "Base del Director" in texto
    assert "about 180 seconds" in texto
    assert "DICTION" in texto and "syllable by syllable" in texto
    assert "LYRICS:\n[Verse]\nMi letra" in texto
    assert "AVOID: gritos" in texto


def test_sin_audio_el_error_dice_el_motivo_real_de_google():
    """Un bloqueo se lee como bloqueo, nunca como un "sin respuesta" vacio."""
    cliente = ClienteFalso(
        {
            "status": "completed",
            "promptFeedback": {
                "blockReason": "SAFETY",
                "blockReasonMessage": "The prompt was blocked by the safety filter.",
            },
            "outputs": [],
        }
    )
    with pytest.raises(ProviderError) as excinfo:
        lyria.generate_song(cliente, prompt="rap callejero", duration_seconds=120)
    mensaje = str(excinfo.value)
    assert "SAFETY" in mensaje and "bloqueada" in mensaje
    assert "sin respuesta" not in mensaje
    # Y el extracto de la respuesta viaja en los detalles del error.
    assert "SAFETY" in excinfo.value.details["response"]


def test_una_interaccion_sin_completar_no_devuelve_cancion():
    """Si el estado no es completed, no hay pieza aunque viniera algo de audio."""
    cliente = ClienteFalso(
        {
            "status": "failed",
            "error": {"message": "quota exceeded", "code": 429},
            "outputs": [{"type": "audio", "mime_type": "audio/mpeg", "data": MP3_B64}],
        }
    )
    with pytest.raises(ProviderError) as excinfo:
        lyria.generate_song(cliente, prompt="rap", duration_seconds=60)
    mensaje = str(excinfo.value)
    assert "'failed'" in mensaje and "quota exceeded" in mensaje


def test_el_detalle_de_la_respuesta_queda_guardado_en_el_trabajo(client, studio, monkeypatch):
    """El fallo que el dueno lee en la pantalla lleva el motivo de Google.

    Antes el orquestador guardaba solo el titular del error y tiraba los
    detalles del proveedor: el motivo real de un fallo no quedaba en ningun
    sitio. Aqui el proveedor falla con detalles, como falla de verdad, y el
    trabajo guardado tiene que mostrarlos.
    """
    from app.providers import lyria as modulo_lyria

    def falla(cliente, **kwargs):
        raise ProviderError(
            "Lyria no devolvio audio: la peticion fue bloqueada (blockReason: SAFETY).",
            details={"response": "{'promptFeedback': {'blockReason': 'SAFETY'}}"},
        )

    monkeypatch.setattr(modulo_lyria, "generate_song", falla)

    creado = client.post("/api/universes", json={"name": "Nova"}).json()
    uid = creado["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": "[Verse 1]\nLuces de neon", "author": "user"},
    )

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{sid}/generate", json={"duration_seconds": 60}
    )
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)
    trabajo = client.get(f"/api/universes/{uid}/jobs/{respuesta.json()['id']}").json()
    assert trabajo["state"] == "FAILED"
    assert "SAFETY" in trabajo["error"]
    assert "Detalle de la respuesta de Google" in trabajo["error"]
