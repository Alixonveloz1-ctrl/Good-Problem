"""Cero aprobaciones y fichas conectadas (regla del dueno, 2026-11-06).

«No tengo por que estar aprobando nada. Ni siquiera tiene que decir
aprobado: todo lo que se vaya generando automaticamente esta aprobado, lo
que este actual por defecto es lo que esta aprobado, se sobreentiende. Y
cada ficha debe tomar sus datos de las otras: si en la edad puse 21, la
ficha de identidad tiene que actualizarse automaticamente.»

Estas pruebas fijan esa regla: la sincronia de la edad entre los rasgos y
la identidad, la imagen principal siempre vigente, los endpoints de
aprobar convertidos en no-ops inofensivos y los flujos de musica y video
avanzando sin ningun gesto de aprobacion.
"""

from __future__ import annotations

from app.domain.enums import CanonStatus

BIBLE = "artist_bible/current"


def _universo(client, studio, **extra):
    creado = client.post("/api/universes", json={"name": "Nova", **extra}).json()
    studio.jobs.wait_for_idle(20)
    return creado


def _biblia_con_edad(studio, uid, edad: str) -> None:
    studio.db.set(
        f"universes/{uid}/{BIBLE}",
        {
            "id": "current",
            "universe_id": uid,
            "identity": {"stage_name": "Nova", "apparent_age": edad},
        },
    )


# --- Sincronia: la identidad toma la edad de los rasgos --------------------


def test_la_edad_de_los_rasgos_se_sincroniza_en_la_identidad(client, studio):
    """El caso real: rasgos 21, identidad 29. Al guardar los rasgos, la
    identidad pasa a decir 21 con el formato de la Bible («21 años»), y la
    ficha del artista tambien."""
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    _biblia_con_edad(studio, uid, "29 años")

    respuesta = client.patch(
        f"/api/universes/{uid}/characters/{char_id}",
        json={"rasgos": {"edad": "21"}},
    )
    assert respuesta.status_code == 200, respuesta.text

    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["identity"]["apparent_age"] == "21 años"
    artista = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert artista["apparent_age"] == "21 años"


def test_la_identidad_se_corrige_sola_al_abrirla(client, studio):
    """El universo ya existente (rasgos 21 guardados antes de que existiera
    la sincronia, Bible en 29) se corrige con solo leer la Bible: el
    usuario no tiene que tocar nada mas."""
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    _biblia_con_edad(studio, uid, "29 años")
    studio.db.update(
        f"universes/{uid}/characters/{char_id}", {"rasgos": {"edad": "21"}}
    )

    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["identity"]["apparent_age"] == "21 años"


def test_la_sincronia_no_pisa_lo_que_no_tiene_fuente(client, studio):
    """El nombre artistico y el origen los escribe el Director y no tienen
    fuente en otra ficha: la sincronia de la edad no los toca."""
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    studio.db.set(
        f"universes/{uid}/{BIBLE}",
        {
            "id": "current",
            "universe_id": uid,
            "identity": {
                "stage_name": "K-Prueba",
                "apparent_age": "29 años",
                "origin": "Caracas, Venezuela",
            },
        },
    )
    client.patch(
        f"/api/universes/{uid}/characters/{char_id}",
        json={"rasgos": {"edad": "21"}},
    )
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["identity"]["apparent_age"] == "21 años"
    assert biblia["identity"]["stage_name"] == "K-Prueba"
    assert biblia["identity"]["origin"] == "Caracas, Venezuela"


# --- La imagen principal siempre es la vigente -----------------------------


def test_la_home_devuelve_el_retrato_vigente_con_su_version(client, studio):
    """La tarjeta del artista sale del retrato actual de su ficha, con su
    marca de version — no de la primera toma que tenga imagen ni de una
    copia guardada al crear el universo."""
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    studio.db.update(
        f"universes/{uid}/characters/{char_id}",
        {
            "master_shots": [
                {"key": "full_body", "label": "Cuerpo entero",
                 "storage_path": "universes/x/full_body.png",
                 "status": CanonStatus.APPROVED.value, "version": 1},
                {"key": "portrait", "label": "Retrato",
                 "storage_path": "universes/x/portrait.png",
                 "status": CanonStatus.APPROVED.value, "version": 3},
            ]
        },
    )
    tarjetas = client.get("/api/home").json()["universes"]
    tarjeta = next(t for t in tarjetas if t["id"] == uid)
    assert tarjeta["cover_path"] == "universes/x/portrait.png"
    assert tarjeta["cover_version"] == 3


# --- Los endpoints de aprobar son no-ops inofensivos -----------------------


def test_aprobar_el_master_sin_imagenes_ya_no_es_un_error(client, studio):
    """Antes, aprobar un Master sin imagenes devolvia un conflicto y la
    pantalla ofrecia el gesto igualmente. Ahora el endpoint devuelve la
    ficha tal cual: no hay gesto que pueda fallar."""
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    respuesta = client.post(f"/api/universes/{uid}/characters/{char_id}/approve")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["id"] == char_id


def test_los_endpoints_de_aprobar_y_rechazar_no_cambian_nada(client, studio):
    creado = _universo(client, studio, gender="hombre")
    uid, char_id = creado["id"], creado["lead_character_id"]
    for ruta in (
        f"/api/universes/{uid}/bible/approve",
        f"/api/universes/{uid}/characters/{char_id}/reject",
    ):
        respuesta = client.post(ruta)
        assert respuesta.status_code == 200, (ruta, respuesta.text)


# --- Flujos sin compuertas: musica y video ---------------------------------


def test_generar_la_cancion_no_exige_aprobar_el_concepto_ni_la_letra(
    client, studio
):
    """Concepto generado -> letra generada -> Lyria, sin un solo gesto de
    aprobacion en medio. Y la version que sale queda como master vigente."""
    creado = _universo(client, studio, gender="hombre")
    uid = creado["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]

    client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={"brief": "Noche"})
    studio.jobs.wait_for_idle(30)

    letra = client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/generate", json={})
    assert letra.status_code == 200, letra.text
    studio.jobs.wait_for_idle(30)

    generada = client.post(f"/api/universes/{uid}/songs/{sid}/generate", json={})
    assert generada.status_code == 200, generada.text
    studio.jobs.wait_for_idle(30)

    cancion = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert cancion["approved_master_path"]
    assert cancion["approved_version"] == 1

    proyecto = client.post(
        f"/api/universes/{uid}/video-projects", json={"song_id": sid}
    )
    assert proyecto.status_code == 200, proyecto.text


def test_imagen_y_clip_de_escena_sin_ninguna_aprobacion(client, studio):
    """Storyboard recien hecho -> imagen -> clip, sin aprobar la historia,
    ni el storyboard, ni la imagen."""
    creado = _universo(client, studio, gender="hombre")
    uid = creado["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    studio.db.update(
        f"universes/{uid}/songs/{cancion['id']}",
        {"approved_master_path": "universes/x/song.wav"},
    )
    proyecto = client.post(
        f"/api/universes/{uid}/video-projects", json={"song_id": cancion["id"]}
    ).json()
    pid = proyecto["id"]

    from app.orchestrator.handlers import _apply_storyboard

    _apply_storyboard(
        studio, uid, pid,
        {"scenes": [{"index": 0, "action": "Canta", "image_prompt": "Nova singing",
                     "video_prompt": "push in", "reuses_scene_index": -1}]},
    )
    escena = client.get(f"/api/universes/{uid}/video-projects/{pid}").json()["scenes"][0]

    imagen = client.post(
        f"/api/universes/{uid}/scenes/{escena['id']}/image",
        json={"model": "gemini-3-pro-image", "variant": "1K"},
    )
    assert imagen.status_code == 200, imagen.text
    studio.jobs.wait_for_idle(30)

    clip = client.post(f"/api/universes/{uid}/scenes/{escena['id']}/clip", json={})
    assert clip.status_code == 200, clip.text
    studio.jobs.wait_for_idle(30)

    detalle = client.get(f"/api/universes/{uid}/scenes/{escena['id']}").json()
    assert detalle["image_id"] and detalle["clip_id"]
