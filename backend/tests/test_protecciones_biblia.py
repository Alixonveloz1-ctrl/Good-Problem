"""Las protecciones que faltaban (2026-11): el nombre y el genero no se tocan.

La primera reescritura real tras el arreglo del eco funciono — los temas
nuevos eran los del artista — pero la salida trajo dos defectos, ambos
verificados en la Biblia guardada de un artista real:

1. El Director renombro al artista con el nombre del UNIVERSO: la
   identidad quedo con stage_name y fictional_name = «Verso Oscuro» en
   vez de «K-Ronte». Dos puertas lo dejaron pasar: el bloque «THE
   ARTIST, AS DECIDED» del prompt tomaba el nombre de una cadena que
   caia al nombre del universo (y la ficha del personaje nace con el
   nombre del formulario de creacion, que es el del universo), y la
   fusion pintaba el nombre devuelto encima del guardado, sin la
   proteccion que ya tenian el estilo visual y la voz fija.
2. El campo genre de la identidad musical volvio contaminado con el
   texto largo de «Suena a» — la mezcla libre de generos del usuario,
   palabra por palabra — cuando genre es la etiqueta corta del genero
   principal («Rap / hip-hop»).

Arreglos: la fusion restaura los nombres guardados y conserva el genero
guardado si lo devuelto es el texto libre o no cabe en una etiqueta; el
bloque decidido lleva el nombre de la identidad guardada o el de la
ficha del personaje, el nombre del universo viaja rotulado como
proyecto — nunca como nombre del artista — y el encargo dice que genre
es solo la etiqueta corta.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.db.repositories import CHARACTERS, Repository
from app.domain.enums import JobState
from app.services.context import load_bible, save_bible

_SECCIONES = ("identity", "musical", "communication", "visual")
_TEXTO_LIBRE = (
    "Rap / hip-hop + Trap + Reguetón + rap poético y oscuro estilo "
    "Canserbero, flow melódico y gancho comercial estilo Bad Bunny, "
    "lírica densa y contestataria estilo Aldo el Aldeano (Los Aldeanos), "
    "técnica, métrica y orgullo venezolano estilo Akapellah"
)


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


def _biblia_de_k_ronte(studio, uid):
    """La Biblia guardada tal como estaba antes de la reescritura real:
    el artista se llama K-Ronte, su genero es la etiqueta corta y su
    mezcla libre vive en su propio campo, no dentro de genre."""
    biblia = load_bible(studio.db, uid)
    biblia.identity.stage_name = "K-Ronte"
    biblia.identity.fictional_name = "Carlos Eduardo Mendoza"
    biblia.identity.personality = "Serio, intenso e introspectivo."
    biblia.identity.backstory = "Nacido y criado en los barrios de Caracas."
    biblia.identity.recurring_themes = ["la traicion y las falsas amistades"]
    biblia.musical.genre = "Rap / hip-hop"
    biblia.musical.mood = "Oscuro y tenso"
    biblia.music_genre_free = _TEXTO_LIBRE
    biblia.communication.speech_style = "Directo y sentenciador"
    biblia.visual.aesthetic = "Urbano nocturno"
    save_bible(studio.db, uid, biblia)
    return load_bible(studio.db, uid)


def _eco_de(biblia) -> dict:
    volcado = biblia.model_dump()
    return {seccion: volcado[seccion] for seccion in _SECCIONES}


# --- 1. La fusion: el nombre del artista no lo cambia el Director ---------


def test_el_director_no_puede_renombrar_al_artista(studio, universe, monkeypatch):
    """La forma exacta del defecto real: el resultado trae el nombre del
    universo como nombre artistico y ficticio, junto a un cambio de
    verdad. Al aplicar, los nombres guardados se quedan y el cambio
    real si se aplica."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_de_k_ronte(studio, uid)

    datos = _eco_de(antes)
    datos["identity"] = {
        **datos["identity"],
        "stage_name": "Verso Oscuro",
        "fictional_name": "Verso Oscuro",
        "personality": "Reflexivo, poetico y sonador.",
    }
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.identity.stage_name == "K-Ronte"
    assert despues.identity.fictional_name == "Carlos Eduardo Mendoza"
    assert despues.identity.personality == "Reflexivo, poetico y sonador."
    assert despues.version == antes.version + 1


# --- 2. La fusion: genre es la etiqueta corta, no el texto de «Suena a» ---


def test_el_texto_libre_no_contamina_el_campo_genre(studio, universe, monkeypatch):
    """El defecto real, palabra por palabra: genre volvio con la mezcla
    libre entera. Se conserva la etiqueta guardada; el resto del cambio
    se aplica igual."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_de_k_ronte(studio, uid)

    datos = _eco_de(antes)
    datos["musical"] = {
        **datos["musical"],
        "genre": _TEXTO_LIBRE,
        "mood": "Calido y comercial",
    }
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.musical.genre == "Rap / hip-hop"
    assert despues.musical.mood == "Calido y comercial"


def test_un_genre_que_no_cabe_en_una_etiqueta_tampoco_contamina(
    studio, universe, monkeypatch
):
    """La otra mitad de la guardia: aunque no sea el texto libre, un
    genre que no cabe en una etiqueta corta no es un genero."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_de_k_ronte(studio, uid)

    datos = _eco_de(antes)
    datos["musical"] = {
        **datos["musical"],
        "genre": "Una descripcion larguisima del sonido del artista " * 4,
        "mood": "Calido y comercial",
    }
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.musical.genre == "Rap / hip-hop"
    assert despues.musical.mood == "Calido y comercial"


def test_un_genre_corto_nuevo_si_se_aplica(studio, universe, monkeypatch):
    """El control contrario: una etiqueta corta nueva es un cambio
    legitimo y la guardia no lo bloquea."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_de_k_ronte(studio, uid)

    datos = _eco_de(antes)
    datos["musical"] = {**datos["musical"], "genre": "Trap latino"}
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.musical.genre == "Trap latino"


# --- 3. El prompt: el nombre sale del artista, el universo es proyecto ----


def _llamada_biblia(studio):
    for llamada in reversed(studio.calls.all()):
        if llamada.method != "generateContent":
            continue
        partes = llamada.payload["contents"][0]["parts"]
        if any("Build a complete Artist Bible" in (p.get("text") or "") for p in partes):
            return "\n".join(p.get("text") or "" for p in partes)
    raise AssertionError("ninguna llamada de Biblia registrada")


def _renombrar_personaje(studio, uid, nombre):
    repo = Repository(studio.db, uid, CHARACTERS)
    personajes = repo.list(limit=50)
    protagonista = next(
        (c for c in personajes if c.get("role") == "lead"), personajes[0]
    )
    repo.update(protagonista["id"], {"name": nombre})


def test_el_bloque_decidido_nombra_al_artista_por_su_ficha(
    client, studio, universe
):
    """Sin nombre artistico guardado todavia, el bloque decidido toma el
    nombre de la ficha del personaje; el nombre del universo («Nova»)
    viaja rotulado como universo, nunca como nombre del artista."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    _renombrar_personaje(studio, uid, "K-Test")

    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    studio.jobs.wait_for_idle(20)

    prompt = _llamada_biblia(studio)
    assert "Stage name: K-Test" in prompt
    assert "Stage name: Nova" not in prompt
    assert "Universe: Nova" in prompt
    assert "NOT the artist's name" in prompt


def test_el_nombre_artistico_guardado_manda_sobre_ficha_y_universo(
    client, studio, universe
):
    """El caso de produccion: la identidad guardada dice «K-Ronte», la
    ficha y el universo dicen otra cosa. El bloque decidido presenta
    «K-Ronte» como el nombre del artista."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    _renombrar_personaje(studio, uid, "K-Test")
    biblia = load_bible(studio.db, uid)
    biblia.identity.stage_name = "K-Ronte"
    save_bible(studio.db, uid, biblia)

    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    studio.jobs.wait_for_idle(20)

    prompt = _llamada_biblia(studio)
    assert "Stage name: K-Ronte" in prompt
    assert "Stage name: K-Test" not in prompt
    assert "Universe: Nova" in prompt
