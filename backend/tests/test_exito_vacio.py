"""La reescritura de la Biblia: que funcione y que nunca falle en
silencio (2026-11).

El caso real que destapo todo: dos trabajos de «Que el Director la
escriba» terminaron LISTO sin cambiar ni una palabra de la Biblia — el
Director devolvio un JSON sin ninguna seccion aplicable y la rama que
lo aplica «fusiono» la nada, subio la version y devolvio exito. Y otro
envio ni siquiera dejo rastro: la peticion murio antes de crear el
trabajo y no habia una sola marca en los registros que dijera si llego.

Tres arreglos, cada uno con su prueba:

1. Exito vacio = fallo visible. Si el Director no devuelve nada
   aplicable —en la Biblia y en el resto de tareas de texto del mismo
   handler, donde el patron era el mismo y encima destructivo—, el
   trabajo queda FAILED con su motivo, y lo que habia queda intacto.
2. Ningun envio muere sin marca: el endpoint anota su entrada y
   submit anota la creacion del trabajo, emparejadas en los registros.
3. La pantalla conserva la misma clave de idempotencia entre intentos
   hasta que un envio tiene exito (probado en frontend/tests, con el
   mecanismo en src/lib/claveEnvio.ts que usa la pantalla).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.domain.enums import JobState
from app.errors import ProviderError
from app.orchestrator.handlers import _apply_director_result
from app.services.context import load_bible

_MENSAJE_BIBLIA = "El Director no devolvió la Biblia: vuelve a intentarlo."


def _director_devuelve(monkeypatch, datos):
    def fake_run(studio, universe_id, model, payload):
        return SimpleNamespace(
            data=datos, text="", prompt_tokens=10, output_tokens=5
        )

    monkeypatch.setattr("app.orchestrator.director.run", fake_run)


def _trabajo_biblia(studio, uid):
    return studio.jobs.create(
        uid,
        kind="text",
        model="gemini-3.1-pro-preview",
        variant="default",
        target_type="artist_bible",
        target_id="current",
        request={"payload": {"task": "artist_bible"}},
        estimated_cost_usd=0.0,
    )


# --- 1. La Biblia: exito vacio = fallo visible -----------------------------


@pytest.mark.parametrize(
    "datos",
    [
        {},
        {"cualquier_otra_cosa": "ruido"},
        {"identity": {}, "musical": {}},
        {"identity": "no es una seccion", "visual": []},
    ],
)
def test_el_director_que_no_devuelve_biblia_es_un_fallo_visible(
    studio, universe, monkeypatch, datos
):
    """La forma exacta del caso real: el trabajo corrio, el Director no
    trajo ninguna seccion aplicable, y antes eso era LISTO con la
    Biblia «reescrita». Ahora es FAILED con el motivo, y la Biblia
    queda palabra por palabra como estaba, version incluida."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = load_bible(studio.db, uid)

    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.FAILED.value
    assert resultado["error"] == _MENSAJE_BIBLIA
    despues = load_bible(studio.db, uid)
    assert despues.model_dump() == antes.model_dump()


def test_una_biblia_de_verdad_sigue_terminando_bien(studio, universe, monkeypatch):
    """La guardia no puede convertirse en otra puerta: con una seccion
    de verdad, el trabajo termina LISTO, la Biblia se actualiza y la
    version sube, como siempre."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = load_bible(studio.db, uid)

    _director_devuelve(
        monkeypatch, {"identity": {"personality": "Una personalidad nueva"}}
    )
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.identity.personality == "Una personalidad nueva"
    assert despues.version == antes.version + 1


# --- 1b. El mismo patron en las demas tareas de texto ----------------------


def _cancion(studio, uid, **extra):
    datos = {
        "id": "song_x",
        "universe_id": uid,
        "title": "Neon",
        "concept": {"concept": "el concepto de antes", "mood": "calido"},
        "lyrics": "la letra de antes",
        **extra,
    }
    studio.db.set(f"universes/{uid}/songs/song_x", datos)
    return datos


def test_el_concepto_vacio_no_pisa_el_que_habia(studio, universe):
    uid = universe
    _cancion(studio, uid)
    with pytest.raises(ProviderError, match="no devolvió el concepto"):
        _apply_director_result(
            studio, uid, {"target_id": "song_x", "request": {"payload": {}}},
            "music_concept", {},
        )
    guardada = studio.db.get(f"universes/{uid}/songs/song_x")
    assert guardada["concept"]["concept"] == "el concepto de antes"


def test_la_letra_vacia_no_borra_la_que_habia(studio, universe):
    uid = universe
    _cancion(studio, uid)
    for datos in ({}, {"lyrics": "   "}):
        with pytest.raises(ProviderError, match="no devolvió la letra"):
            _apply_director_result(
                studio, uid, {"target_id": "song_x", "request": {"payload": {}}},
                "lyrics", datos,
            )
    guardada = studio.db.get(f"universes/{uid}/songs/song_x")
    assert guardada["lyrics"] == "la letra de antes"


def test_el_video_concept_vacio_es_un_fallo(studio, universe):
    uid = universe
    studio.db.set(
        f"universes/{uid}/video_projects/vp_x",
        {"id": "vp_x", "universe_id": uid, "concept": "el de antes"},
    )
    with pytest.raises(ProviderError, match="no devolvió el concepto del video"):
        _apply_director_result(
            studio, uid, {"target_id": "vp_x", "request": {"payload": {}}},
            "video_concept", {},
        )
    guardado = studio.db.get(f"universes/{uid}/video_projects/vp_x")
    assert guardado["concept"] == "el de antes"


def test_el_storyboard_vacio_no_borra_las_escenas(studio, universe):
    """El mas destructivo: la rama sustituye el storyboard entero, asi
    que un resultado vacio borraba las escenas y dejaba el proyecto
    «en uso» sin una sola. Ahora falla antes de tocar nada."""
    uid = universe
    studio.db.set(
        f"universes/{uid}/video_projects/vp_x",
        {"id": "vp_x", "universe_id": uid, "character_ids": []},
    )
    studio.db.set(
        f"universes/{uid}/scenes/scene_1",
        {"id": "scene_1", "universe_id": uid, "project_id": "vp_x"},
    )
    for datos in ({}, {"scenes": []}):
        with pytest.raises(ProviderError, match="no devolvió el storyboard"):
            _apply_director_result(
                studio, uid, {"target_id": "vp_x", "request": {"payload": {}}},
                "storyboard", datos,
            )
    assert studio.db.get(f"universes/{uid}/scenes/scene_1") is not None


def test_el_personaje_vacio_es_un_fallo(studio, universe):
    uid = universe
    with pytest.raises(ProviderError, match="no devolvió el personaje"):
        _apply_director_result(
            studio, uid, {"target_id": "char_x", "request": {"payload": {}}},
            "character", {},
        )


# --- 2. Ningun envio muere sin marca ----------------------------------------


def test_el_encargo_de_la_biblia_deja_sus_dos_marcas(client, studio, caplog):
    """La entrada del endpoint y la creacion del trabajo, emparejadas:
    con estas dos lineas se sabe en una mirada si la peticion llego y
    que trabajo creo — lo que no se pudo saber el dia que un envio
    desaparecio sin dejar ni el trabajo ni un error."""
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    studio.jobs.wait_for_idle(20)

    with caplog.at_level(logging.INFO):
        respuesta = client.post(
            f"/api/universes/{uid}/bible/generate",
            json={"brief": "Rap nocturno", "idempotency_key": "clave-de-la-prueba"},
        )
    assert respuesta.status_code == 200, respuesta.text
    trabajo_id = respuesta.json()["id"]

    mensajes = [registro.getMessage() for registro in caplog.records]
    assert any(
        "generate_bible" in mensaje and uid in mensaje and "presente" in mensaje
        for mensaje in mensajes
    ), mensajes
    assert any(
        "job_created" in mensaje and trabajo_id in mensaje for mensaje in mensajes
    ), mensajes
    studio.jobs.wait_for_idle(20)
