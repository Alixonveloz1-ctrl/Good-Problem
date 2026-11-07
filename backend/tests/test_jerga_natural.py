"""La jerga, solo cuando caiga natural y bien dicha (2026-11-07).

El dueño lo dijo con sus ejemplos: las letras sonaban a IA porque el
Director metía jerga venezolana A LA FUERZA y MAL USADA — palabras con
el significado o el contexto equivocados, como adorno para «sonar» del
lugar. Bien usada no habría problema; mal usada se escucha horrible.

El arreglo es una regla permanente de oficio en la instrucción de las
tareas de canción (roles._JERGA_NATURAL, que viaja con el reparto de
canciones): la jerga entra solo si cae natural en la frase, con su
significado real y como la diría un nativo; nunca esparcida como
adorno; ante la duda de uso, español limpio; y cuánto sabor local lleva
una letra lo marca la identidad del artista, no una cuota por verso.

Y lo que estas pruebas fijan con la misma fuerza: NO es una
prohibición. No hay lista de palabras prohibidas, ni filtro sobre la
salida, ni la regla nombra identidad alguna: la jerga bien usada del
mundo del artista es bienvenida.
"""

from __future__ import annotations

from app.domain.enums import CreativeRole
from app.orchestrator.roles import _JERGA_NATURAL, system_instruction

_FRASES = (
    "How slang works in anything sung",
    "falls NATURALLY in it",
    "Never scatter slang words as decoration",
    "not certain of a slang word's exact meaning",
    "never by a quota of slang",
)


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


def test_la_regla_viaja_en_la_instruccion_de_las_tareas_de_cancion():
    instruccion = system_instruction(
        CreativeRole.MUSIC_DIRECTOR, reparto_canciones=True
    )
    for frase in _FRASES:
        assert frase in instruccion
    # Y el reparto de siempre sigue ahi: la regla se suma, no lo desplaza.
    assert "never vetoes an element of a song reference" in instruccion


def test_la_regla_no_viaja_fuera_de_las_tareas_de_cancion():
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


# --- De punta a punta: la letra y el concepto la llevan --------------------


def _cancion_con_concepto(client, studio, uid, **concepto):
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    respuesta = client.post(
        f"/api/universes/{uid}/songs/{sid}/concept", json=concepto
    )
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)
    return sid


def test_el_concepto_la_lleva_sin_referencia_ni_idea(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    _cancion_con_concepto(client, studio, uid)

    instruccion = _instruccion(_llamada(studio, "Develop a song concept"))
    for frase in _FRASES:
        assert frase in instruccion


def test_el_concepto_la_lleva_con_referencia(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.patch(
        f"/api/universes/{uid}/songs/{sid}",
        json={"inspiration_summary": "RESUMEN DE ESTA CANCION: duo romantico suave"},
    )
    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    instruccion = _instruccion(_llamada(studio, "Develop a song concept"))
    for frase in _FRASES:
        assert frase in instruccion


def test_la_letra_la_lleva_de_punta_a_punta(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    sid = _cancion_con_concepto(client, studio, uid, brief="Una despedida")

    letra = client.post(f"/api/universes/{uid}/songs/{sid}/lyrics/generate", json={})
    assert letra.status_code == 200, letra.text
    studio.jobs.wait_for_idle(20)

    instruccion = _instruccion(_llamada(studio, "Write the full lyrics"))
    for frase in _FRASES:
        assert frase in instruccion


# --- Lo que la regla NO es ---------------------------------------------------


def test_la_regla_no_prohibe_ni_palabras_ni_identidad():
    regla = _JERGA_NATURAL
    minusculas = regla.lower()
    # Lo dice ella misma: no es una prohibición y lo bien usado entra.
    assert "This is not a ban" in regla
    assert "is welcome" in regla
    # Sin lenguaje de prohibición y sin nombrar identidad alguna: la
    # regla es de oficio (cómo se usa una palabra), no de origen.
    assert "forbidden" not in minusculas
    assert "prohibit" not in minusculas
    assert "banned" not in minusculas
    assert "venezuel" not in minusculas
