"""El eco de la Biblia (2026-11): «reescribir» no puede ser transcribir.

El caso real, verificado en vivo tres veces: se pulsaba «Que el Director
la escriba», el trabajo terminaba LISTO en un minuto y la Biblia quedaba
palabra por palabra igual. La guardia de exito vacio no saltaba porque
el Director SI devolvia secciones con contenido: devolvia LA BIBLIA QUE
YA HABIA. La causa estaba en el diseño de la tarea:

* La Biblia vigente viajaba entera en la instruccion de sistema como
  canon («trátala como verdad de fondo»), bajo la orden escrita de
  quedarse dentro de ella.
* El encargo, con el Brief vacio, no pedia cambiar nada, y el esquema
  obligaba a rellenar cada campo: la respuesta cumplidora era copiar.
* El bloque oficio-si/contenido-no prohibia importar los temas de las
  referencias sin dar otra fuente, asi que los temas viejos se quedaban.

Dos arreglos, cada uno con su prueba:

1. Fuera el eco de raíz: para ``artist_bible`` la Biblia vigente deja de
   viajar como canon en la instruccion de sistema. Viaja en el prompt,
   rotulada «CURRENT VERSION TO REWRITE» — un borrador —, junto a un
   bloque aparte con lo que el artista ya ES (sus datos decididos, que
   se conservan porque son suyos), y la tarea recibe su propio bloque de
   reescritura en vez de la regla de coherencia. Las demas tareas no
   cambian: personajes y video conservan la coherencia.
2. La red en la fusion: si las secciones de contenido fusionadas quedan
   identicas a las que habia, el trabajo es FAILED con su motivo — la
   misma filosofia que la guardia de exito vacio, un nivel mas arriba.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.enums import JobState
from app.services.context import load_bible, save_bible

_MENSAJE_ECO = "El Director devolvió la Biblia sin cambios: vuelve a intentarlo."
_SECCIONES = ("identity", "musical", "communication", "visual")


def _llamada(studio, fragmento: str):
    """La ultima llamada de texto cuyo prompt contiene el fragmento."""
    for llamada in reversed(studio.calls.all()):
        if llamada.method != "generateContent":
            continue
        partes = llamada.payload["contents"][0]["parts"]
        if any(fragmento in (p.get("text") or "") for p in partes):
            return llamada
    raise AssertionError(f"ninguna llamada contiene {fragmento!r}")


def _prompt(llamada) -> str:
    return "\n".join(
        p.get("text") or "" for p in llamada.payload["contents"][0]["parts"]
    )


def _instruccion(llamada) -> str:
    return llamada.payload["systemInstruction"]["parts"][0]["text"]


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


def _biblia_con_historia(studio, uid):
    """Una Biblia con contenido propio y reconocible, como la de un
    artista real: es el borrador que el eco transcribia."""
    biblia = load_bible(studio.db, uid)
    biblia.identity.personality = "Serio, de barrio, con la palabra pesada."
    biblia.identity.backstory = "Crecio en el barrio y salio a buscarse la vida."
    biblia.identity.recurring_themes = ["la traicion y las falsas amistades"]
    biblia.musical.mood = "Oscuro y tenso"
    biblia.musical.lyrical_themes = ["traicion, envidia e hipocresia"]
    biblia.communication.speech_style = "Directo y sentenciador"
    biblia.visual.aesthetic = "Urbano nocturno"
    save_bible(studio.db, uid, biblia)
    return load_bible(studio.db, uid)


def _eco_de(biblia) -> dict:
    """Lo que devolvia el Director en vivo: las secciones tal cual."""
    volcado = biblia.model_dump()
    return {seccion: volcado[seccion] for seccion in _SECCIONES}


# --- 1. La llamada ya no entrega la Biblia como canon ----------------------


def test_la_reescritura_recibe_el_borrador_en_el_prompt_y_no_el_canon(
    client, studio
):
    """Sobre la llamada real que construye director.run: la instruccion
    de sistema no trae ni la orden de coherencia, ni el canon como verdad
    de fondo, ni el texto de la Biblia vigente; el encuadre de
    reescritura esta en la instruccion, y el borrador viaja en el prompt
    con su rotulo, junto a los datos decididos del artista."""
    uid = client.post("/api/universes", json={"name": "Nova"}).json()["id"]
    studio.jobs.wait_for_idle(20)
    biblia = _biblia_con_historia(studio, uid)
    assert "la traicion y las falsas amistades" in biblia.identity.recurring_themes

    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": ""})
    studio.jobs.wait_for_idle(20)

    llamada = _llamada(studio, "Build a complete Artist Bible")
    instruccion, prompt = _instruccion(llamada), _prompt(llamada)

    # La instruccion: ni coherencia, ni canon, ni el texto del borrador.
    assert "Stay inside the Artist Bible" not in instruccion
    assert "treat as ground truth" not in instruccion
    assert "la traicion y las falsas amistades" not in instruccion
    # En su lugar, el bloque de reescritura.
    assert "REWRITES the Artist Bible" in instruccion
    assert "starting draft" in instruccion
    assert "is not a result" in instruccion

    # El prompt: el borrador con su rotulo, y el artista aparte.
    assert "CURRENT VERSION TO REWRITE" in prompt
    assert "Do not transcribe it back" in prompt
    assert "la traicion y las falsas amistades" in prompt
    assert "THE ARTIST, AS DECIDED" in prompt
    assert "Stage name: Nova" in prompt


# --- 2. La red: devolver lo mismo es un fallo visible ----------------------


def test_devolver_la_biblia_tal_cual_es_un_fallo_visible(
    studio, universe, monkeypatch
):
    """La forma exacta del caso real, de punta a punta por run_job: el
    Director devuelve las secciones llenas… con el texto que ya habia.
    Antes: LISTO sin tocar ni una palabra. Ahora: FAILED con el motivo,
    y la Biblia queda exactamente como estaba, version incluida."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_con_historia(studio, uid)

    _director_devuelve(monkeypatch, _eco_de(antes))
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.FAILED.value
    assert resultado["error"] == _MENSAJE_ECO
    despues = load_bible(studio.db, uid)
    assert despues.model_dump() == antes.model_dump()


def test_una_reescritura_de_verdad_se_guarda(studio, universe, monkeypatch):
    """El control contrario: con cambios reales, el trabajo termina
    LISTO, lo guardado refleja lo nuevo y la version sube."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_con_historia(studio, uid)

    datos = _eco_de(antes)
    datos["identity"] = {
        **datos["identity"],
        "personality": "Sonador y melancolico, con el barrio en la voz.",
        "recurring_themes": ["salir del barrio sin olvidarlo", "la madre y la casa"],
    }
    datos["musical"] = {
        **datos["musical"],
        "lyrical_themes": ["superacion y memoria"],
        "mood": "Melancolico y calido",
    }
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.identity.personality.startswith("Sonador y melancolico")
    assert despues.identity.recurring_themes == [
        "salir del barrio sin olvidarlo",
        "la madre y la casa",
    ]
    assert despues.musical.mood == "Melancolico y calido"
    assert despues.version == antes.version + 1


def test_un_cambio_parcial_legitimo_pasa_la_red(studio, universe, monkeypatch):
    """La red compara el conjunto de secciones, no campo a campo: una
    reescritura que solo cambia una seccion y conserva lo demas —el
    origen, la voz, lo que el artista ya es— es un resultado valido y
    se guarda."""
    uid = universe
    studio.jobs.wait_for_idle(20)
    antes = _biblia_con_historia(studio, uid)

    datos = _eco_de(antes)
    datos["communication"] = {
        **datos["communication"],
        "speech_style": "Cercano, con humor seco",
    }
    _director_devuelve(monkeypatch, datos)
    trabajo = _trabajo_biblia(studio, uid)
    resultado = studio.orchestrator.run_job(uid, trabajo["id"])

    assert resultado["state"] == JobState.READY.value
    despues = load_bible(studio.db, uid)
    assert despues.communication.speech_style == "Cercano, con humor seco"
    assert despues.identity.backstory == antes.identity.backstory
    assert despues.version == antes.version + 1
