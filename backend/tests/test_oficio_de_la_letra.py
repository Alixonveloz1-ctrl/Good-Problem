"""La base de oficio de la letra y su revisión antes de guardar (2026-11-07).

El dueño leyó la letra de «Madera y Neón» y la dictaminó horrible: una
sola idea repetida en todas las partes, frases sin sentido puestas por
la rima («mi única balanza», «que el tráfico se ahogue en el cristal»)
y rimas mecánicas en cadena (-ando, -ión). Ordenó dos cosas:

1. Una BASE DE OFICIO permanente en el código — destilada de cómo
   componen los grandes (Arjona, Canserbero, Franco De Vita, Alejandro
   Sanz, Bad Bunny) — para la forma en que se piden las letras: la base
   manda en el CÓMO (historia que avanza, concreto antes que abstracto,
   imágenes que aguantan, la rima al servicio del sentido, coro =
   gancho, voz de persona, mostrar en vez de declarar, detalles con
   dueño) y nunca en el QUÉ: el tema, la historia, el mundo y la voz
   salen solo de la identidad del artista y del concepto de la canción.
   Viaja por el mismo canal que _JERGA_NATURAL — el reparto de
   canciones — y se suma a la descripción de cada artista sin tocarla.

2. REVISIÓN ANTES DE GUARDAR dentro del propio trabajo de letra: el
   borrador ya no se guarda tal como sale de una sola pasada; una
   segunda llamada de texto del mismo trabajo lo lee contra la base de
   oficio y la regla de la jerga y lo reescribe limpio, y lo que la
   canción guarda es la letra revisada. Si la revisión no devuelve una
   letra utilizable, el trabajo FALLA a la vista y la letra anterior
   queda intacta — fallo visible antes que éxito fingido.
"""

from __future__ import annotations

from app.db.repositories import SONGS, Repository
from app.domain.enums import CreativeRole, JobState
from app.orchestrator.roles import _OFICIO_DE_LA_LETRA, system_instruction
from app.providers.gemini_text import TextResult

_FRASES = (
    "The craft of writing the lyric",
    "A STORY THAT MOVES",
    "The premise is stated ONCE",
    "idea again in different words is forbidden",
    "CONCRETE BEFORE ABSTRACT",
    "IMAGES THAT HOLD UP",
    "RHYME SERVES MEANING",
    "no audible rhyme is unfinished",
    "SCENES, NOT SLOGANS",
    "A COMPLETE SONG'S ARCHITECTURE",
    "THE TEMPERATURE IS THE SONG'S",
    "sex sung out loud",
    "THE CHORUS IS THE HOOK",
    "SHOW, DO NOT DECLARE",
    "DETAILS WITH AN OWNER",
)

_GUARDARRAIL = "governs only how the lyric is written"


def _universo(client, studio, **extra):
    creado = client.post("/api/universes", json={"name": "Nova", **extra}).json()
    studio.jobs.wait_for_idle(20)
    return creado


def _llamada(studio, fragmento: str):
    """La ultima llamada de texto cuyo prompt contiene el fragmento."""
    for llamada in reversed(studio.calls.all()):
        if llamada.method != "generateContent":
            continue
        partes = llamada.payload["contents"][0]["parts"]
        if any(fragmento in (p.get("text") or "") for p in partes):
            return llamada
    raise AssertionError(f"ninguna llamada contiene {fragmento!r}")


def _instruccion(llamada) -> str:
    return llamada.payload["systemInstruction"]["parts"][0]["text"]


# --- Donde viaja y donde no ------------------------------------------------


def test_la_base_viaja_en_la_instruccion_de_las_tareas_de_cancion():
    instruccion = system_instruction(
        CreativeRole.MUSIC_DIRECTOR, reparto_canciones=True
    )
    for frase in _FRASES:
        assert frase in instruccion
    assert _GUARDARRAIL in instruccion
    # Se suma a lo que ya viajaba, no lo desplaza: el reparto y la jerga.
    assert "never vetoes an element of a song reference" in instruccion
    assert "falls NATURALLY in it" in instruccion


def test_la_base_no_viaja_fuera_de_las_tareas_de_cancion():
    del_video = system_instruction(
        CreativeRole.DIRECTOR,
        bible_summary="Stage name: Nova",
        canon="- character: Nova",
    )
    de_la_biblia = system_instruction(
        CreativeRole.CREATIVE_DIRECTOR, reescritura_biblia=True
    )
    for instruccion in (del_video, de_la_biblia):
        for frase in _FRASES:
            assert frase not in instruccion


def test_el_guardarrail_de_individualidad_esta_en_la_base():
    """La base manda en el cómo, nunca en el qué: no impone ni los temas
    ni el estilo de ninguno de los compositores que la inspiraron."""
    base = _OFICIO_DE_LA_LETRA
    assert _GUARDARRAIL in base
    assert "comes only from the artist's identity" in base
    for nombre in ("Arjona", "Canserbero", "Franco De Vita", "Sanz", "Bad Bunny"):
        assert nombre not in base


# --- De punta a punta: el concepto y la letra la llevan --------------------


def _cancion_con_concepto(client, studio, uid, **concepto):
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    respuesta = client.post(
        f"/api/universes/{uid}/songs/{sid}/concept", json=concepto
    )
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)
    return sid


def test_el_concepto_lleva_la_base(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    _cancion_con_concepto(client, studio, uid)

    instruccion = _instruccion(_llamada(studio, "Develop a song concept"))
    for frase in _FRASES:
        assert frase in instruccion
    assert _GUARDARRAIL in instruccion


def test_la_letra_y_su_revision_llevan_la_base(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    sid = _cancion_con_concepto(client, studio, uid, brief="Una despedida")

    letra = client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/generate", json={})
    assert letra.status_code == 200, letra.text
    studio.jobs.wait_for_idle(20)

    for fragmento in ("Write the full lyrics", "REVIEW THE DRAFT LYRIC"):
        instruccion = _instruccion(_llamada(studio, fragmento))
        for frase in _FRASES:
            assert frase in instruccion
        assert _GUARDARRAIL in instruccion


# --- La revisión: lo que se guarda es lo revisado ---------------------------

_BORRADOR_CON_DEFECTOS = (
    "[Verse 1]\n"
    "Miro la ciudad que me hace ruido caminando,\n"
    "todo sigue igual afuera y yo pensando,\n"
    "eres mi única balanza, mi señal brillando.\n"
    "\n"
    "[Chorus]\n"
    "La ciudad es ruido y tú eres mi paz."
)

_LETRA_CORREGIDA = (
    "[Verse 1]\n"
    "Dejé las llaves en la mesa de la cocina\n"
    "y tu taza siguió tibia junto a la ventana.\n"
    "\n"
    "[Chorus]\n"
    "La ciudad es ruido y tú eres mi paz."
)


def _gemini_a_medida(monkeypatch, revisada: str, llamadas: list[str]):
    """El proveedor de texto a medida: para la tarea de letra devuelve
    primero el borrador con los defectos de siempre y despues la
    revision que el guion diga. Cualquier otra llamada es un error:
    estas pruebas fijan el flujo de la letra y solo el de la letra."""

    def fake_generate(client, model, *, system_instruction, prompt, schema=None, **kwargs):
        llamadas.append(prompt)
        if "REVIEW THE DRAFT LYRIC" in prompt:
            return TextResult(
                text="revision",
                data={"title": "Madera y Neón", "lyrics": revisada},
                model=model,
                prompt_tokens=10,
                output_tokens=10,
            )
        if "Write the full lyrics" in prompt:
            return TextResult(
                text="borrador",
                data={"title": "Madera y Neón", "lyrics": _BORRADOR_CON_DEFECTOS},
                model=model,
                prompt_tokens=10,
                output_tokens=10,
            )
        raise AssertionError(f"llamada de texto inesperada: {prompt[:80]!r}")

    monkeypatch.setattr("app.providers.gemini_text.generate", fake_generate)


def _cancion(client, studio, uid, **extra):
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    Repository(studio.db, uid, SONGS).update(
        sid,
        {
            "concept": {"concept": "una historia de cocina y ventana", "mood": "calido"},
            **extra,
        },
    )
    return sid


def _trabajo_de_letra(studio, uid):
    for trabajo in studio.jobs.list(uid):
        payload = (trabajo.get("request") or {}).get("payload") or {}
        if payload.get("task") == "lyrics":
            return trabajo
    raise AssertionError("no hay trabajo de letra")


def test_el_trabajo_de_letra_guarda_la_letra_revisada(client, studio, monkeypatch):
    uid = _universo(client, studio, gender="mujer")["id"]
    sid = _cancion(client, studio, uid, lyrics="la letra de antes")
    llamadas: list[str] = []
    _gemini_a_medida(monkeypatch, _LETRA_CORREGIDA, llamadas)

    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/generate", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    assert _trabajo_de_letra(studio, uid)["state"] == JobState.READY.value
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert guardada["lyrics"] == _LETRA_CORREGIDA
    # Y la revision leyo el borrador entero, con su lista de caza.
    revision = next(p for p in llamadas if "REVIEW THE DRAFT LYRIC" in p)
    assert _BORRADOR_CON_DEFECTOS in revision
    assert "the same idea restated in more than one section" in revision


def test_revision_vacia_falla_a_la_vista_y_la_letra_queda_intacta(
    client, studio, monkeypatch
):
    uid = _universo(client, studio, gender="mujer")["id"]
    sid = _cancion(client, studio, uid, lyrics="la letra de antes")
    llamadas: list[str] = []
    _gemini_a_medida(monkeypatch, "   ", llamadas)

    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/generate", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    trabajo = _trabajo_de_letra(studio, uid)
    assert trabajo["state"] == JobState.FAILED.value
    assert "La revisión de la letra no devolvió una letra utilizable" in trabajo["error"]
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert guardada["lyrics"] == "la letra de antes"


# --- El análisis de la letra del usuario no cambia ---------------------------


def test_el_analisis_de_la_letra_del_usuario_no_se_revisa(client, studio):
    """La letra que escribe el usuario es suya: el analisis la lee y
    propone, sin reescribirla y sin segunda pasada de revision."""
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": "mi letra, escrita por mi", "author": "user"},
    )
    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/analyze", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    analisis = [
        llamada
        for llamada in studio.calls.all()
        if llamada.method == "generateContent"
        and any(
            "Analyse theme and structure" in (p.get("text") or "")
            for p in llamada.payload["contents"][0]["parts"]
        )
    ]
    assert len(analisis) == 1
    assert not any(
        "REVIEW THE DRAFT LYRIC" in (p.get("text") or "")
        for llamada in studio.calls.all()
        if llamada.method == "generateContent"
        for p in llamada.payload["contents"][0]["parts"]
    )
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert guardada["lyrics"] == "mi letra, escrita por mi"
