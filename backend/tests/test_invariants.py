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
    assert len(studio.jobs.list(uid, limit=50)) == 1


# --- Model resolution order (PRD 42.8) ------------------------------------


def test_user_choice_beats_the_bible_preference(studio, client):
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    client.put(
        f"/api/universes/{uid}/bible/preferences",
        json={"preferred_image_model": "gemini-3.1-flash-lite-image"},
    )
    chosen = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id=uid, kind="image", model="gemini-3-pro-image")
    )
    assert (chosen.spec.id, chosen.source) == ("gemini-3-pro-image", "user")

    fallback = studio.orchestrator.resolve_model(
        GenerationRequest(universe_id=uid, kind="image")
    )
    assert (fallback.spec.id, fallback.source) == ("gemini-3.1-flash-lite-image", "bible")


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

    Eso solo se cumple si van por Cloud Tasks. La audiencia del token se pone a
    mano: si se deja al valor por defecto, Cloud Tasks firma para la URL con su
    ruta, el worker comprueba contra la URL base, y cada trabajo muere en un 401.
    """
    from app.services.jobs import JobService

    settings.tasks_queue = "aaus-generation"
    settings.tasks_target_url = "https://aaus-abc.a.run.app"
    settings.tasks_service_account = "aaus-tasks@proyecto.iam.gserviceaccount.com"

    tarea = JobService(studio.db, settings).build_task("uni_1", "job_1", "POST")
    peticion = tarea["http_request"]

    assert peticion["url"] == "https://aaus-abc.a.run.app/api/internal/jobs/run"
    assert peticion["oidc_token"]["audience"] == "https://aaus-abc.a.run.app"
    assert peticion["oidc_token"]["service_account_email"].startswith("aaus-tasks@")


def test_la_audiencia_del_token_es_la_que_el_worker_comprueba(settings, studio):
    """El que firma y el que comprueba tienen que mirar el mismo sitio.

    Estas dos lineas viven en archivos distintos y nadie las lee juntas. Esta
    prueba es el unico sitio donde se encuentran.
    """
    from app.services.jobs import JobService

    settings.tasks_target_url = "https://aaus-abc.a.run.app/"
    settings.tasks_service_account = "aaus-tasks@proyecto.iam.gserviceaccount.com"

    tarea = JobService(studio.db, settings).build_task("uni_1", "job_1", "POST")
    firmada = tarea["http_request"]["oidc_token"]["audience"]

    # Lo mismo que comprueba verify_service_token al recibir la peticion.
    from app.auth import service_audience

    assert firmada == service_audience(settings) == "https://aaus-abc.a.run.app"


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

        def stream(self):
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
