"""El nombre del artista tiene casa: su ficha (2026-11).

El problema, verificado en vivo: el nombre del artista no vivia en
ninguna pantalla. La ficha del personaje nace con el nombre del
formulario de creacion (el del UNIVERSO: «Verso Oscuro»), la Biblia lo
guardaba del Director («K-Ronte») hasta que una reescritura lo sobrescribio
con el del universo, y no existia ningun campo editable de nombre en
ninguna parte — ni en Identidad/Biblia (esa ficha no se edita a mano, por
diseno) ni en el dialogo de rasgos del personaje.

El arreglo sigue la doctrina del estudio — cada dato vive en SU ficha y
las demas lo toman de ahi, como ya pasaba con la edad:

1. El nombre se escribe en la ficha del artista (el PATCH ya admitia
   `name`; faltaban el campo en la pantalla y la sincronia al guardarlo).
2. sync_bible_identity: stage_name y fictional_name de la identidad
   siguen al nombre de la ficha; y al nacer, al reves una sola vez: si
   la ficha todavia lleva el nombre del formulario (el del universo) y
   la primera Biblia del Director trae el nombre del artista, la ficha
   lo ADOPTA — desde ahi manda ella.
3. El bloque decidido de la reescritura presenta el nombre de la ficha
   primero (4321e98 lo dejo guardado-primero, y eso congelaba el nombre
   mal guardado); la fusion restaura hacia el mismo valor que manda.
4. El saneo del genero: la linea «Genero» de la pantalla pinta el
   musical.genre GUARDADO tal cual; quedo contaminado con el texto
   libre entero en la reescritura de las 12:51, ANTES de que existiera
   la guardia de la fusion, y la guardia conservaba el guardado — o
   sea, conservaba la contaminacion. Al leer, un guardado contaminado
   cede ante la etiqueta del primer genero elegido.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.db.repositories import CHARACTERS, Repository
from app.domain.enums import JobState
from app.services.context import load_bible, save_bible

_MEZCLA = (
    "rap poético y oscuro estilo Canserbero, flow melódico y gancho "
    "comercial estilo Bad Bunny, lírica densa y contestataria estilo "
    "Aldo el Aldeano (Los Aldeanos)"
)
_GENERO_CONTAMINADO = f"Rap / hip-hop + Trap + Reguetón + {_MEZCLA}"
_SECCIONES = ("identity", "musical", "communication", "visual")


def _protagonista(client, uid):
    respuesta = client.get(f"/api/universes/{uid}/characters")
    assert respuesta.status_code == 200, respuesta.text
    personajes = respuesta.json()
    return next(
        (c for c in personajes if c.get("role") == "lead"), personajes[0]
    )


def _biblia(client, uid):
    respuesta = client.get(f"/api/universes/{uid}/bible")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --- 1+2. El nombre se escribe en su ficha y la identidad lo toma -------


def test_el_nombre_se_escribe_en_la_ficha_y_la_identidad_lo_toma(
    client, studio, universe
):
    uid = universe
    studio.jobs.wait_for_idle(20)
    artista = _protagonista(client, uid)
    assert artista["name"] == "Nova"  # nacio con el nombre del formulario

    respuesta = client.patch(
        f"/api/universes/{uid}/characters/{artista['id']}",
        json={"name": "K-Ronte"},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["name"] == "K-Ronte"
    assert _protagonista(client, uid)["name"] == "K-Ronte"

    biblia = _biblia(client, uid)
    assert biblia["identity"]["stage_name"] == "K-Ronte"
    assert biblia["identity"]["fictional_name"] == "K-Ronte"


def test_la_edad_sigue_sincronizando_junto_al_nombre(client, studio, universe):
    """El control de siempre, con el nombre ya en su ficha: la edad de
    los rasgos sigue mandando en la edad aparente de la identidad."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    artista = _protagonista(client, uid)
    client.patch(
        f"/api/universes/{uid}/characters/{artista['id']}",
        json={"name": "K-Ronte"},
    )
    client.patch(
        f"/api/universes/{uid}/characters/{artista['id']}",
        json={"rasgos": {"edad": "21"}},
    )
    biblia = _biblia(client, uid)
    assert biblia["identity"]["apparent_age"] == "21 años"
    assert biblia["identity"]["stage_name"] == "K-Ronte"


# --- 4. Al nacer: la ficha adopta el nombre de la primera Biblia --------


def test_la_ficha_adopta_el_nombre_de_la_primera_biblia(
    client, studio, universe
):
    """La forma exacta del nacimiento de K-Ronte: la ficha nace con el
    nombre del universo («Nova» aqui) y la primera Biblia del Director
    trae el nombre del artista. Al leer la Biblia, la ficha lo adopta;
    desde ahi el nombre vive en la ficha y la identidad lo sigue a el."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    assert _protagonista(client, uid)["name"] == "Nova"

    biblia = load_bible(studio.db, uid)
    biblia.identity.stage_name = "K-Ronte"
    biblia.identity.fictional_name = "K-Ronte"
    save_bible(studio.db, uid, biblia)

    leida = _biblia(client, uid)
    assert leida["identity"]["stage_name"] == "K-Ronte"
    assert _protagonista(client, uid)["name"] == "K-Ronte"


# --- 3. La reescritura presenta el nombre de la ficha --------------------


def _llamada_biblia(studio):
    for llamada in reversed(studio.calls.all()):
        if llamada.method != "generateContent":
            continue
        partes = llamada.payload["contents"][0]["parts"]
        if any("Build a complete Artist Bible" in (p.get("text") or "") for p in partes):
            return "\n".join(p.get("text") or "" for p in partes)
    raise AssertionError("ninguna llamada de Biblia registrada")


def _bloque_decidido(prompt: str) -> str:
    """Solo el bloque «THE ARTIST, AS DECIDED»: el borrador que viaja
    despues trae su propia linea «Stage name:» con el nombre guardado,
    y mezclar los dos haria la asercion sobre el sitio equivocado."""
    inicio = prompt.index("THE ARTIST, AS DECIDED")
    fin = prompt.index("CURRENT VERSION TO REWRITE")
    return prompt[inicio:fin]


def test_la_llamada_presenta_el_nombre_de_la_ficha_aunque_la_guardada_diga_otro(
    client, studio, universe
):
    uid = universe
    studio.jobs.wait_for_idle(20)
    repo = Repository(studio.db, uid, CHARACTERS)
    artista = _protagonista(client, uid)
    repo.update(artista["id"], {"name": "K-Test"})
    biblia = load_bible(studio.db, uid)
    biblia.identity.stage_name = "Nombre Viejo"
    save_bible(studio.db, uid, biblia)

    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    studio.jobs.wait_for_idle(20)

    prompt = _bloque_decidido(_llamada_biblia(studio))
    assert "Stage name: K-Test" in prompt
    assert "Stage name: Nombre Viejo" not in prompt


def test_la_llamada_usa_el_guardado_cuando_la_ficha_aun_es_el_formulario(
    client, studio, universe
):
    """El recurso: la ficha todavia dice «Nova» (el nombre del universo,
    el del formulario) y el unico nombre de artista que existe es el de
    la Biblia. El bloque lo presenta a el, no el del proyecto."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    biblia = load_bible(studio.db, uid)
    biblia.identity.stage_name = "K-Ronte"
    save_bible(studio.db, uid, biblia)

    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    studio.jobs.wait_for_idle(20)

    prompt = _bloque_decidido(_llamada_biblia(studio))
    assert "Stage name: K-Ronte" in prompt
    assert "Stage name: Nova" not in prompt


# --- 5. El genero: la pantalla pinta el guardado, y el guardado se sanea -


def _biblia_con_genero_contaminado(studio, uid):
    biblia = load_bible(studio.db, uid)
    biblia.music_genres = ["rap", "trap"]
    biblia.music_genre_free = _MEZCLA
    biblia.musical.genre = _GENERO_CONTAMINADO
    save_bible(studio.db, uid, biblia)
    return load_bible(studio.db, uid)


def test_el_genero_guardado_contaminado_se_sanea_al_leer(
    client, studio, universe
):
    """El estado final exigible para K-Ronte: la linea «Genero» de su
    identidad musical vuelve a la etiqueta corta de su genero
    principal, sin tocar ni su eleccion de generos ni su mezcla libre
    (que son suyos y alimentan «Suena a» desde sus propios campos)."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    _biblia_con_genero_contaminado(studio, uid)

    leida = _biblia(client, uid)
    assert leida["musical"]["genre"] == "Rap / hip-hop"
    assert leida["music_genres"] == ["rap", "trap"]
    assert leida["music_genre_free"] == _MEZCLA
    # Y queda guardado asi, no solo pintado: la siguiente lectura lee
    # el dato ya limpio.
    assert load_bible(studio.db, uid).musical.genre == "Rap / hip-hop"


def test_el_genero_limpio_no_se_toca_al_leer(client, studio, universe):
    """El control contrario: una etiqueta corta legitima, aunque no sea
    el primer genero elegido, se queda como esta."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    biblia = load_bible(studio.db, uid)
    biblia.music_genres = ["rap", "trap"]
    biblia.music_genre_free = _MEZCLA
    biblia.musical.genre = "Trap latino"
    save_bible(studio.db, uid, biblia)

    assert _biblia(client, uid)["musical"]["genre"] == "Trap latino"


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


def test_la_fusion_no_conserva_un_genero_guardado_contaminado(
    studio, universe, monkeypatch
):
    """La reescritura sobre un guardado YA contaminado: el Director
    devuelve otra vez el texto entero (lo leyo en el borrador) y un
    cambio de verdad. Conserva la guardia de 4321e98, el resultado no
    puede ser el guardado tal cual: el campo queda en la etiqueta."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_con_genero_contaminado(studio, uid)

    datos = {seccion: antes.model_dump()[seccion] for seccion in _SECCIONES}
    datos["identity"] = {
        **datos["identity"],
        "personality": "Reflexivo, poetico y sonador.",
    }
    assert datos["musical"]["genre"] == _GENERO_CONTAMINADO
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.musical.genre == "Rap / hip-hop"
    assert despues.identity.personality == "Reflexivo, poetico y sonador."
    assert despues.music_genre_free == _MEZCLA
