"""Que el análisis llene solo la ficha de la canción (2026-11-07).

El dueño lo dijo sin rodeos: ¿para qué analizar una canción si luego hay
que marcar los géneros a mano y escribir la Idea igual? El análisis solo
guardaba un resumen de texto, y «Guardar los generos de esta cancion»
guardaba sin avisar, así que parecía que no pasaba nada. Estas pruebas
fijan el comportamiento nuevo:

1. Un análisis bueno deja la canción GUARDADA con los géneros de la
   canción analizada — los casados con el catálogo de la app — y con su
   mezcla como texto libre («Suena a…»). Los géneros del artista no se
   tocan.
2. Si el análisis no casa ningún género del catálogo, los marcados no se
   tocan (nunca se vacían) y solo se mueve la mezcla.
3. Si el análisis falla, no se tocan ni géneros ni mezcla: el fallo
   visible de siempre, y nada más.
4. El casado respeta el tope de géneros principales y descarta claves
   inventadas y repetidas.
5. El concepto ya no exige Idea escrita: con el brief vacío, el encargo
   al Director ordena inventar el concepto completo — desde la forma de
   la referencia si la hay, desde el artista solo si no — y si el
   usuario SÍ escribe su Idea, manda la suya, como siempre.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import inspiration as inspiration_service

_URL = "https://www.youtube.com/watch?v=7GDp7S1HgSk"


def _universo(client, studio, **extra):
    creado = client.post("/api/universes", json={"name": "Nova", **extra}).json()
    studio.jobs.wait_for_idle(20)
    return creado


def _analisis(monkeypatch, datos):
    def fake_generate(client, model, **kwargs):
        return SimpleNamespace(data=datos)

    monkeypatch.setattr(inspiration_service.gemini_text, "generate", fake_generate)


def _datos_buenos(**cambios):
    datos = {
        "title": "Ojitos Lindos",
        "genres": "Pop latino alternativo y regueton chill",
        "genre_keys": ["pop", "regueton"],
        "rhythm": "Suave, bailable lento",
        "instruments": ["guitarra", "sintetizadores"],
        "structure": "verso, coro, verso, coro",
        "mood": "Romantico y sonador",
        "lyric_themes": ["enamorarse de una mirada"],
        "lyric_style": "Directa y tierna",
    }
    datos.update(cambios)
    return datos


def _cancion_del_artista_rap(client, uid):
    """El artista es de rap; su canción nace con eso, hasta que el
    análisis de su referencia diga otra cosa."""
    client.put(
        f"/api/universes/{uid}/bible/genres",
        json={"music_genres": ["rap"], "music_genre_free": ""},
    )
    return client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()


def _guardada(client, uid, sid):
    return client.get(f"/api/universes/{uid}/songs/{sid}").json()


# --- 1. El análisis llena los géneros y la mezcla -------------------------


def test_analisis_correcto_guarda_generos_y_mezcla(client, studio, monkeypatch):
    _analisis(monkeypatch, _datos_buenos())
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = _cancion_del_artista_rap(client, uid)
    assert cancion["genres"] == ["rap"]

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/inspiration", json={"url": _URL}
    )
    assert respuesta.status_code == 200, respuesta.text

    guardada = _guardada(client, uid, cancion["id"])
    # Los géneros de la canción analizada, casados con el catálogo.
    assert guardada["genres"] == ["pop", "regueton"]
    # Su mezcla, tal como la oyó el análisis, en el texto libre.
    assert guardada["genre_free"] == "Pop latino alternativo y regueton chill"
    # Y la línea «Suena a…» compuesta con lo nuevo, no con lo de antes.
    assert guardada["genre"] == (
        "Pop + Reguetón + Pop latino alternativo y regueton chill"
    )
    assert guardada["inspiration_failed"] is False
    assert "Ojitos Lindos" in guardada["inspiration_summary"]

    # Los géneros del artista quedan como estaban: esto es solo de la
    # canción.
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["music_genres"] == ["rap"]


def test_sin_casa_de_catalogo_se_mueve_la_mezcla_y_no_los_generos(
    client, studio, monkeypatch
):
    _analisis(
        monkeypatch,
        _datos_buenos(
            genres="Glitch pop experimental, sintetizadores rotos",
            genre_keys=["glitch_inventado", "dream_pop_espacial"],
        ),
    )
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = _cancion_del_artista_rap(client, uid)

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/inspiration", json={"url": _URL}
    )
    assert respuesta.status_code == 200, respuesta.text

    guardada = _guardada(client, uid, cancion["id"])
    # Ninguna clave era del catálogo: los marcados no se tocan…
    assert guardada["genres"] == ["rap"]
    # …pero la mezcla sí pasa a ser la oída.
    assert guardada["genre_free"] == "Glitch pop experimental, sintetizadores rotos"
    assert guardada["genre"] == (
        "Rap / hip-hop + Glitch pop experimental, sintetizadores rotos"
    )


def test_el_casado_respeta_el_tope_y_descarta_inventadas_y_repetidas(
    client, studio, monkeypatch
):
    _analisis(
        monkeypatch,
        _datos_buenos(
            genre_keys=["pop", "rock", "pop", "trap", "jazz", "inventado", "blues"]
        ),
    )
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = _cancion_del_artista_rap(client, uid)

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/inspiration", json={"url": _URL}
    )
    assert respuesta.status_code == 200, respuesta.text

    guardada = _guardada(client, uid, cancion["id"])
    # Tres principales como máximo, sin repetir y sin inventadas.
    assert guardada["genres"] == ["pop", "rock", "trap"]


def test_analisis_fallido_no_toca_ni_generos_ni_mezcla(client, studio, monkeypatch):
    _analisis(
        monkeypatch,
        _datos_buenos(
            title="Your browser is deprecated",
            genres="Glitch pop, synthwave, industrial electronico",
            genre_keys=["pop"],
        ),
    )
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(
        f"/api/universes/{uid}/songs",
        json={"title": "Neon", "genres": ["rap", "trap"], "genre_free": "mi mezcla"},
    ).json()
    assert cancion["genres"] == ["rap", "trap"]

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/inspiration", json={"url": _URL}
    )
    assert respuesta.status_code == 502, respuesta.text

    guardada = _guardada(client, uid, cancion["id"])
    assert guardada["inspiration_failed"] is True
    # El fallo es el de siempre y no arrastra nada consigo.
    assert guardada["genres"] == ["rap", "trap"]
    assert guardada["genre_free"] == "mi mezcla"
    assert guardada["genre"] == cancion["genre"]


# --- 2. El concepto no exige Idea escrita -----------------------------------


def _prompt_del_concepto(studio) -> str:
    for llamada in reversed(studio.calls.all()):
        if llamada.method != "generateContent":
            continue
        partes = llamada.payload["contents"][0]["parts"]
        texto = "\n".join(p.get("text") or "" for p in partes)
        if "Develop a song concept" in texto:
            return texto
    raise AssertionError("ninguna llamada es la del concepto")


def test_concepto_sin_idea_con_referencia_ordena_inventarla(client, studio):
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

    prompt = _prompt_del_concepto(studio)
    assert "THIS SONG'S REFERENCE" in prompt
    # La orden de inventar, en su rama de referencia: la forma sale de
    # ella y la historia es nueva, no la suya contada otra vez.
    assert "NO USER IDEA — INVENT THE SONG YOURSELF" in prompt
    assert "analysed the reference above" in prompt
    assert "never the reference's own plot" in prompt
    assert "USER IDEA\n" not in prompt


def test_concepto_sin_idea_sin_referencia_inventa_desde_el_artista(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/concept", json={}
    )
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    prompt = _prompt_del_concepto(studio)
    assert "NO USER IDEA — INVENT THE SONG YOURSELF" in prompt
    assert "from this artist alone" in prompt
    assert "USER IDEA\n" not in prompt


def test_concepto_con_idea_sigue_mandando_la_del_usuario(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/concept",
        json={"brief": "Una despedida en la estacion"},
    )
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    prompt = _prompt_del_concepto(studio)
    assert "USER IDEA\nUna despedida en la estacion" in prompt
    assert "NO USER IDEA" not in prompt
