"""La version simplificada (2026-11): un universo, un artista, su cancion y
su videoclip.

Cada prueba cubre una de las piezas nuevas o quitadas: el estilo visual fijo,
la voz cantada palabra por palabra, los generos combinables que se heredan,
la inspiracion de YouTube analizada por la propia app, la foto subida, que
ya no hay segundo artista posible, y que un proyecto sin MP4 renderizado no
se puede aprobar.
"""

from __future__ import annotations

import pytest

from app.db.repositories import VIDEO_PROJECTS, Repository
from app.domain.enums import CanonStatus

VOZ = {
    "sex": "Mujer",
    "apparent_age": "Unos 25 anos",
    "pitch": "Media, mas bien grave",
    "timbre": "Calida, con un poco de aire",
    "language_accent": "Espanol neutro",
    "singing_style": "Intima en los versos, con fuerza en el coro",
}


def _universo(client, studio, **extra):
    creado = client.post("/api/universes", json={"name": "Nova", **extra}).json()
    studio.jobs.wait_for_idle(20)
    return creado


def _textos_de_imagen(studio) -> str:
    textos = []
    for llamada in studio.calls.all():
        if llamada.method != "generateContent":
            continue
        for parte in llamada.payload["contents"][0]["parts"]:
            if "text" in parte:
                textos.append(parte["text"])
    return "\n".join(textos)


def test_el_estilo_se_guarda_y_llega_al_master_y_a_los_planos(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid, char_id = creado["id"], creado["lead_character_id"]

    guardado = client.put(
        f"/api/universes/{uid}/bible/visual-style", json={"style_key": "oleo"}
    )
    assert guardado.status_code == 200, guardado.text
    assert guardado.json()["style_label"] == "Óleo, pintura clásica"

    # El Master se genera con el estilo dentro del propio encargo.
    trabajo = client.post(
        f"/api/universes/{uid}/characters/{char_id}/master/portrait",
        json={"prompt": "portrait of Nova"},
    )
    assert trabajo.status_code == 200, trabajo.text
    studio.jobs.wait_for_idle(20)
    assert "oil painting" in _textos_de_imagen(studio)

    # Y un plano de escena tambien: el estilo no es solo cosa del retrato.
    from app.orchestrator.handlers import _apply_storyboard

    Repository(studio.db, uid, VIDEO_PROJECTS).create(
        "vp_estilo",
        {"song_id": "song_x", "character_ids": [char_id], "status": "draft", "story": {}},
    )
    _apply_storyboard(
        studio, uid, "vp_estilo",
        {"scenes": [{"index": 0, "character_names": ["Nova"],
                     "image_prompt": "Nova singing", "video_prompt": "push in",
                     "reuses_scene_index": -1}]},
    )
    escena = client.get(f"/api/universes/{uid}/video-projects/vp_estilo").json()["scenes"][0]
    studio.calls.clear()
    trabajo = client.post(
        f"/api/universes/{uid}/scenes/{escena['id']}/image",
        json={"model": "gemini-3-pro-image", "variant": "1K"},
    )
    # Sin storyboard aprobado la imagen no sale; se aprueba y se reintenta.
    if trabajo.status_code != 200:
        client.post(f"/api/universes/{uid}/video-projects/vp_estilo/storyboard/approve")
        trabajo = client.post(
            f"/api/universes/{uid}/scenes/{escena['id']}/image",
            json={"model": "gemini-3-pro-image", "variant": "1K"},
        )
    assert trabajo.status_code == 200, trabajo.text
    studio.jobs.wait_for_idle(20)
    assert "oil painting" in _textos_de_imagen(studio)


def test_cambiar_el_estilo_marca_la_cara_como_desactualizada(client, studio):
    creado = _universo(
        client, studio, gender="mujer", visual_style="realista"
    )
    uid, char_id = creado["id"], creado["lead_character_id"]
    client.post(
        f"/api/universes/{uid}/characters/{char_id}/master/portrait",
        json={"prompt": "portrait of Nova"},
    )
    studio.jobs.wait_for_idle(20)
    client.post(f"/api/universes/{uid}/characters/{char_id}/approve")

    client.put(f"/api/universes/{uid}/bible/visual-style", json={"style_key": "anime_suave"})
    artista = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert artista["master_stale"] is True
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["visual"]["master_stale"] is True
    siguiente = client.get(f"/api/universes/{uid}").json()["siguiente"]
    assert siguiente["clave"] == "rehacer_cara"


def test_la_voz_cantada_viaja_palabra_por_palabra_a_lyria(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid = creado["id"]
    respuesta = client.put(f"/api/universes/{uid}/bible/singing-voice", json=VOZ)
    assert respuesta.status_code == 200, respuesta.text
    texto_voz = respuesta.json()["text"]
    assert "Warm" not in texto_voz and "Timbre: Calida" in texto_voz

    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": "[Verse 1]\nLuces de neon", "author": "user"},
    )
    client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/analyze", json={})
    studio.jobs.wait_for_idle(20)

    # Ya en el concepto: el prompt guardado para Lyria lleva la voz entera,
    # palabra por palabra, aunque el Director la hubiera resumido.
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert texto_voz in guardada["music_prompt"]

    client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/approve")
    studio.calls.clear()
    client.post(f"/api/universes/{uid}/songs/{sid}/generate", json={"duration_seconds": 60})
    studio.jobs.wait_for_idle(20)
    llamadas = studio.calls.for_model_prefix("lyria")
    assert llamadas, "no se llamo a Lyria"
    enviado = llamadas[-1].payload["contents"][0]["parts"][0]["text"]
    assert texto_voz in enviado, "la voz fija no llego entera al encargo de Lyria"


def test_los_generos_se_heredan_y_se_pueden_ajustar_por_cancion(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid = creado["id"]
    client.put(
        f"/api/universes/{uid}/bible/genres",
        json={"music_genres": ["pop", "bachata"], "music_genre_free": "con guitarra de corrido"},
    )

    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    assert cancion["genres"] == ["pop", "bachata"]
    assert cancion["genre_free"] == "con guitarra de corrido"
    assert cancion["genre"] == "Pop + Bachata + con guitarra de corrido"

    # Ajustarla para esta cancion no toca la del artista.
    ajustada = client.patch(
        f"/api/universes/{uid}/songs/{cancion['id']}",
        json={"genres": ["trap"], "genre_free": ""},
    ).json()
    assert ajustada["genres"] == ["trap"]
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["music_genres"] == ["pop", "bachata"]

    # Mas de tres principales no pasan: el cuarto se queda fuera.
    client.put(
        f"/api/universes/{uid}/bible/genres",
        json={"music_genres": ["pop", "rock", "jazz", "metal"]},
    )
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["music_genres"] == ["pop", "rock", "jazz"]


def test_la_inspiracion_de_youtube_alimenta_la_cancion(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid = creado["id"]

    # Un enlace que no es de YouTube no se analiza.
    malo = client.post(
        f"/api/universes/{uid}/bible/inspirations", json={"url": "https://ejemplo.com/x"}
    )
    assert malo.status_code == 422, malo.text

    respuesta = client.post(
        f"/api/universes/{uid}/bible/inspirations",
        json={"url": "https://www.youtube.com/watch?v=abc123XYZ"},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["summary_text"], "el analisis no guardo resumen"

    # El resumen es editable, y lo editado es lo que alimenta la cancion.
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    biblia["inspirations"][0]["summary_text"] = "RESUMEN EDITADO: balada lenta con piano"
    client.put(
        f"/api/universes/{uid}/bible/inspirations",
        json={"inspirations": biblia["inspirations"]},
    )

    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={"brief": "Una despedida"})
    studio.jobs.wait_for_idle(20)
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert "RESUMEN EDITADO: balada lenta con piano" in guardada["music_prompt"]


def test_cada_universo_tiene_un_solo_artista(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid = creado["id"]
    segundo = client.post(f"/api/universes/{uid}/characters", json={"name": "Otro"})
    assert segundo.status_code == 409
    assert "un solo artista" in segundo.json()["error"]["message"]


def test_la_foto_tal_cual_queda_como_master_aprobado(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid, char_id = creado["id"], creado["lead_character_id"]
    respuesta = client.post(
        f"/api/universes/{uid}/characters/{char_id}/photo",
        files={"file": ("cara.jpg", b"\xff\xd8\xff\xe0foto", "image/jpeg")},
        data={"mode": "use_as_master"},
    )
    assert respuesta.status_code == 200, respuesta.text
    artista = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert artista["status"] == CanonStatus.APPROVED.value
    assert artista["reference_image_paths"], "la foto no quedo como referencia aprobada"
    assert artista["source_photo_path"]


def test_la_foto_tambien_aporta_su_estilo(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid, char_id = creado["id"], creado["lead_character_id"]
    respuesta = client.post(
        f"/api/universes/{uid}/characters/{char_id}/photo",
        files={"file": ("estilo.jpg", b"\xff\xd8\xff\xe0foto", "image/jpeg")},
        data={"mode": "copy_style"},
    )
    assert respuesta.status_code == 200, respuesta.text
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["visual"]["style_key"] == "photo"
    assert biblia["visual"]["photo_style_description"], "no se leyo el estilo de la foto"


def test_sin_mp4_renderizado_no_se_aprueba_el_proyecto(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid = creado["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    studio.db.update(
        f"universes/{uid}/songs/{cancion['id']}",
        {"status": CanonStatus.APPROVED.value,
         "approved_master_path": "universes/x/song.wav"},
    )
    proyecto = client.post(
        f"/api/universes/{uid}/video-projects",
        json={"song_id": cancion["id"], "video_type": "narrative"},
    ).json()
    pid = proyecto["id"]

    # Solo el plan de montaje (EDL), sin MP4: no se aprueba.
    studio.db.update(
        f"universes/{uid}/video_projects/{pid}", {"edl_path": "universes/x/edl.json"}
    )
    respuesta = client.post(f"/api/universes/{uid}/video-projects/{pid}/approve")
    assert respuesta.status_code == 409
    assert "MP4" in respuesta.json()["error"]["message"]

    # Con el MP4 renderizado si.
    studio.db.update(
        f"universes/{uid}/video_projects/{pid}",
        {"master_16x9_path": "universes/x/master_16x9.mp4"},
    )
    respuesta = client.post(f"/api/universes/{uid}/video-projects/{pid}/approve")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] == CanonStatus.APPROVED.value


@pytest.mark.parametrize(
    "ruta",
    [
        "content",
        "content/voice-clone",
        "wardrobe",
        "locations",
    ],
)
def test_las_rutas_quitadas_no_existen(client, universe, ruta):
    assert client.get(f"/api/universes/{universe}/{ruta}").status_code == 404
