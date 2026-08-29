"""The rules PRD v2.1 exists to enforce. If one of these fails, the system is
spending money the wrong way or shipping the wrong artefact.
"""

from __future__ import annotations

import pytest

from app.domain import guards
from app.domain.enums import JobState, ModelKind
from app.domain.pricing import estimate_images, estimate_song, estimate_text, estimate_video
from app.domain.registry import ModelRegistry, load_seed
from app.errors import InvalidGenerationRequest, ModelNotAllowed
from app.orchestrator.orchestrator import GenerationRequest
from app.providers import lyria, veo
from app.providers.vertex import VertexClient


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry(load_seed())


# --- 1. Music is Lyria 3 Pro, never a 30 second clip model (PRD 14) --------


@pytest.mark.parametrize("banned", ["lyria-3", "lyria-2", "lyria-002"])
def test_clip_music_models_are_refused_everywhere(banned, registry, studio):
    with pytest.raises(ModelNotAllowed):
        guards.assert_music_model(banned)
    with pytest.raises(ModelNotAllowed):
        lyria.generate_song(
            VertexClient("p", dry_run=True), model=banned, prompt="x", duration_seconds=30
        )
    with pytest.raises(ModelNotAllowed):
        studio.orchestrator.resolve_model(
            GenerationRequest(universe_id="u", kind="music", model=banned)
        )


def test_banned_models_cannot_be_re_enabled_from_the_registry():
    document = load_seed()
    document["models"].append(
        {
            "id": "lyria-3",
            "kind": "music",
            "label": "Lyria 3",
            "status": "active",
            "variants": [{"key": "clip", "unit": "song", "price": 0.02}],
        }
    )
    registry = ModelRegistry(document)
    assert "lyria-3" not in [m.id for m in registry.all(ModelKind.MUSIC, active_only=False)]
    assert any(entry["id"] == "lyria-3" for entry in registry.excluded)


def test_music_selector_offers_exactly_one_model(registry):
    assert [m.id for m in registry.all(ModelKind.MUSIC)] == ["lyria-3-pro-preview"]


def test_music_falls_back_to_nothing(studio):
    """A failed music job retries with the same model; there is no weaker one to
    fall back to (PRD 37)."""
    resolved = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id="u", kind="music", model=None)
    )
    assert resolved.spec.id == "lyria-3-pro-preview"
    assert resolved.source == "system"


# --- 2. Veo audio is always off (PRD 5, 26) -------------------------------


def test_every_veo_request_disables_audio(registry):
    client = VertexClient("p", dry_run=True)
    for model_id in (
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
        "veo-3.1-lite-generate-001",
    ):
        veo.start_generation(
            client,
            registry.get(model_id),
            prompt="scene",
            variant="1080p",
            source_image=veo.SourceImage(data=b"x"),
        )
    for call in client.calls.for_model_prefix("veo"):
        assert call.payload["parameters"]["generateAudio"] is False


def test_asking_for_audio_is_an_error():
    with pytest.raises(InvalidGenerationRequest):
        guards.enforce_video_audio_disabled({"generateAudio": True})
    with pytest.raises(InvalidGenerationRequest):
        guards.enforce_video_audio_disabled({"generate_audio": True})


# --- 3. Clip durations (PRD 23, 26) ---------------------------------------


@pytest.mark.parametrize("resolution", ["1080p", "4K"])
def test_eight_seconds_is_mandatory_at_high_resolution(resolution):
    assert guards.resolve_clip_duration(8, resolution=resolution) == 8
    for bad in (4, 6):
        with pytest.raises(InvalidGenerationRequest):
            guards.resolve_clip_duration(bad, resolution=resolution)


def test_eight_seconds_is_mandatory_with_reference_images():
    with pytest.raises(InvalidGenerationRequest):
        guards.resolve_clip_duration(6, resolution="720p", reference_image_count=1)
    assert guards.resolve_clip_duration(6, resolution="720p") == 6


def test_unsupported_durations_are_refused():
    with pytest.raises(InvalidGenerationRequest):
        guards.resolve_clip_duration(5, resolution="720p")


def test_at_most_three_reference_images(registry):
    with pytest.raises(InvalidGenerationRequest):
        veo.start_generation(
            VertexClient("p", dry_run=True),
            registry.get("veo-3.1-generate-001"),
            prompt="x",
            variant="1080p",
            reference_images=[veo.SourceImage(data=b"a") for _ in range(4)],
        )


# --- 4. Retries keep the model (PRD 37) -----------------------------------


def test_retry_never_substitutes_the_model(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    job = studio.jobs.create(
        uid, kind="video", model="veo-3.1-generate-001", variant="1080p", target_type="scene",
        target_id="scene_x", request={}, estimated_cost_usd=1.6,
    )
    studio.jobs.mark_failed(uid, job["id"], "boom")
    with pytest.raises(ModelNotAllowed):
        studio.jobs.retry(uid, job["id"], model="veo-3.1-lite-generate-001")


def test_retry_stops_after_max_attempts(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    job = studio.jobs.create(
        uid, kind="text", model="gemini-3.1-pro-preview", variant="default", target_type="song",
        target_id="s", request={}, estimated_cost_usd=0.01,
    )
    studio.db.update(
        f"universes/{uid}/jobs/{job['id']}",
        {"attempts": 3, "state": JobState.FAILED.value},
    )
    with pytest.raises(Exception) as excinfo:
        studio.jobs.retry(uid, job["id"])
    assert "intentos" in str(excinfo.value)


# --- Pricing matches the PRD's own reference numbers (PRD 44) -------------


def test_reference_cost_of_a_three_minute_video(registry):
    """PRD 44: 24 escenas, dos intentos por pieza, gemini-3.1-flash-image y
    veo-3.1-fast-generate-001 1080p sin audio."""
    song = estimate_song(registry, attempts=15)
    images = estimate_images(registry, "gemini-3.1-flash-image", "1K", images=42)
    video = estimate_video(registry, "veo-3.1-fast-generate-001", "1080p", seconds=8, clips=36)
    director = estimate_text(registry, "gemini-3.1-pro-preview", input_tokens=900_000,
                             output_tokens=100_000)
    assert round(song.amount_usd, 2) == 1.20
    assert round(images.amount_usd, 2) == 2.81
    assert round(video.amount_usd, 2) == 28.80
    assert director.amount_usd == pytest.approx(2.125)  # el PRD lo redondea a ~$2,00
    total = song.amount_usd + images.amount_usd + video.amount_usd + director.amount_usd + 1.00
    assert 34.0 < total < 36.5


def test_video_is_billed_per_second_not_per_clip(registry):
    """The Vertex console labels the unit '1 count'. It is not per video."""
    one_clip = estimate_video(registry, "veo-3.1-lite-generate-001", "1080p", seconds=8, clips=1)
    assert one_clip.amount_usd == 0.40
    assert one_clip.quantity == 8


def test_switching_model_is_the_main_lever(registry):
    """PRD 44: the same video is about $15 on lite 720p and about $65 on
    veo-3.1-generate-001 1080p."""
    cheap = estimate_video(registry, "veo-3.1-lite-generate-001", "720p", seconds=8, clips=36)
    dear = estimate_video(registry, "veo-3.1-generate-001", "1080p", seconds=8, clips=36)
    assert round(cheap.amount_usd, 2) == 8.64
    assert round(dear.amount_usd, 2) == 57.60
    assert dear.amount_usd / cheap.amount_usd > 6


# --- El artista se crea una vez, y es suyo --------------------------------


def test_crear_el_artista_es_un_solo_paso(client, studio):
    """Un formulario, un nombre, y el estudio se pone a trabajar solo.

    Antes eran dos: se creaba un universo con un nombre y dentro habia que
    crear otra vez al artista con otro nombre. Dos nombres para la misma
    persona. Y hasta que no se pedia el diseno a mano no habia prompts, asi que
    todos los botones de "Generar" contestaban que no habia prompt.
    """
    creado = client.post(
        "/api/universes",
        json={"name": "Feri", "gender": "mujer", "genre": "reggaeton triste"},
    ).json()

    assert creado["lead_character_id"]
    # Y ya esta encargado el diseno: nadie tiene que acordarse de pedirlo.
    assert creado["job"] is not None

    personajes = client.get(f"/api/universes/{creado['id']}/characters").json()
    assert len(personajes) == 1
    assert personajes[0]["name"] == "Feri"
    assert personajes[0]["role"] == "lead"
    assert personajes[0]["gender"] == "mujer"


def test_el_director_no_puede_cambiarle_el_nombre_ni_el_sexo(client, studio):
    """Escribio "Feri", una artista, y el Director devolvio "Leo Castillo".

    Al Director se le pide en el prompt que respete lo que ya se decidio, pero
    un prompt es una peticion, no una garantia. Esto es la garantia: pase lo que
    pase con el modelo, el nombre que se escribio es el nombre.
    """
    from app.orchestrator.handlers import _apply_director_result

    creado = client.post(
        "/api/universes", json={"name": "Feri", "gender": "mujer"}
    ).json()
    uid, char_id = creado["id"], creado["lead_character_id"]
    studio.jobs.wait_for_idle(20)  # que termine el diseno que se encargo solo

    # Lo que devolveria un modelo que se va por su cuenta.
    _apply_director_result(
        studio,
        uid,
        {"target_id": char_id,
         "request": {"payload": {"task": "character",
                                 "locked": {"name": "Feri", "gender": "mujer"}}}},
        "character",
        {
            "name": "Leo Castillo",
            "apparent_age": "35",
            "appearance": "hombre de barba",
            "master_prompts": [{"key": "portrait", "prompt": "portrait of a man"}],
        },
    )

    personaje = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert personaje["name"] == "Feri"
    assert personaje["gender"] == "mujer"
    # Lo demas si lo escribe el Director: para eso esta.
    assert personaje["apparent_age"] == "35"
    assert personaje["master_shots"][0]["prompt"] == "portrait of a man"


def test_lo_que_elige_el_usuario_manda_sobre_el_director(client, studio):
    """"O decido yo o lo decide el director, pero yo no tengo donde decidir."

    Tenia razon: la unica decision que quedaba era el nombre. Ahora se eligen el
    pelo, la piel, el cuerpo, la edad y el estilo, y lo elegido no se discute:
    viaja como dado hasta el prompt de cada imagen. Lo que se deja en blanco si
    lo decide el Director, que para eso esta.
    """
    from app.orchestrator.handlers import _apply_director_result
    from app.routers.characters import _lo_que_ya_decidio

    creado = client.post(
        "/api/universes", json={"name": "Feri", "gender": "mujer"}
    ).json()
    uid, char_id = creado["id"], creado["lead_character_id"]
    studio.jobs.wait_for_idle(20)

    elegidos = {"pelo": "teñido", "piel": "morena", "cuerpo": "atlético", "edad": "25-34"}
    client.patch(f"/api/universes/{uid}/characters/{char_id}", json={"rasgos": elegidos})

    personaje = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert personaje["rasgos"] == elegidos
    # Todo lo elegido llega al Director como algo dado, no como una sugerencia.
    fijo = _lo_que_ya_decidio(personaje)
    assert fijo["name"] == "Feri" and fijo["gender"] == "mujer"
    for clave, valor in elegidos.items():
        assert fijo[clave] == valor

    # Y si el modelo devuelve otra cosa, lo elegido se queda.
    _apply_director_result(
        studio,
        uid,
        {"target_id": char_id, "request": {"payload": {"task": "character"}}},
        "character",
        {"name": "Otra", "apparent_age": "50", "appearance": "rubia de pelo largo",
         "master_prompts": [{"key": "portrait", "prompt": "portrait"}]},
    )
    personaje = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert personaje["rasgos"] == elegidos
    assert personaje["name"] == "Feri"
    # Y lo que NO se eligio si lo escribe el: eso es su trabajo.
    assert personaje["apparent_age"] == "50"


def test_hay_donde_elegir_como_es_en_la_pantalla():
    """La otra mitad: los botones existen y guardan.

    Una ruta sin boton no existe para quien usa la app, y esto era exactamente
    eso: el campo se podia guardar desde el primer dia y no habia donde tocarlo.
    """
    import pathlib as rutas

    fuente = rutas.Path(__file__).resolve().parents[2] / "frontend" / "src"
    codigo = "\n".join(f.read_text() for f in fuente.rglob("*.tsx"))
    assert "<Rasgos" in codigo, "no hay donde elegir como es"
    assert "rasgos: { ...rasgos" in codigo, "elegir no guarda nada"
    for rasgo in ("pelo", "piel", "cuerpo", "edad", "estilo"):
        assert f"clave: '{rasgo}'" in codigo, f"falta poder elegir {rasgo}"


def test_la_pantalla_del_artista_dice_que_toca_ahora(client, studio):
    """El camino entero, paso a paso, sin adelantarse ni saltarse ninguno.

    "No se ni por donde empezar ni que crear ni que ver. No puedo hacer nada
    porque no se entiende nada." La pantalla era un indice de once puertas sin
    orden entre ellas, y un indice no dice que hacer.

    Cada paso necesita el anterior de verdad: un video sin cara aprobada no
    sabe a quien esta grabando, y un videoclip sin cancion no tiene sobre que
    montarse. Esta prueba recorre el camino y comprueba que en cada estado la
    aplicacion pide UNA cosa, y la que toca.
    """
    from app.domain.enums import CanonStatus

    def toca(uid: str) -> str:
        return client.get(f"/api/universes/{uid}").json()["siguiente"]["clave"]

    creado = client.post("/api/universes", json={"name": "Feri", "gender": "mujer"}).json()
    uid, char_id = creado["id"], creado["lead_character_id"]
    studio.jobs.wait_for_idle(20)
    ficha = f"universes/{uid}/characters/{char_id}"

    # 1. Con artista y sin cara, lo que toca es la cara.
    assert toca(uid) == "cara"

    # 2. Con cara sin aprobar, lo que toca es aprobarla.
    tomas = studio.db.get(ficha)["master_shots"]
    tomas[0]["storage_path"] = "universes/x/character/retrato.png"
    studio.db.update(ficha, {"master_shots": tomas})
    assert toca(uid) == "aprobar_cara"

    # 3. Aprobada, lo que toca es la primera cancion.
    studio.db.update(ficha, {"status": CanonStatus.APPROVED.value})
    assert toca(uid) == "cancion"

    # 4. Con cancion sin aprobar, terminarla.
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "La primera"}).json()
    assert toca(uid) == "aprobar_cancion"

    # 5. Aprobada, el videoclip. Y no antes: es el paso que no se puede saltar.
    studio.db.update(
        f"universes/{uid}/songs/{cancion['id']}", {"status": CanonStatus.APPROVED.value}
    )
    assert toca(uid) == "videoclip"


def test_un_estudio_sin_artista_lo_dice_y_lo_arregla(client, studio):
    """Y NO enseña a un acompañante haciendo de artista.

    Los estudios creados antes de que el artista se creara solo se quedaron sin
    protagonista. La pantalla cogia entonces el primer personaje de la lista, y
    como los acompañantes si se pueden proponer, acababa presidiendo la
    pantalla una tal Luna Ferrer que no venia de ninguna parte.
    """
    uid = client.post("/api/universes", json={"name": "Feri"}).json()["id"]
    studio.jobs.wait_for_idle(20)

    # Se borra el protagonista, como si el estudio fuera de los viejos.
    for personaje in client.get(f"/api/universes/{uid}/characters").json():
        client.delete(f"/api/universes/{uid}/characters/{personaje['id']}")

    # Y se le añaden acompañantes, que es lo que llenaba la lista.
    client.post(
        f"/api/universes/{uid}/characters", json={"name": "Luna Ferrer", "role": "supporting"}
    )

    paso = client.get(f"/api/universes/{uid}").json()["siguiente"]
    assert paso["clave"] == "artista", "con acompañantes pero sin artista, pide el artista"
    assert "Feri" in paso["titulo"]
    assert paso["accion"] == "crear_artista"

    # Y se arregla de un toque, con el nombre del estudio.
    creado = client.post(f"/api/universes/{uid}/artista").json()
    assert creado["name"] == "Feri"
    assert creado["role"] == "lead"
    assert client.get(f"/api/universes/{uid}").json()["siguiente"]["clave"] == "genero"

    # Y no crea dos si se toca dos veces.
    client.post(f"/api/universes/{uid}/artista")
    lideres = [
        c for c in client.get(f"/api/universes/{uid}/characters").json() if c["role"] == "lead"
    ]
    assert len(lideres) == 1


def test_la_pantalla_nunca_asciende_a_un_secundario_a_artista():
    """La otra mitad: en el codigo de la pantalla, tampoco.

    El fallo estaba en un `?? lista[0]` puesto para que "un universo con
    personajes pero sin protagonista no se quede sin cara". Lo que conseguia era
    peor que quedarse sin cara: enseñaba a otro en su lugar.
    """
    import pathlib as rutas

    pantallas = rutas.Path(__file__).resolve().parents[2] / "frontend" / "src" / "screens"
    codigo = "\n".join(f.read_text() for f in pantallas.glob("*.tsx"))
    assert "'lead') ?? lista[0]" not in codigo
    assert "=== 'lead') ?? null" in codigo, "el artista tiene que salir solo del protagonista"


def test_se_le_puede_decir_quien_es_a_un_artista_que_ya_existe(client, studio):
    """Y esa decision viaja hasta el Director.

    El bloqueo del nombre y el sexo no sirve de nada si el sexo esta vacio:
    entonces lo elige el Director, y de un nombre de mujer saca un hombre. Al
    crear el artista ahora es obligatorio, pero los que ya existian se quedaron
    sin ello y no habia ningun sitio donde decirlo.
    """
    from app.routers.characters import _lo_que_ya_decidio

    creado = client.post("/api/universes", json={"name": "Feri"}).json()
    uid, char_id = creado["id"], creado["lead_character_id"]
    studio.jobs.wait_for_idle(20)

    # Sin sexo, al Director solo le llega el nombre: lo demas se lo inventa.
    personaje = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert "gender" not in _lo_que_ya_decidio(personaje)

    # Se le dice, desde su propia ficha.
    respuesta = client.patch(
        f"/api/universes/{uid}/characters/{char_id}", json={"gender": "mujer"}
    )
    assert respuesta.status_code == 200, respuesta.text

    personaje = client.get(f"/api/universes/{uid}/characters/{char_id}").json()
    assert personaje["gender"] == "mujer"
    assert _lo_que_ya_decidio(personaje) == {"name": "Feri", "gender": "mujer"}


def test_hay_donde_decir_quien_es_en_la_pantalla():
    """La otra mitad: que el selector exista donde se usa.

    "Sigo sin poder escoger el genero." La ruta aceptaba el campo desde hacia
    rato; lo que no habia era ningun sitio donde tocarlo. Una ruta sin boton no
    existe para quien usa la app.
    """
    import pathlib as rutas

    fuente = rutas.Path(__file__).resolve().parents[2] / "frontend" / "src"
    codigo = "\n".join(f.read_text() for f in fuente.rglob("*.tsx"))
    assert codigo.count("<ElegirGenero") >= 2, "falta el selector al crear o en la ficha"
    assert "{ gender: valor }" in codigo, "el selector no guarda nada"


def test_el_estudio_propone_el_vestuario_y_las_locaciones(client, studio):
    """Sin escribir un nombre ni una descripcion.

    "Para que estan los directores." Tenia razon: cada atuendo y cada locacion
    habia que crearlos a mano, con su nombre y su categoria, uno por uno. Eso no
    es dirigir un estudio, es rellenar un formulario.
    """
    from app.orchestrator.handlers import _apply_director_result

    uid = client.post("/api/universes", json={"name": "Feri"}).json()["id"]
    studio.jobs.wait_for_idle(20)

    # Las rutas existen, encargan el trabajo, y lo que vuelve se guarda solo:
    # el vestuario aparece sin que nadie escriba un nombre.
    for ruta in ("wardrobe", "locations", "characters"):
        respuesta = client.post(f"/api/universes/{uid}/{ruta}/propose", json={"count": 2})
        assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)
    assert client.get(f"/api/universes/{uid}/wardrobe").json(), "no propuso ningun atuendo"
    assert client.get(f"/api/universes/{uid}/locations").json(), "no propuso ninguna locacion"

    # Y los campos se guardan donde toca.
    _apply_director_result(
        studio, uid, {"request": {"payload": {}}}, "wardrobe_set",
        {"outfits": [{"name": "Chandal de terciopelo", "category": "signature",
                      "description": "verde botella"}]},
    )
    _apply_director_result(
        studio, uid, {"request": {"payload": {}}}, "location_set",
        {"locations": [{"name": "Azotea de Caracas", "description": "de noche"}]},
    )

    atuendos = {a["name"]: a for a in client.get(f"/api/universes/{uid}/wardrobe").json()}
    sitios = {s["name"]: s for s in client.get(f"/api/universes/{uid}/locations").json()}
    assert atuendos["Chandal de terciopelo"]["category"] == "signature"
    assert atuendos["Chandal de terciopelo"]["description"] == "verde botella"
    assert sitios["Azotea de Caracas"]["description"] == "de noche"


# --- Idempotency (PRD 42.1) -----------------------------------------------


def test_the_same_key_never_generates_twice(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    request = GenerationRequest(
        universe_id=uid, kind="text", target_type="artist_bible", target_id="current",
        idempotency_key="abc-123", payload={"task": "artist_bible"},
    )
    first = studio.orchestrator.submit(request)
    second = studio.orchestrator.submit(request)
    assert first["id"] == second["id"]
    studio.jobs.wait_for_idle(20)
    # Se cuentan los de ESTA clave: crear el artista ya encarga su diseno, y
    # esa es otra generacion legitima que no tiene nada que ver con esta.
    con_esta_clave = [
        job for job in studio.jobs.list(uid, limit=50)
        if job.get("idempotency_key") == "abc-123"
    ]
    assert len(con_esta_clave) == 1


# --- Model resolution order (PRD 42.8) ------------------------------------


def test_user_choice_beats_the_bible_preference(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    client.put(
        f"/api/universes/{uid}/bible/preferences",
        json={"preferred_image_model": "gemini-2.5-flash-image"},
    )
    chosen = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id=uid, kind="image", model="gemini-3-pro-image")
    )
    assert (chosen.spec.id, chosen.source) == ("gemini-3-pro-image", "user")

    fallback = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id=uid, kind="image")
    )
    assert (fallback.spec.id, fallback.source) == ("gemini-2.5-flash-image", "bible")


def test_an_unknown_api_route_is_a_404_not_the_pwa(client, tmp_path):
    """Sin esto, una ruta /api que ya no existe devuelve el index.html con 200 y
    el cliente falla al parsear JSON muy lejos de la causa."""
    response = client.get("/api/universes/uni_x/ruta-que-no-existe")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_the_studio_keeps_no_budget(client):
    """El gasto se mira en Google Cloud, no aqui."""
    assert client.get("/api/budget").status_code == 404
    home = client.get("/api/home").json()
    assert "budget" not in home


def test_la_ruta_de_voz_no_la_tapa_la_de_contenido(client, universe):
    """FastAPI resuelve las rutas en orden. Si /voice-clone queda despues de
    /{content_id}, la app pide la voz y recibe un 404 sin sentido."""
    respuesta = client.get(f"/api/universes/{universe}/content/voice-clone")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ready"] is False
    assert "consent" in cuerpo["consent_script"].lower()


def test_la_cola_de_trabajos_lleva_su_propia_identidad(settings, studio):
    """PRD 37: los trabajos siguen en Google Cloud aunque se cierre el iPhone.

    Eso solo se cumple si van por Cloud Tasks, y la cola solo puede volver a
    entrar si trae con que demostrar quien es. Antes eso era un token OIDC de
    Google; emitirlo exigia un permiso que hay que ir a dar a mano, y sin el no
    arrancaba ni una sola generacion. Ahora el pase lo firma el propio estudio.
    """
    from app.auth import COLA
    from app.services.jobs import JobService

    settings.tasks_queue = "aaus-generation"
    settings.tasks_target_url = "https://aaus-abc.a.run.app"

    tarea = JobService(studio.db, settings).build_task("uni_1", "job_1", "POST")
    peticion = tarea["http_request"]

    assert peticion["url"] == "https://aaus-abc.a.run.app/api/internal/jobs/run"
    assert peticion["headers"][COLA]
    # Y nada de OIDC: es justo lo que pedia el permiso que faltaba.
    assert "oidc_token" not in peticion


def test_el_pase_de_la_cola_va_atado_a_su_trabajo(settings, studio):
    """Un encargo firmado no puede servir de llave para otra generacion.

    La puerta solo mira que la firma cuadre. Si el pase no dijera de que trabajo
    es, cualquier encargo legitimo -y hay uno por cada imagen que se genera-
    valdria para lanzar el que quisiera quien lo pillase.
    """
    from app.auth import COLA, firmar_encargo, leer_encargo
    from app.services.jobs import JobService

    settings.tasks_queue = "aaus-generation"
    settings.tasks_target_url = "https://aaus-abc.a.run.app"
    settings.session_secret = "clave-de-prueba"

    tarea = JobService(studio.db, settings).build_task("uni_1", "job_1", "POST")
    pase = tarea["http_request"]["headers"][COLA]

    assert leer_encargo(pase, settings.session_secret) == ("uni_1", "job_1")
    # Con otra clave no vale, y manipulado tampoco.
    assert leer_encargo(pase, "otra-clave") is None
    cuerpo, firma = pase.rsplit(".", 1)
    otra = firmar_encargo("uni_1", "job_2", settings.session_secret).rsplit(".", 1)[1]
    assert leer_encargo(f"{cuerpo}.{otra}", settings.session_secret) is None


COMPROBADOS = {
    "gemini-3.1-pro-preview",
    "gemini-3-pro-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
    "lyria-3-pro-preview",
    "veo-3.1-generate-001",
    "veo-3.1-fast-generate-001",
    "veo-3.1-lite-generate-001",
    "chirp-3-instant-custom-voice",
}
"""Los modelos que existen de verdad, uno por uno.

No salen de la documentacion ni de acordarse: estan copiados de una instalacion
del mismo dueño que ya genera con ellos todos los dias. Un identificador de
modelo no se deduce del nombre comercial -"Veo 3.1" no es "veo-3.1"- y cuando se
inventa uno, Vertex contesta 404 y ese 404 no dice "te lo inventaste": dice lo
mismo que si el modelo existiera y estuviera en otro sitio.

Ya paso dos veces. Por eso esto es una prueba y no un comentario.
"""


def test_no_hay_ningun_modelo_inventado_en_el_registro(registry):
    """Cada modelo del registro tiene que ser uno comprobado, y ninguno mas."""
    del registry  # el registro se lee de la semilla, que es lo que se despliega
    from app.domain.registry import load_seed

    en_la_semilla = {m["id"] for m in load_seed()["models"]}
    assert en_la_semilla == COMPROBADOS, (
        "Modelos que sobran: " + str(sorted(en_la_semilla - COMPROBADOS)) +
        " | Modelos que faltan: " + str(sorted(COMPROBADOS - en_la_semilla))
    )


def test_cada_modelo_se_pide_donde_vive():
    """El 404 que parecia un nombre inventado y era una direccion equivocada.

    "Vertex AI devolvio 404 para gemini-3.1-pro-preview:generateContent". Ese
    error se lee como "ese modelo no existe", asi que uno se pasa la tarde
    cambiando el nombre. El nombre estaba bien. Lo que estaba mal era el sitio:
    los gemini-3.* y Lyria 3 Pro no viven en us-central1 sino en "global", y la
    region global ademas no lleva prefijo en el host.

    Comprobado contra una instalacion que ya funciona.
    """
    from app.providers.vertex import VertexClient

    cliente = VertexClient("mi-proyecto", location="us-central1", dry_run=True)

    for modelo in ("gemini-3.1-pro-preview", "gemini-3-pro-image", "lyria-3-pro-preview"):
        url = cliente.model_url(modelo, "generateContent")
        assert url.startswith("https://aiplatform.googleapis.com/"), url
        assert "/locations/global/" in url, url

    for modelo in ("gemini-2.5-flash-image", "veo-3.1-generate-001"):
        url = cliente.model_url(modelo, "predictLongRunning")
        assert url.startswith("https://us-central1-aiplatform.googleapis.com/"), url
        assert "/locations/us-central1/" in url, url


def test_lyria_se_pide_como_gemini_no_como_una_prediccion():
    """Lyria no tiene endpoint propio: es :generateContent con audio.

    Pedirsela con :predict, que es como se pide un modelo de generacion
    normal, devuelve el mismo 404 de arriba. Y la duracion no es un parametro:
    si no se le dice en el propio texto que no pare, entrega 30 segundos.
    """
    from app.providers import lyria
    from app.providers.vertex import CallLog, VertexClient

    registro = CallLog()
    cliente = VertexClient("mi-proyecto", dry_run=True, call_log=registro)
    resultado = lyria.generate_song(cliente, prompt="cumbia triste", duration_seconds=95)

    llamada = registro.all()[-1]
    assert llamada.method == "generateContent"
    assert llamada.payload["generationConfig"]["responseModalities"] == ["AUDIO", "TEXT"]
    # Sin maxOutputTokens: Vertex contesta "invalid argument" si se le anade.
    assert set(llamada.payload["generationConfig"]) == {"responseModalities"}
    texto = llamada.payload["contents"][0]["parts"][0]["text"]
    assert "95 seconds" in texto and "cumbia triste" in texto
    # Y los trozos de audio vienen pegados, sin la cabecera RIFF repetida.
    assert resultado.data[:4] == b"RIFF"
    assert resultado.data.count(b"RIFF") == 1


# --- La puerta (PRD 41) -----------------------------------------------------

FIREBASE = (
    '{"apiKey":"AIzaFalsa","authDomain":"alixon-jhan.firebaseapp.com",'
    '"projectId":"alixon-jhan"}'
)


def test_la_cookie_de_sesion_no_se_puede_falsificar():
    """Sin esto, cualquiera que sepa el correo del dueno entra escribiendo una
    cookie a mano."""
    from app.auth import create_session, read_session

    cookie = create_session("yo@gmail.com", "un-secreto-de-treinta-y-dos-caracteres")

    assert read_session(cookie, "un-secreto-de-treinta-y-dos-caracteres") == "yo@gmail.com"
    assert read_session(cookie, "otro-secreto-cualquiera-de-32-chars") is None
    assert read_session("basura", "un-secreto-de-treinta-y-dos-caracteres") is None

    # La firma es hexadecimal, asi que cambiar el ultimo caracter por un "0"
    # fijo no la altera una de cada dieciseis veces. Se elige uno distinto del
    # que hay: una prueba que a veces no prueba nada es peor que ninguna.
    distinto = "1" if cookie[-1] == "0" else "0"
    assert read_session(cookie[:-1] + distinto, "un-secreto-de-treinta-y-dos-caracteres") is None


def test_la_sesion_caduca():
    from app.auth import create_session, read_session

    secreto = "un-secreto-de-treinta-y-dos-caracteres"
    caducada = create_session("yo@gmail.com", secreto, days=-1)
    assert read_session(caducada, secreto) is None


def test_sin_sesion_no_se_ven_los_datos(client, studio):
    """La puerta se aplica en un middleware y no ruta por ruta a proposito: una
    ruta nueva se puede escribir sin acordarse de pedir identidad."""
    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"

    assert client.get("/api/home").status_code == 403
    assert client.get("/api/universes").status_code == 403
    # /media/ tampoco: los archivos generados no son publicos por acertar la ruta.
    assert client.get("/media/loquesea.png").status_code == 403


def test_la_pantalla_de_entrada_si_carga_sin_sesion(client, studio):
    """Si la puerta tapara tambien el HTML, no habria forma de pintar el boton
    de entrar: la aplicacion seria inaccesible para su propio dueno."""
    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"

    assert client.get("/api/health").status_code == 200

    config = client.get("/api/auth/config")
    assert config.status_code == 200
    cuerpo = config.json()
    assert cuerpo["login_required"] is True
    assert cuerpo["firebase"]["projectId"] == "alixon-jhan"
    assert cuerpo["signed_in"] is False


def test_con_la_cookie_correcta_se_entra(client, studio):
    from app.auth import COOKIE, create_session

    studio.settings.owner_email = "Dueno@Gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"

    client.cookies.set(COOKIE, create_session("dueno@gmail.com", studio.settings.session_secret))
    assert client.get("/api/home").status_code == 200

    # Otra cuenta de Google, con una sesion firmada de verdad, sigue fuera.
    client.cookies.set(COOKIE, create_session("otro@gmail.com", studio.settings.session_secret))
    assert client.get("/api/home").status_code == 403
    client.cookies.clear()


def test_la_ruta_interna_no_acepta_la_cookie_del_navegador(client, studio):
    """Es la puerta de la cola de trabajos y solo de ella. Con la cookie valdria
    para lanzar trabajos a mano desde el movil sin pasar por el orquestador."""
    from app.auth import COOKIE, create_session

    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"
    client.cookies.set(COOKIE, create_session("dueno@gmail.com", studio.settings.session_secret))

    respuesta = client.post("/api/internal/jobs/run", json={"universe_id": "u", "job_id": "j"})
    assert respuesta.status_code == 403
    client.cookies.clear()


def test_un_despliegue_a_medias_no_arranca():
    """Correo de dueno puesto y nada con que comprobarlo: eso es una puerta
    pintada. Tiene que romperse en el despliegue, no despues."""
    from app.settings import Settings

    a_medias = Settings(owner_email="dueno@gmail.com", firebase_config="", session_secret="")
    assert len(a_medias.check()) == 2

    # Una configuracion rota cuenta como si no hubiera: un JSON a medias dejaria
    # la puerta abierta creyendo que esta cerrada.
    rota = Settings(
        owner_email="dueno@gmail.com",
        firebase_config="{esto no es json",
        session_secret="un-secreto-de-treinta-y-dos-caracteres",
    )
    assert len(rota.check()) == 1

    corto = Settings(
        owner_email="dueno@gmail.com", firebase_config=FIREBASE, session_secret="corto"
    )
    assert len(corto.check()) == 1

    completo = Settings(
        owner_email="dueno@gmail.com",
        firebase_config=FIREBASE,
        session_secret="un-secreto-de-treinta-y-dos-caracteres",
    )
    assert completo.check() == []

    # En un portatil, sin correo de dueno, no hay nada que exigir.
    assert Settings(owner_email="").check() == []


def test_la_cookie_de_sesion_sale_marcada(client, studio, monkeypatch):
    """HttpOnly para que ningun script la lea, Secure para que no viaje en
    claro. Mirar solo el esquema fallaria: detras del proxy de Cloud Run la app
    se cree en http, y la marca se perderia sin que nada falle a la vista."""
    from app.routers import auth as router_auth

    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"
    monkeypatch.setattr(router_auth, "verify_firebase_token", lambda *_: "dueno@gmail.com")

    respuesta = client.post("/api/auth/session", json={"credential": "loquesea"})
    assert respuesta.status_code == 200
    galleta = respuesta.headers["set-cookie"]
    assert "HttpOnly" in galleta
    assert "Secure" in galleta   # aunque el test hable http
    assert "SameSite=lax" in galleta


def test_un_token_bueno_de_otra_cuenta_no_entra(client, studio, monkeypatch):
    """Comprobar que Google firmo el token no basta: lo firma para cualquiera
    que tenga cuenta. La segunda comprobacion es la que cierra la puerta."""
    from app.routers import auth as router_auth

    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"
    monkeypatch.setattr(router_auth, "verify_firebase_token", lambda *_: "otro@gmail.com")

    respuesta = client.post("/api/auth/session", json={"credential": "token-de-otro"})
    assert respuesta.status_code == 403
    assert "set-cookie" not in respuesta.headers


def test_sin_firebase_no_se_intenta_comprobar_nada(client, studio):
    """Sin proyecto contra el que comprobar, un token no se puede verificar. Hay
    que decirlo, no dejar pasar."""
    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = ""
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"

    respuesta = client.post("/api/auth/session", json={"credential": "loquesea"})
    assert respuesta.status_code == 403
    assert "instalador" in respuesta.json()["error"]["message"]

    # Y la pantalla de entrada lo sabe, para poder decirlo en vez de quedarse muda.
    assert client.get("/api/auth/config").json()["firebase"] == {}


def test_el_token_tiene_que_ir_dirigido_a_este_proyecto(studio):
    """Sin exigir destinatario valdria un token emitido por el Firebase de
    cualquier otro proyecto, que es un token perfectamente autentico."""
    import inspect

    from app.auth import verify_firebase_token

    fuente = inspect.getsource(verify_firebase_token)
    assert "project_id" in fuente
    assert "securetoken.google.com" in fuente

    studio.settings.firebase_config = FIREBASE
    assert studio.settings.firebase_project == "alixon-jhan"


# --- Los nombres de los modelos ---------------------------------------------


def test_los_ids_son_los_que_vertex_quiere(registry):
    """Los del PRD eran nombres comerciales, no identificadores.

    Con "veo-3.1" en vez de "veo-3.1-generate-001", la URL que se arma no existe
    y cada video muere en un 404 que en la pantalla solo se ve como un trabajo
    fallido. Estos son los que estan comprobados funcionando en
    studio.LegadodeHierro.
    """
    ids = {spec.id for spec in registry.all()}
    assert {
        "gemini-3.1-pro-preview",
        "gemini-3-pro-image",
        "gemini-3.1-flash-image",
        "lyria-3-pro-preview",
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
        "veo-3.1-lite-generate-001",
    } <= ids

    # Los nombres comerciales no vuelven a colarse.
    assert not ids & {"veo-3.1", "veo-3.1-fast", "veo-3.1-lite", "lyria-3-pro", "gemini-3-pro"}


def test_el_guardia_de_musica_apunta_a_un_modelo_que_existe(registry):
    """guards.py y el registro se escriben por separado y nadie los lee juntos.

    Si el guardia exige un ID que el registro no tiene, no se puede generar
    musica en absoluto y el error no dice eso.
    """
    from app.domain.guards import MUSIC_MODEL_ID

    assert MUSIC_MODEL_ID in {spec.id for spec in registry.all()}


def test_la_app_arranca_con_lo_que_pone_el_instalador(tmp_root, monkeypatch):
    """El despliegue se cayo por esto y el error no lo decia.

    setup.sh publicaba con el correo del dueno puesto pero conseguia la
    configuracion de Firebase DESPUES. La app se niega a arrancar sin ella —con
    razon: seria una puerta pintada—, asi que el contenedor moria al nacer y
    Cloud Run solo decia "failed to start and listen on the port".

    Esta prueba arranca la app con exactamente las variables que pone el
    instalador. Si vuelven a faltarle, falla aqui y no en un despliegue de diez
    minutos.
    """
    from fastapi.testclient import TestClient

    from app.container import set_studio
    from app.settings import get_settings

    puestas = {
        "AAUS_PROJECT_ID": "",  # sin proyecto: no se toca Firestore de verdad
        "AAUS_LOCATION": "us-central1",
        "AAUS_BUCKET": "",
        "AAUS_OWNER_EMAIL": "dueno@gmail.com",
        "AAUS_SESSION_SECRET": "0" * 48,
        "AAUS_FIREBASE_CONFIG": FIREBASE,
        "AAUS_DRY_RUN": "true",
        "AAUS_LOCAL_DATA_DIR": str(tmp_root / "arranque"),
        "AAUS_STATIC_DIR": str(tmp_root / "sin-frontend"),
    }
    for clave, valor in puestas.items():
        monkeypatch.setenv(clave, valor)
    get_settings.cache_clear()
    set_studio(None)

    try:
        from app.main import app

        with TestClient(app) as cliente:          # dispara el startup de verdad
            assert cliente.get("/api/health").status_code == 200
            assert cliente.get("/api/auth/config").json()["firebase"]["projectId"]
    finally:
        get_settings.cache_clear()
        set_studio(None)


def test_un_fallo_del_servidor_se_cuenta_en_json(studio, monkeypatch):
    """Sin esto, el unico mensaje que llega al telefono es "JSON Parse error:
    Unexpected identifier", que habla del formato de la respuesta y no del
    problema. Paso de verdad, en la primera pantalla.

    El cliente de pruebas relanza por defecto los fallos del servidor, que es lo
    contrario de lo que hay que comprobar aqui: lo que importa es la respuesta
    que sale por el cable.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    def revienta(*_args, **_kwargs):
        raise RuntimeError("la base de datos dijo que no")

    monkeypatch.setattr(studio.db, "list", revienta)
    app.state.studio = studio
    cliente = TestClient(app, raise_server_exceptions=False)

    respuesta = cliente.get("/api/home")
    assert respuesta.status_code == 500
    cuerpo = respuesta.json()          # y no texto plano
    assert cuerpo["error"]["code"] == "internal_error"
    assert "la base de datos dijo que no" in cuerpo["error"]["message"]
    assert cuerpo["error"]["details"]["ruta"] == "/api/home"
    app.state.studio = None


def test_no_se_pide_ningun_indice_compuesto_a_firestore():
    """Firestore exige un indice compuesto para filtrar y ordenar a la vez, y no
    lo dice hasta que la consulta corre de verdad: 400 y un enlace para crearlo
    a mano. Paso en la primera pantalla, recien instalado.

    Filtrar solo, u ordenar solo, usa los indices automaticos. Esta prueba mira
    lo que se le pide a Firestore.
    """
    from app.db import client as modulo

    pedido: dict = {"where": [], "order_by": None, "limit": None}

    class ConsultaFalsa:
        def where(self, filter=None):  # noqa: A002
            pedido["where"].append(filter)
            return self

        def order_by(self, campo, direction=None):
            pedido["order_by"] = campo
            return self

        def limit(self, n):
            pedido["limit"] = n
            return self

        def stream(self, timeout=None):
            # El plazo importa: sin el, una consulta colgada deja la pantalla
            # girando para siempre. Que la falsa lo exija evita quitarlo.
            assert timeout, "toda consulta a Firestore lleva un plazo"
            return iter(())

    class ClienteFalso:
        def collection(self, _ruta):
            return ConsultaFalsa()

    db = modulo.FirestoreDatabase.__new__(modulo.FirestoreDatabase)
    db._client = ClienteFalso()

    db.list("universes/u1/jobs", where={"state": "READY"}, order_by="created_at", limit=10)
    assert len(pedido["where"]) == 1
    assert pedido["order_by"] is None, "pedir orden con filtro exige un indice compuesto"
    assert pedido["limit"] is None, "el limite se aplica despues de ordenar aqui"

    pedido.update({"where": [], "order_by": None, "limit": None})
    db.list("universes", order_by="updated_at", limit=50)
    assert pedido["order_by"] == "updated_at"
    assert pedido["limit"] == 50


def test_los_dos_almacenes_ordenan_igual(tmp_root):
    """Si en memoria y en Firestore el orden no coincide, las pruebas pasan y la
    app se comporta distinto en el telefono."""
    from app.db.client import MemoryDatabase, _sort_key

    db = MemoryDatabase(str(tmp_root / "orden"))
    for i, cuando in enumerate(["2026-01-03", "2026-01-01", "2026-01-02"]):
        db.set(f"c/d{i}", {"id": f"d{i}", "created_at": cuando, "state": "READY"})

    filas = db.list("c", where={"state": "READY"}, order_by="created_at")
    assert [f["created_at"] for f in filas] == ["2026-01-03", "2026-01-02", "2026-01-01"]

    copia = sorted(filas, key=lambda d: _sort_key(d, "created_at"), reverse=True)
    assert copia == filas


def test_no_es_lo_mismo_sin_sesion_que_no_se_puede(client, studio):
    """Los dos son 403, pero el navegador tiene que distinguirlos: ante el
    primero vuelve a la pantalla de entrada, ante el segundo se queda donde
    esta. Sin esto, la primera regla del estudio que conteste 403 echa al
    usuario de la aplicacion sin ninguna explicacion."""
    from app.errors import Forbidden, SinSesion

    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"

    sin = client.get("/api/home")
    assert sin.status_code == 403
    assert sin.json()["error"]["code"] == "sin_sesion"

    # Y una prohibicion del dominio sigue siendo 403 pero con otro codigo.
    assert Forbidden("x").code == "forbidden"
    assert SinSesion("x").status_code == 403
    assert SinSesion("x").code == "sin_sesion"


def test_una_correccion_de_la_semilla_llega_a_una_instalacion_que_ya_existe(studio):
    """Antes solo se sembraba si no habia nada, y eso dejo muerta la correccion
    de los identificadores: la instalacion seguia con los nombres comerciales y
    cada generacion habria muerto en un 404.

    Y al reves: una edicion hecha a mano en Firestore tiene que sobrevivir a los
    despliegues, que es justo para lo que ese documento existe.
    """
    from app.db.repositories import CONFIG_MODELS
    from app.domain.registry import load_seed

    version_actual = int(load_seed()["schema_version"])

    # Una instalacion vieja, con los nombres que no existen en Vertex.
    studio.db.set(
        CONFIG_MODELS,
        {
            "id": "models",
            "schema_version": version_actual - 1,
            "models": [{"id": "veo-3.1", "kind": "video", "label": "viejo",
                        "status": "active", "variants": []}],
            "excluded": [],
        },
    )
    studio._registry = None
    studio.ensure_registry_seeded()

    ids = {spec.id for spec in studio.registry.all()}
    assert "veo-3.1" not in ids
    assert "veo-3.1-generate-001" in ids

    # Ahora una edicion a mano, con la version al dia: no se toca.
    studio.db.set(
        CONFIG_MODELS,
        {
            "id": "models",
            "schema_version": version_actual,
            "models": [{"id": "veo-3.1-generate-001", "kind": "video",
                        "label": "Editado a mano", "status": "active", "variants": []}],
            "excluded": [],
        },
    )
    studio._registry = None
    studio.ensure_registry_seeded()
    assert studio.registry.all()[0].label == "Editado a mano"


def test_en_la_aplicacion_no_se_habla_de_dinero():
    """El gasto se mira en la consola de Google Cloud. Que la app lo repita es
    justo lo que se pidio quitar el primer dia, y se habia colado otra vez en
    la pantalla de Ajustes."""
    import pathlib

    frontend = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    # Solo lo que se pinta. Los tipos de api/types.ts reflejan el documento de
    # Firestore, que si lleva precios: los usa el backend para sus registros.
    pintado = "\n".join(
        p.read_text() for p in frontend.rglob("*.tsx") if p.is_file()
    ) + "\n".join(
        p.read_text() for p in frontend.rglob("*.ts")
        if p.is_file() and p.name not in {"types.ts"}
    )
    # Señales de dinero y nada más: "toFixed" a secas tambien lo usan los
    # segundos de una grabacion, y marcarlo seria una prueba que grita cuando
    # no pasa nada, que es como se aprende a ignorarla.
    for rastro in ("money(", "US$", "$${", "USD", "currency:"):
        assert rastro not in pintado, f"quedo dinero en la interfaz: {rastro}"


def test_la_interfaz_no_lleva_monigotes():
    """No es una aplicacion de ninos.

    Habia un dibujito de persona presidiendo la pantalla de crear artistas, y
    emoji de teclado en la barra de abajo. Eso no es un icono: es el emoji del
    telefono de otra persona, se dibuja distinto en cada sistema y convierte una
    herramienta de trabajo en un juguete.

    Las marcas geometricas —el visto de una etapa aprobada, el circulo de
    grabar— si valen: son tipografia, no dibujos. Por eso el corte esta en el
    bloque de pictogramas, de U+1F300 para arriba.
    """
    import pathlib

    fuente = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    for fichero in sorted(fuente.rglob("*.tsx")) + sorted(fuente.rglob("*.ts")):
        for numero, linea in enumerate(fichero.read_text().splitlines(), 1):
            dibujos = [c for c in linea if ord(c) >= 0x1F300]
            assert not dibujos, f"{fichero.name}:{numero} lleva {''.join(dibujos)}"


def test_todo_lo_que_se_crea_se_puede_borrar(client, universe):
    """Dije que el universo si se podia borrar y era falso: la ruta existia en
    el servidor pero no habia boton en ninguna parte, y una ruta sin boton no
    existe para quien usa la app. Aqui se comprueban las dos mitades."""
    import pathlib
    import re

    creables = {
        "characters": {"name": "Nova", "role": "lead"},
        "wardrobe": {"name": "Chaqueta", "category": "signature"},
        "locations": {"name": "Azotea"},
        "songs": {"title": "Neon"},
    }
    for coleccion, cuerpo in creables.items():
        creado = client.post(f"/api/universes/{universe}/{coleccion}", json=cuerpo)
        assert creado.status_code == 200, f"{coleccion}: {creado.text}"
        doc_id = creado.json()["id"]

        borrado = client.delete(f"/api/universes/{universe}/{coleccion}/{doc_id}")
        assert borrado.status_code == 200, f"{coleccion} no se borra: {borrado.text}"
        quedan = [d["id"] for d in client.get(f"/api/universes/{universe}/{coleccion}").json()]
        assert doc_id not in quedan

    assert client.delete(f"/api/universes/{universe}").status_code == 200

    # La otra mitad: que el boton exista de verdad en alguna pantalla.
    pantallas = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "screens"
    codigo = "\n".join(p.read_text() for p in pantallas.glob("*.tsx"))
    for ruta in ("/characters/", "/wardrobe/", "/locations/", "/songs/", "/video-projects/"):
        assert f"api.del(`/api/universes/${{universeId}}{ruta}" in codigo, f"sin boton: {ruta}"
    # El artista entero. La expresion exacta cambia si el boton se muda de
    # pantalla —y se mudo, de la portada a la pantalla del propio artista— asi
    # que lo que se comprueba es la llamada, no donde vive.
    borra_artista = re.search(
        r"api\.del\(`/api/universes/\$\{[A-Za-z.]+\}`\)", codigo
    )
    assert borra_artista, "sin boton: el artista"


def test_ninguna_pantalla_obliga_a_escribir_un_nombre():
    """Las dos mitades: que la ruta exista y que el boton este puesto.

    "Para que estan los directores. Mi intencion es automatizar; si no, mejor lo
    hago yo a mano desde el principio." Tenia razon: cada atuendo, cada locacion
    y cada personaje habia que crearlos escribiendo un nombre y una descripcion.

    Se comprueba lo mismo que con los botones de borrar, y por la misma razon:
    una ruta sin boton no existe para quien usa la app, y un boton sin ruta es
    un error rojo.
    """
    import pathlib as rutas

    fuente = rutas.Path(__file__).resolve().parents[2] / "frontend" / "src"
    codigo = "\n".join(f.read_text() for f in fuente.rglob("*.tsx"))
    for ruta in ("wardrobe", "locations", "characters"):
        assert f'ruta="{ruta}"' in codigo, f"sin boton de proponer: {ruta}"
    assert "/${ruta}/propose" in codigo, "el boton no llama a ninguna ruta"


def test_los_enlaces_se_firman_pidiendoselo_a_google():
    """En Cloud Run no hay clave privada con la que firmar.

    Las credenciales del servidor de metadatos solo traen un token. Si no se le
    dice a quien pedirle la firma, la libreria intenta firmar en local y
    contesta "you need a private key to sign credentials", que fue justo lo que
    salio en pantalla DESPUES de generar y pagar la imagen.

    Yo habia escrito un comentario diciendo que esto funcionaba. No lo comprobe.
    """
    from app.providers.storage import GcsStorage

    pedido = {}

    class BlobFalso:
        def generate_signed_url(self, **kwargs):
            pedido.update(kwargs)
            return "https://firmado"

    almacen = GcsStorage.__new__(GcsStorage)
    almacen._bucket = type("B", (), {"blob": lambda self, p: BlobFalso()})()
    almacen._firmante = lambda: ("aaus-run@proyecto.iam.gserviceaccount.com", "un-token")

    assert almacen.signed_url("universes/u/character/a.png") == "https://firmado"
    assert pedido["service_account_email"].startswith("aaus-run@")
    assert pedido["access_token"] == "un-token"
    assert pedido["version"] == "v4"


def test_generar_algo_no_depende_de_poder_firmar_un_enlace():
    """Un enlace que no se puede firmar no puede tirar el trabajo entero.

    La imagen se generaba, se guardaba, se pagaba... y entonces el trabajo
    moria al firmar el enlace y la pantalla decia FALLO. El archivo estaba en el
    bucket y no habia forma de saberlo.

    Ademas un enlace firmado caduca en una hora, asi que guardarlo en la base de
    datos era guardar basura. La verdad es la ruta; el enlace se firma al
    leerlo, que es cuando sirve.
    """
    import pathlib as rutas

    handlers = rutas.Path(__file__).resolve().parents[1] / "app" / "orchestrator" / "handlers.py"
    assert "signed_url" not in handlers.read_text(), (
        "generar algo volvio a depender de firmar un enlace"
    )


def test_la_cola_puede_entrar_con_su_pase(client, studio):
    """El camino que hace que un trabajo pase de "en cola" a hecho.

    Cloud Tasks vuelve a llamar a /api/internal/jobs/run con el pase que firmo
    esta misma aplicacion. Ya se comprueba que la cookie del navegador NO vale
    ahi; falta lo contrario: que el pase si abra. Si esa puerta estuviera mal
    cerrada del otro lado, cada trabajo se quedaria en cola para siempre y en la
    pantalla no habria ningun error que mirar, que es la peor forma de fallar.
    """
    from app.auth import COLA, firmar_encargo

    clave = "un-secreto-de-treinta-y-dos-caracteres"
    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = clave
    studio.settings.tasks_target_url = "https://aaus-abc.a.run.app"

    cuerpo = {"universe_id": "uni_inventado", "job_id": "job_inventado"}

    # Sin pase, fuera.
    assert client.post("/api/internal/jobs/run", json=cuerpo).status_code == 403

    # Con un pase firmado con otra clave, tambien fuera.
    ajeno = firmar_encargo(cuerpo["universe_id"], cuerpo["job_id"], "clave-de-otro")
    assert client.post(
        "/api/internal/jobs/run", json=cuerpo, headers={COLA: ajeno}
    ).status_code == 403

    # Con el pase bueno entra: llega al orquestador y este contesta que ese
    # trabajo no existe, que es lo correcto para un id inventado.
    pase = firmar_encargo(cuerpo["universe_id"], cuerpo["job_id"], clave)
    respuesta = client.post("/api/internal/jobs/run", json=cuerpo, headers={COLA: pase})
    assert respuesta.status_code == 404, respuesta.text
    assert respuesta.json()["error"]["code"] == "not_found"

    # Y un pase bueno de OTRO trabajo no sirve para este.
    otro = firmar_encargo("uni_inventado", "job_distinto", clave)
    assert client.post(
        "/api/internal/jobs/run", json=cuerpo, headers={COLA: otro}
    ).status_code == 403


def test_el_bucle_entero_de_la_cola(client, studio, universe):
    """Encargar, entregar y ejecutar, sin dar nada por hecho.

    Aqui han ido a morir dos fallos seguidos -una audiencia mal puesta y un
    permiso que faltaba- y las dos veces el sintoma fue el mismo: nada. El
    trabajo se quedaba "en cola" y no habia error que mirar.

    Las otras pruebas miran cada mitad por separado: que build_task prepara un
    pase, y que la puerta acepta un pase escrito a mano. Esta las junta: lo que
    build_task prepara se entrega tal cual, con la puerta cerrada, y el trabajo
    tiene que terminar hecho.
    """
    from app.services.jobs import JobService

    personaje = client.post(
        f"/api/universes/{universe}/characters", json={"name": "Nova", "role": "lead"}
    ).json()

    # Y ahora la puerta, cerrada de verdad: sin el pase esto seria un 403.
    studio.settings.owner_email = "dueno@gmail.com"
    studio.settings.firebase_config = FIREBASE
    studio.settings.session_secret = "un-secreto-de-treinta-y-dos-caracteres"
    studio.settings.tasks_target_url = "https://aaus-abc.a.run.app"

    trabajo = studio.jobs.create(
        universe,
        kind="image",
        model="gemini-3-pro-image",
        variant="1K",
        target_type="character",
        target_id=personaje["id"],
        request={"kind": "image", "prompt": "retrato", "target_type": "character",
                 "target_id": personaje["id"], "shot_key": "front"},
        estimated_cost_usd=0.0,
    )

    tarea = JobService(studio.db, studio.settings).build_task(universe, trabajo["id"], "POST")
    peticion = tarea["http_request"]

    respuesta = client.post(
        "/api/internal/jobs/run",
        content=peticion["body"],
        headers=peticion["headers"],
    )
    assert respuesta.status_code == 200, respuesta.text
    assert studio.jobs.get(universe, trabajo["id"])["state"] != "QUEUED"


def test_un_trabajo_que_no_se_pudo_encargar_no_dice_en_cola(studio, universe, monkeypatch):
    """La pantalla decia "EN COLA" sobre un trabajo que nunca llego a existir.

    El documento se escribe como en cola antes de encargarlo de verdad; si el
    encargo falla -un permiso que falta- y nadie corrige ese estado, ahi se
    queda para siempre. Un estado falso es peor que un error: con el error se
    sabe que hacer, con el estado falso se espera.
    """
    from app.domain.enums import JobState

    trabajo = studio.jobs.create(
        universe, kind="text", model="gemini-3.1-pro-preview", variant="default",
        target_type="song", target_id="x", request={}, estimated_cost_usd=0.0,
    )
    assert trabajo["state"] == JobState.QUEUED.value

    def no_se_puede(*_a, **_k):
        raise RuntimeError("lacks IAM permission iam.serviceAccounts.actAs")

    monkeypatch.setattr(studio.jobs, "_run_inline", no_se_puede)
    monkeypatch.setattr(studio.jobs, "_enqueue_cloud_task", no_se_puede)

    with pytest.raises(RuntimeError):
        studio.jobs.enqueue(universe, trabajo["id"])

    despues = studio.jobs.get(universe, trabajo["id"])
    assert despues["state"] == JobState.FAILED.value
    assert "No se pudo encargar" in despues["error"]
