"""La clave de Gemini del dueno y la segunda puerta de la musica (2026-11-07).

El dueno oyo la misma letra cantada por la aplicacion de Gemini — sin
un solo corte — y por su estudio — con la voz cortada — y ordeno abrir
la segunda puerta: el pone SU clave de Gemini en Ajustes y la musica
pasa a Lyria 3.5 por la API de Gemini. Sin clave, todo sigue como
estaba: Lyria 3 Pro por Vertex.

Lo que estas pruebas fijan:
- la clave se guarda y NO vuelve a salir por ningun GET, ni tapada;
- con la clave puesta, el trabajo de musica se resuelve y se genera
  con lyria-3.5, la llamada va a la puerta de Gemini y la clave no
  viaja en el cuerpo registrado;
- sin clave (o tras quitarla), la musica vuelve a lyria-3-pro-preview
  por Vertex;
- una clave vacia se rechaza a la vista;
- el proveedor se niega a mezclar puertas: modelo de una puerta con
  el transporte de la otra es un error, no una sustitucion silenciosa.
"""

from __future__ import annotations

import pytest

from app.errors import ModelNotAllowed
from app.providers import lyria

CLAVE = "AIza-clave-de-prueba-del-dueno-1234567890"
URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _universo(client, studio):
    creado = client.post("/api/universes", json={"name": "Nova"}).json()
    studio.jobs.wait_for_idle(20)
    return creado["id"]


def _cancion_con_letra(client, studio, uid):
    cancion = client.post(
        f"/api/universes/{uid}/songs", json={"title": "Neon"}
    ).json()
    sid = cancion["id"]
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": "una letra de prueba, con su rima puesta", "author": "user"},
    )
    return sid


def _generar(client, studio, uid, sid):
    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/generate", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)
    return client.get(f"/api/universes/{uid}/songs/{sid}").json()


def _llamadas_musica(studio):
    return [c for c in studio.calls.all() if c.method == "interactions"]


def test_sin_clave_la_musica_es_lyria_3_pro_por_vertex(client, studio):
    uid = _universo(client, studio)
    sid = _cancion_con_letra(client, studio, uid)
    assert client.get("/api/settings").json() == {"gemini_key_configured": False}

    cancion = _generar(client, studio, uid, sid)
    assert cancion["versions"][-1]["model"] == "lyria-3-pro-preview"
    llamada = _llamadas_musica(studio)[-1]
    assert llamada.model == "lyria-3-pro-preview"
    assert "aiplatform.googleapis.com" in llamada.url


def test_con_clave_la_musica_es_lyria_35_por_gemini_y_la_clave_no_sale(
    client, studio
):
    uid = _universo(client, studio)
    sid = _cancion_con_letra(client, studio, uid)

    puesta = client.put("/api/settings/gemini-key", json={"api_key": CLAVE})
    assert puesta.status_code == 200, puesta.text
    assert puesta.json() == {"gemini_key_configured": True}
    assert CLAVE not in puesta.text

    # La clave no sale por ningun GET: ni en ajustes ni en la cuenta.
    for ruta in ("/api/settings", "/api/me", "/api/health"):
        respuesta = client.get(ruta)
        assert CLAVE not in respuesta.text, ruta
    assert client.get("/api/settings").json() == {"gemini_key_configured": True}

    cancion = _generar(client, studio, uid, sid)
    assert cancion["versions"][-1]["model"] == "lyria-3.5"
    llamada = _llamadas_musica(studio)[-1]
    assert llamada.model == "lyria-3.5"
    assert llamada.url == URL_GEMINI
    # La clave viaja en la cabecera, nunca en el cuerpo registrado.
    assert CLAVE not in str(llamada.payload)
    # Y el encargo es el de siempre: la orden de diccion sigue puesta.
    texto = llamada.payload["input"][0]["text"]
    assert "DICTION:" in texto


def test_quitar_la_clave_devuelve_la_musica_a_vertex(client, studio):
    uid = _universo(client, studio)
    sid = _cancion_con_letra(client, studio, uid)
    client.put("/api/settings/gemini-key", json={"api_key": CLAVE})
    _generar(client, studio, uid, sid)

    quitada = client.delete("/api/settings/gemini-key")
    assert quitada.status_code == 200, quitada.text
    assert quitada.json() == {"gemini_key_configured": False}

    cancion = _generar(client, studio, uid, sid)
    assert cancion["versions"][-1]["model"] == "lyria-3-pro-preview"


def test_clave_vacia_se_rechaza(client, studio):
    respuesta = client.put("/api/settings/gemini-key", json={"api_key": "   "})
    assert respuesta.status_code == 400
    assert client.get("/api/settings").json() == {"gemini_key_configured": False}


# --- El proveedor no mezcla puertas -----------------------------------------


class ClienteDosPuertas:
    def __init__(self):
        self.puerta = None

    def call_interactions(self, model, payload):
        self.puerta = "vertex"
        return {
            "status": "completed",
            "outputs": [
                {"type": "audio", "mime_type": "audio/mpeg", "data": "AAAA"}
            ],
        }

    def call_interactions_gemini_api(self, model, payload, api_key):
        self.puerta = "gemini"
        return {
            "status": "completed",
            "outputs": [
                {"type": "audio", "mime_type": "audio/mpeg", "data": "AAAA"}
            ],
        }


def test_el_proveedor_usa_la_puerta_de_la_clave():
    cliente = ClienteDosPuertas()
    resultado = lyria.generate_song(
        cliente,
        model="lyria-3.5",
        gemini_api_key=CLAVE,
        prompt="trap oscuro",
        duration_seconds=60,
        lyrics="una letra",
    )
    assert cliente.puerta == "gemini"
    assert resultado.model == "lyria-3.5"


def test_el_proveedor_se_niega_a_mezclar_puertas():
    cliente = ClienteDosPuertas()
    with pytest.raises(ModelNotAllowed):
        lyria.generate_song(
            cliente,
            model="lyria-3-pro-preview",
            gemini_api_key=CLAVE,
            prompt="trap",
            duration_seconds=60,
        )
    with pytest.raises(ModelNotAllowed):
        lyria.generate_song(
            cliente, model="lyria-3.5", prompt="trap", duration_seconds=60
        )
