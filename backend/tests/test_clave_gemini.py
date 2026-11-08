"""La clave de Gemini del dueno y la segunda puerta de la musica (2026-11-07).

El dueno oyo la misma letra cantada por la aplicacion de Gemini — sin
un solo corte — y por su estudio — con la voz cortada — y ordeno abrir
la segunda puerta: con SU clave de Gemini, la musica pasa a Lyria 3.5
por la API de Gemini. Sin clave, todo sigue como estaba: Lyria 3 Pro
por Vertex.

La clave vive como VARIABLE DE ENTORNO del servicio
(AAUS_GEMINI_API_KEY), puesta una sola vez por el dueno en la consola
de Google Cloud escribiendola el mismo. Rechazo el campo dentro de la
app la misma noche en que se construyo: la app no guarda claves, solo
sabe si la variable esta puesta.

Lo que estas pruebas fijan:
- sin clave en el entorno, la musica es lyria-3-pro-preview por Vertex;
- con la clave en el entorno, el trabajo se genera con lyria-3.5 por
  la puerta de Gemini, con el mismo encargo (diccion incluida);
- la clave NO sale por ningun GET, ni siquiera tapada: los ajustes
  solo dicen si esta puesta;
- la app no ofrece forma de escribir la clave (no hay endpoint);
- el proveedor se niega a mezclar puertas: modelo de una puerta con
  el transporte de la otra es un error, no una sustitucion silenciosa.
"""

from __future__ import annotations

import pytest

from app.errors import ModelNotAllowed
from app.providers import lyria

CLAVE = "<redacted>"
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


def test_con_clave_en_el_entorno_la_musica_es_lyria_35_y_la_clave_no_sale(
    client, studio
):
    # La variable de entorno del servicio, como queda en produccion.
    studio.settings.gemini_api_key = CLAVE
    uid = _universo(client, studio)
    sid = _cancion_con_letra(client, studio, uid)

    # Los ajustes solo dicen si esta puesta; la clave no sale por
    # ningun GET, ni en ajustes ni en la cuenta.
    assert client.get("/api/settings").json() == {"gemini_key_configured": True}
    for ruta in ("/api/settings", "/api/me", "/api/health"):
        respuesta = client.get(ruta)
        assert CLAVE not in respuesta.text, ruta

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


def test_la_app_no_ofrece_forma_de_escribir_la_clave(client, studio):
    puesta = client.put("/api/settings/gemini-key", json={"api_key": CLAVE})
    assert puesta.status_code in (404, 405), puesta.text
    quitada = client.delete("/api/settings/gemini-key")
    assert quitada.status_code in (404, 405), quitada.text
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
