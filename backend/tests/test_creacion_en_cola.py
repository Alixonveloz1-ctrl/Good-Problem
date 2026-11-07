"""La creacion del artista contesta enseguida (2026-11).

El caso real: el usuario creo su artista nuevo con cuatro enlaces de
referencia y la pantalla le dijo «El estudio tardo demasiado en
contestar». Era un error FALSO: la creacion analizaba los enlaces
dentro de la peticion, en serie, y tardaba mas que los 45 segundos que
la pantalla espera — pero en el servidor si se completaba. Su toque
repetido (el propio error invita a reintentar) dejo el artista
DUPLICADO: dos universos identicos.

La reparacion, fijada aqui:

1. Crear contesta en menos de un segundo: los enlaces quedan como
   PENDIENTES en la Biblia y un trabajo de creacion en la cola los
   analiza — en serie, dentro del trabajo — guardando cada resumen y
   cada fallo con la semantica visible de siempre.
2. Solo cuando los resumenes ya estan guardados, ese trabajo encarga
   el diseno del personaje: el orden analisis→Biblia→diseno no cambia.
3. La creacion lleva la clave de idempotencia del formulario: un
   doble toque o un reintento tras un corte devuelve EL MISMO
   artista.
4. Mientras los analisis siguen pendientes, pedir la Biblia avisa
   claro en vez de generarla en silencio sin las referencias.
5. Crear sin enlaces sigue siendo lo de siempre: sin trabajo de
   analisis, el diseno encargado directamente. Y una Biblia guardada
   antes de que existieran los pendientes se lee sin pendientes.

Los analisis estan simulados: ninguna prueba paga una generacion.
"""

from __future__ import annotations

from app.domain.enums import JobState
from app.domain.schemas import Inspiration
from app.errors import ProviderError
from app.services import inspiration as inspiration_service
from app.services.context import bible_path, load_bible

_ENLACE_OK = "https://www.youtube.com/watch?v=buena12345"
_ENLACE_MALO = "https://www.youtube.com/watch?v=mala123456"


def _sin_entregar(studio, monkeypatch):
    """La cola no entrega nada: los trabajos se quedan QUEUED a la vista.

    Es lo que permite mirar el estado intermedio con calma: la creacion
    ya contesto y el trabajo de analisis todavia no ha corrido.
    """
    monkeypatch.setattr(studio.jobs, "enqueue", lambda u, j: None)


def _analisis(monkeypatch, *, fallan=()):
    """El analisis simulado: cuenta las llamadas y resuelve al momento."""
    llamadas: list[str] = []

    def fake(studio, url):
        llamadas.append(url)
        if url in fallan:
            raise ProviderError("Vertex no respondio")
        inspiracion = Inspiration(
            url=url,
            title="La cancion analizada",
            genres="Rap con guitarra",
            rhythm="Lento y medido",
            instruments=["guitarra"],
            structure="verso, coro",
            mood="Denso",
            lyric_themes=["el barrio"],
            lyric_style="Narrativo",
        )
        inspiracion.summary_text = inspiration_service.summary_text(inspiracion)
        return inspiracion

    monkeypatch.setattr(inspiration_service, "analyse_youtube", fake)
    return llamadas


def _trabajos(studio, uid):
    return studio.jobs.repo(uid).list(limit=100)


# --- 1. Contesta enseguida, con el trabajo en cola -------------------------


def test_crear_con_enlaces_contesta_sin_analizar_y_deja_el_trabajo_en_cola(
    client, studio, monkeypatch
):
    _sin_entregar(studio, monkeypatch)
    llamadas = _analisis(monkeypatch)

    respuesta = client.post(
        "/api/universes",
        json={
            "name": "Nova",
            "gender": "mujer",
            "inspiration_urls": [_ENLACE_OK, _ENLACE_MALO],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    creado = respuesta.json()

    # El analisis NO paso por la peticion: ni una sola llamada todavia.
    assert llamadas == []
    # El trabajo de creacion esta en cola, con los enlaces dentro.
    trabajo = creado["job"]
    assert trabajo["kind"] == "creation"
    assert trabajo["state"] == JobState.QUEUED.value
    assert trabajo["request"]["payload"]["inspiration_urls"] == [
        _ENLACE_OK,
        _ENLACE_MALO,
    ]
    # Y la Biblia los enseña como pendientes, sin resumenes todavia:
    # su analisis esta en camino y se ve.
    biblia = load_bible(studio.db, creado["id"])
    assert biblia.inspirations_pending == [_ENLACE_OK, _ENLACE_MALO]
    assert biblia.inspirations == []
    assert biblia.inspirations_failed == []
    # El artista existe ya, con su protagonista: lo rapido si se hizo.
    personajes = client.get(f"/api/universes/{creado['id']}/characters").json()
    assert len(personajes) == 1
    assert personajes[0]["id"] == creado["lead_character_id"]


# --- 2. El trabajo guarda, y solo entonces encarga el diseno ---------------


def test_el_trabajo_guarda_resumenes_y_fallos_y_solo_entonces_encarga_el_diseno(
    client, studio, monkeypatch
):
    _sin_entregar(studio, monkeypatch)
    _analisis(monkeypatch, fallan={_ENLACE_MALO})

    # El espia mira la Biblia en el instante exacto en que se encarga
    # el diseno: los resumenes tienen que estar YA guardados.
    original_submit = studio.orchestrator.submit
    al_encargar: dict[str, int] = {}

    def espia(request):
        if (request.payload or {}).get("task") == "character":
            al_encargar["resumenes"] = len(
                load_bible(studio.db, request.universe_id).inspirations
            )
        return original_submit(request)

    monkeypatch.setattr(studio.orchestrator, "submit", espia)

    creado = client.post(
        "/api/universes",
        json={
            "name": "Nova",
            "gender": "mujer",
            "inspiration_urls": [_ENLACE_OK, _ENLACE_MALO],
        },
    ).json()
    uid = creado["id"]
    # Sin el trabajo, todavia no hay encargo de diseno: solo el de creacion.
    assert [t["kind"] for t in _trabajos(studio, uid)] == ["creation"]

    terminado = studio.orchestrator.run_job(uid, creado["job"]["id"])
    assert terminado["state"] == JobState.READY.value

    biblia = load_bible(studio.db, uid)
    assert [i.title for i in biblia.inspirations] == ["La cancion analizada"]
    assert biblia.inspirations_failed == [_ENLACE_MALO]
    assert biblia.inspirations_pending == []

    # El diseno se encargo DESPUES de guardar: el espia lo vio con el
    # resumen ya dentro, y el trabajo de diseno existe ahora.
    assert al_encargar["resumenes"] == 1
    disenos = [
        t
        for t in _trabajos(studio, uid)
        if t["kind"] == "text" and (t["request"].get("payload") or {}).get("task") == "character"
    ]
    assert len(disenos) == 1
    assert disenos[0]["target_id"] == creado["lead_character_id"]


def test_reintentar_el_trabajo_no_duplica_los_resumenes(client, studio, monkeypatch):
    """Un reintento tras un corte a mitad de cadena no repite lo hecho."""
    _sin_entregar(studio, monkeypatch)
    _analisis(monkeypatch)

    creado = client.post(
        "/api/universes",
        json={"name": "Nova", "gender": "mujer", "inspiration_urls": [_ENLACE_OK]},
    ).json()
    uid = creado["id"]
    job_id = creado["job"]["id"]
    assert studio.orchestrator.run_job(uid, job_id)["state"] == JobState.READY.value

    studio.jobs.repo(uid).update(job_id, {"state": JobState.QUEUED.value})
    assert studio.orchestrator.run_job(uid, job_id)["state"] == JobState.READY.value

    biblia = load_bible(studio.db, uid)
    assert len(biblia.inspirations) == 1
    assert biblia.inspirations_pending == []


# --- 3. Idempotencia: la misma clave, el mismo artista ---------------------


def test_la_misma_clave_devuelve_el_mismo_artista(client, studio, monkeypatch):
    _sin_entregar(studio, monkeypatch)
    _analisis(monkeypatch)
    cuerpo = {
        "name": "Nova",
        "gender": "mujer",
        "inspiration_urls": [_ENLACE_OK],
        "idempotency_key": "formulario-uno",
    }

    primero = client.post("/api/universes", json=cuerpo)
    assert primero.status_code == 200, primero.text
    repetido = client.post("/api/universes", json=cuerpo)
    assert repetido.status_code == 200, repetido.text

    # El mismo artista, y una sola vez en la lista: no hay duplicado.
    assert repetido.json()["id"] == primero.json()["id"]
    assert repetido.json()["lead_character_id"] == primero.json()["lead_character_id"]
    universos = client.get("/api/universes").json()
    assert [u["id"] for u in universos] == [primero.json()["id"]]
    # Ni siquiera se creo un segundo trabajo de creacion.
    assert len(_trabajos(studio, primero.json()["id"])) == 1

    # Otra clave es otra apertura del formulario: otro artista.
    otro = client.post(
        "/api/universes", json={**cuerpo, "idempotency_key": "formulario-dos"}
    )
    assert otro.status_code == 200, otro.text
    assert otro.json()["id"] != primero.json()["id"]
    assert len(client.get("/api/universes").json()) == 2


# --- 4. Sin enlaces no hay trabajo de analisis ------------------------------


def test_crear_sin_enlaces_no_encola_ningun_analisis(client, studio, monkeypatch):
    _sin_entregar(studio, monkeypatch)
    llamadas = _analisis(monkeypatch)

    creado = client.post("/api/universes", json={"name": "Nova", "gender": "mujer"})
    assert creado.status_code == 200, creado.text
    creado = creado.json()

    # El unico trabajo es el diseno del personaje, encargado como siempre.
    trabajos = _trabajos(studio, creado["id"])
    assert [t["kind"] for t in trabajos] == ["text"]
    assert creado["job"]["kind"] == "text"
    assert llamadas == []
    assert load_bible(studio.db, creado["id"]).inspirations_pending == []


# --- 5. La puerta de la Biblia y las Biblias viejas -------------------------


def test_reescribir_la_biblia_con_analisis_en_curso_avisa_y_no_genera(
    client, studio, monkeypatch
):
    _sin_entregar(studio, monkeypatch)
    _analisis(monkeypatch)

    creado = client.post(
        "/api/universes",
        json={"name": "Nova", "gender": "mujer", "inspiration_urls": [_ENLACE_OK]},
    ).json()
    uid = creado["id"]

    respuesta = client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    assert respuesta.status_code == 409, respuesta.text
    mensaje = respuesta.json()["error"]["message"]
    assert "analizando" in mensaje
    # Y no se creo ningun trabajo de Biblia a escondidas.
    assert [
        t
        for t in _trabajos(studio, uid)
        if t["target_type"] == "artist_bible" and t["kind"] == "text"
    ] == []

    # Cuando el trabajo de creacion termina, la misma peticion ya entra.
    assert (
        studio.orchestrator.run_job(uid, creado["job"]["id"])["state"]
        == JobState.READY.value
    )
    respuesta = client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    assert respuesta.status_code == 200, respuesta.text


def test_una_biblia_guardada_sin_el_campo_se_lee_sin_pendientes(client, studio):
    """Compatibilidad: las Biblias de antes no tienen el campo nuevo."""
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    doc = studio.db.get(bible_path(uid))
    doc.pop("inspirations_pending", None)
    studio.db.set(bible_path(uid), doc)

    assert load_bible(studio.db, uid).inspirations_pending == []
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["inspirations_pending"] == []
