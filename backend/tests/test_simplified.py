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
    # La imagen sale sin aprobar el storyboard: la escena existe y eso
    # basta. (El reintento queda por si el trabajo fallara por otra cosa.)
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
    # La peticion viaja por la API de interacciones: el texto va en input[0].
    enviado = llamadas[-1].payload["input"][0]["text"]
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


def test_el_proyecto_esta_terminado_cuando_existe_su_mp4(client, studio):
    """Terminado es un estado derivado, no un gesto: el proyecto esta
    completo cuando su MP4 renderizado existe. Aprobarlo no existe; el
    viejo endpoint queda como no-op que no marca nada."""
    creado = _universo(client, studio, gender="mujer")
    uid = creado["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    # La cancion tiene audio: eso es todo lo que el videoclip necesita de
    # ella. Ningun estado de aprobacion interviene.
    studio.db.update(
        f"universes/{uid}/songs/{cancion['id']}",
        {"approved_master_path": "universes/x/song.wav"},
    )
    proyecto = client.post(
        f"/api/universes/{uid}/video-projects",
        json={"song_id": cancion["id"], "video_type": "narrative"},
    ).json()
    pid = proyecto["id"]

    # Solo el plan de montaje (EDL), sin MP4: el proyecto NO esta terminado.
    studio.db.update(
        f"universes/{uid}/video_projects/{pid}", {"edl_path": "universes/x/edl.json"}
    )
    estado = client.get(f"/api/universes/{uid}/video-projects/{pid}").json()
    assert not estado.get("master_16x9_path")
    respuesta = client.post(f"/api/universes/{uid}/video-projects/{pid}/approve")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] != CanonStatus.APPROVED.value

    # Con el MP4 renderizado, esta completo por el hecho de que el archivo
    # existe, sin aprobar nada.
    studio.db.update(
        f"universes/{uid}/video_projects/{pid}",
        {"master_16x9_path": "universes/x/master_16x9.mp4"},
    )
    estado = client.get(f"/api/universes/{uid}/video-projects/{pid}").json()
    assert estado["master_16x9_path"] == "universes/x/master_16x9.mp4"


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


# --- El rostro sigue a los rasgos, y lo generado nace aprobado --------------
#
# Dos reglas del dueno, aprendidas con un artista real: si cambia los rasgos
# del artista con los selectores, la siguiente cara tiene que pedirse con los
# rasgos nuevos (el texto viejo de la ficha pedia la cara vieja y salia la
# misma); y lo que se genera queda aprobado y en uso en el acto, sin pasos
# de revision ni de adopcion (si no le gusta, regenera).

APARIENCIA_VIEJA = (
    "Hombre latino de 29 anos, barba recortada, tatuajes en el cuello y las manos."
)


def _generar_retrato(client, studio, uid, char_id):
    respuesta = client.post(
        f"/api/universes/{uid}/characters/{char_id}/master/portrait", json={}
    )
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)


def test_el_retrato_se_pide_con_los_rasgos_actuales_tras_cambiarlos(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    # La ficha nace como nacio la real: el texto largo describe los rasgos
    # de entonces y los selectores dicen lo mismo.
    client.patch(
        f"/api/universes/{uid}/characters/{char_id}",
        json={
            "appearance": APARIENCIA_VIEJA,
            "rasgos": {
                "edad": "29",
                "vello_facial": "barba recortada",
                "detalles": "tatuajes en el cuello y las manos",
            },
        },
    )
    studio.calls.clear()
    _generar_retrato(client, studio, uid, char_id)
    assert "Exact age: 29" in _textos_de_imagen(studio)

    # El usuario cambia los rasgos con los selectores. Nadie reescribe el
    # texto largo: sigue diciendo 29, barba recortada, cuello y manos.
    client.patch(
        f"/api/universes/{uid}/characters/{char_id}",
        json={
            "rasgos": {
                "edad": "21",
                "vello_facial": "barba cerrada",
                "detalles": "tatuajes en los brazos",
            }
        },
    )
    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert ficha["appearance"] == APARIENCIA_VIEJA

    # Y aun asi, la regeneracion se pide con los rasgos nuevos, declarados
    # como los que mandan sobre la descripcion anterior.
    studio.calls.clear()
    _generar_retrato(client, studio, uid, char_id)
    pedido = _textos_de_imagen(studio)
    assert "Exact age: 21" in pedido
    assert "barba cerrada" in pedido
    assert "tatuajes en los brazos" in pedido
    assert "override any earlier description" in pedido


def test_la_imagen_generada_queda_aprobada_y_en_uso_sin_aprobar_a_mano(client, studio):
    creado = _universo(client, studio, gender="mujer")
    uid, char_id = creado["id"], creado["lead_character_id"]

    _generar_retrato(client, studio, uid, char_id)

    # Sin tocar ningun boton de aprobar: el artista ya esta aprobado, el
    # retrato es su referencia en uso y no queda marcado desactualizado.
    artista = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert artista["status"] == CanonStatus.APPROVED.value
    retrato = next(s for s in artista["master_shots"] if s["key"] == "portrait")
    assert retrato["storage_path"]
    assert retrato["status"] == CanonStatus.APPROVED.value
    assert artista["reference_image_paths"] == [retrato["storage_path"]]
    assert artista["master_stale"] is False


def test_master_aprobado_se_regenera_y_sigue_aprobado_y_en_uso(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]

    _generar_retrato(client, studio, uid, char_id)
    aprobado = client.post(f"/api/universes/{uid}/characters/{char_id}/approve")
    assert aprobado.status_code == 200, aprobado.text
    antes = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert antes["status"] == CanonStatus.APPROVED.value
    referencias_antes = list(antes["reference_image_paths"])
    historial_antes = len(antes.get("approval_history") or [])

    # Regenerar con el Master ya aprobado: la toma nueva lo sustituye y el
    # artista sigue aprobado y en uso, sin volver a aprobar nada a mano.
    _generar_retrato(client, studio, uid, char_id)
    despues = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert despues["status"] == CanonStatus.APPROVED.value
    retrato = next(s for s in despues["master_shots"] if s["key"] == "portrait")
    assert retrato["status"] == CanonStatus.APPROVED.value
    assert despues["reference_image_paths"] == referencias_antes
    assert len(despues.get("approval_history") or []) > historial_antes


# --- Toda toma se apoya en el rostro ---------------------------------------
#
# Regla del dueno: la primera ficha, el Portrait, es la que fija la cara, y
# TODAS las demas tomas tienen que tomarla como referencia visual para que
# sea el mismo rostro en cada angulo. Solo con el texto, cada toma
# reinterpretaba la cara. Lo garantiza el servidor en el payload del trabajo,
# no el cliente.


def _generar_toma(client, uid, char_id, toma, **extra):
    respuesta = client.post(
        f"/api/universes/{uid}/characters/{char_id}/master/{toma}", json=extra
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _ruta_del_retrato(client, uid, char_id):
    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    retrato = next(s for s in ficha["master_shots"] if s["key"] == "portrait")
    return retrato["storage_path"]


def test_otra_toma_lleva_el_retrato_como_referencia(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    _generar_retrato(client, studio, uid, char_id)
    ruta_retrato = _ruta_del_retrato(client, uid, char_id)
    assert ruta_retrato

    # El cliente no manda ninguna referencia (asi llama hoy la vista) y aun
    # asi el trabajo sale con el retrato como referencia: lo pone el servidor.
    trabajo = _generar_toma(client, uid, char_id, "full_body")
    assert trabajo["request"]["payload"]["reference_paths"] == [ruta_retrato]
    studio.jobs.wait_for_idle(20)

    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    cuerpo = next(s for s in ficha["master_shots"] if s["key"] == "full_body")
    assert cuerpo["storage_path"]


def test_el_retrato_no_se_adjunta_a_si_mismo(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    _generar_retrato(client, studio, uid, char_id)
    ruta_retrato = _ruta_del_retrato(client, uid, char_id)

    # Regenerar el retrato ya existiendo su imagen: el trabajo no lleva su
    # propia ruta como referencia; el retrato nace del texto.
    trabajo = _generar_toma(client, uid, char_id, "portrait")
    assert ruta_retrato not in trabajo["request"]["payload"]["reference_paths"]
    studio.jobs.wait_for_idle(20)


def test_sin_retrato_previo_la_toma_sigue_sin_referencias(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]

    # Sin retrato todavia no hay cara que copiar: la toma se genera como
    # siempre, sin referencias y sin error.
    trabajo = _generar_toma(client, uid, char_id, "full_body")
    assert trabajo["request"]["payload"]["reference_paths"] == []
    studio.jobs.wait_for_idle(20)
    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    cuerpo = next(s for s in ficha["master_shots"] if s["key"] == "full_body")
    assert cuerpo["storage_path"]


def test_el_retrato_va_primero_y_no_se_duplica(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    _generar_retrato(client, studio, uid, char_id)
    ruta_retrato = _ruta_del_retrato(client, uid, char_id)

    # Si el cliente manda otra referencia, el retrato va incluido y primero.
    _generar_toma(client, uid, char_id, "full_body")
    studio.jobs.wait_for_idle(20)
    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    ruta_cuerpo = next(
        s for s in ficha["master_shots"] if s["key"] == "full_body"
    )["storage_path"]
    trabajo = _generar_toma(
        client, uid, char_id, "profile", reference_paths=[ruta_cuerpo]
    )
    assert trabajo["request"]["payload"]["reference_paths"] == [
        ruta_retrato,
        ruta_cuerpo,
    ]
    studio.jobs.wait_for_idle(20)

    # Y si el cliente ya mando el retrato, no se duplica.
    trabajo = _generar_toma(
        client, uid, char_id, "profile", reference_paths=[ruta_retrato]
    )
    assert trabajo["request"]["payload"]["reference_paths"] == [ruta_retrato]
    studio.jobs.wait_for_idle(20)


def test_la_version_de_la_toma_sube_en_cada_regeneracion(client, studio):
    """La regeneracion sobrescribe la misma ruta canonica: lo unico que
    distingue la imagen nueva de la vieja es la version de la toma, que es
    la marca que la vista pone en la URL para no ensenar la copia guardada
    en la cache del telefono."""
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]

    _generar_retrato(client, studio, uid, char_id)
    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    retrato = next(s for s in ficha["master_shots"] if s["key"] == "portrait")
    assert retrato["version"] == 1
    ruta = retrato["storage_path"]

    _generar_retrato(client, studio, uid, char_id)
    ficha = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    retrato = next(s for s in ficha["master_shots"] if s["key"] == "portrait")
    # Misma ruta de siempre, version nueva: la URL cambia y la vista esta
    # obligada a pedir la imagen recien generada.
    assert retrato["storage_path"] == ruta
    assert retrato["version"] == 2
