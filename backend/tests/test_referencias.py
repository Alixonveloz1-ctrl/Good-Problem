"""El reparto de las referencias (2026-11): el enlace pone la forma, el
artista pone su identidad.

El caso real que lo provoco: el usuario enlazo «Ojitos Lindos» (un duo
romantico) como referencia de su cancion y el concepto salio una tiradera
de traicion. Habia tres causas en el codigo, y estas pruebas las fijan:

1. Todos los roles del Director llevaban una orden escrita de quedarse
   dentro de la Biblia y DECIR lo que la contradijera — y esas notas
   caian dentro de los campos del concepto. Para las tareas de cancion
   esa orden ya no existe: la Biblia da la identidad y nunca veta ni
   impone el tema.
2. La referencia de la cancion entraba ultima y sin rango, enterrada
   tras los resumenes del artista (que entraban dos veces). Ahora viaja
   primera, en su propio bloque y mandando en la forma; los resumenes
   del artista no entran en la llamada de concepto.
3. Gemini "vio" la pagina de navegador obsoleto de music.youtube.com e
   invento un analisis glitch pop que se guardo como valido. Ahora la
   URL se normaliza a youtube.com/watch?v= y una guardia rechaza los
   resumenes vacios o fabricados de una pagina de error.

Y la pieza de la raiz: la Biblia misma se escribio importando el
CONTENIDO de las referencias (Jeremias 17:5 canta sobre la traicion, y
eso se convirtio en "los temas del artista"). La generacion de la Biblia
ahora lleva el encuadre oficio-si / contenido-no.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import inspiration as inspiration_service
from app.services.context import load_bible, save_bible


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


def _prompt(llamada) -> str:
    return "\n".join(
        p.get("text") or "" for p in llamada.payload["contents"][0]["parts"]
    )


def _instruccion(llamada) -> str:
    return llamada.payload["systemInstruction"]["parts"][0]["text"]


def _cancion_con_concepto(client, studio, uid):
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={"brief": "Una idea"})
    studio.jobs.wait_for_idle(20)
    return sid


_VOZ = {
    "sex": "Mujer",
    "apparent_age": "Unos 25 anos",
    "pitch": "Media, mas bien grave",
    "timbre": "Calida, con un poco de aire",
    "language_accent": "Espanol neutro",
    "singing_style": "Intima en los versos, con fuerza en el coro",
}


def _con_voz_y_generos(client, uid):
    """La voz y los generos de la ficha, para que los bloques del encargo
    al Director existan y se pueda afirmar sobre ellos."""
    client.put(f"/api/universes/{uid}/bible/singing-voice", json=_VOZ)
    client.put(
        f"/api/universes/{uid}/bible/genres",
        json={"music_genres": ["rap"], "music_genre_free": ""},
    )


# --- 1. Fuera la censura en las tareas de cancion -------------------------


def test_el_concepto_ya_no_lleva_la_orden_de_censura(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    _cancion_con_concepto(client, studio, uid)

    instruccion = _instruccion(_llamada(studio, "Develop a song concept"))
    assert "Stay inside the Artist Bible" not in instruccion
    assert "without exception" not in instruccion
    # En su lugar, el reparto: la Biblia da al artista y nunca veta.
    assert "never vetoes an element of a song reference" in instruccion
    assert "Never write notes about your own process" in instruccion


def test_la_biblia_y_el_video_conservan_su_regla_de_coherencia(client, studio):
    """El alcance es el de la censura tematica en canciones: las tareas que
    definen al artista (su Biblia) conservan la regla de coherencia."""
    uid = _universo(client, studio, gender="mujer")["id"]
    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": "Rap nocturno"})
    studio.jobs.wait_for_idle(20)

    instruccion = _instruccion(_llamada(studio, "Build a complete Artist Bible"))
    assert "Stay inside the Artist Bible" in instruccion
    assert "without exception" in instruccion


# --- 2. La referencia de la cancion: primera, con rango, sin duplicar -----


def test_la_referencia_de_la_cancion_va_primera_y_con_rango(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    _con_voz_y_generos(client, uid)
    # Una inspiracion del artista, con su resumen reconocible.
    client.post(
        f"/api/universes/{uid}/bible/inspirations",
        json={"url": "https://www.youtube.com/watch?v=abc123XYZ"},
    )
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    biblia["inspirations"][0]["summary_text"] = "RESUMEN DEL ARTISTA: boom bap crudo"
    client.put(
        f"/api/universes/{uid}/bible/inspirations",
        json={"inspirations": biblia["inspirations"]},
    )

    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.patch(
        f"/api/universes/{uid}/songs/{sid}",
        json={"inspiration_summary": "RESUMEN DE ESTA CANCION: duo romantico suave"},
    )
    client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={"brief": "Una idea"})
    studio.jobs.wait_for_idle(20)

    llamada = _llamada(studio, "Develop a song concept")
    prompt, instruccion = _prompt(llamada), _instruccion(llamada)
    # La referencia de la cancion esta, con su rango escrito.
    assert "THIS SONG'S REFERENCE" in prompt
    assert "RESUMEN DE ESTA CANCION: duo romantico suave" in prompt
    # Y va antes que la voz y que los generos dentro del encargo.
    assert prompt.index("RESUMEN DE ESTA CANCION") < prompt.index("SINGING VOICE")
    assert prompt.index("RESUMEN DE ESTA CANCION") < prompt.index("GENRE COMBINATION")
    # Los resumenes del artista no entran en esta llamada: ni en el prompt
    # ni duplicados en la instruccion de sistema.
    assert "RESUMEN DEL ARTISTA" not in prompt
    assert "RESUMEN DEL ARTISTA" not in instruccion


def test_los_temas_se_presentan_como_fondo_en_el_concepto(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    biblia = load_bible(studio.db, uid)
    biblia.identity.recurring_themes = ["traicion y amigos falsos"]
    biblia.musical.lyrical_themes = ["la traicion"]
    save_bible(studio.db, uid, biblia)

    _cancion_con_concepto(client, studio, uid)
    instruccion = _instruccion(_llamada(studio, "Develop a song concept"))
    assert "Recurring themes (background identity of the artist" in instruccion
    assert "NOT the topic of this song" in instruccion
    assert "Lyric themes (background identity" in instruccion
    # Los temas siguen ahi como fondo: lo que cambia es el rotulo.
    assert "traicion y amigos falsos" in instruccion


def test_generos_sin_fixed_en_el_concepto_y_la_voz_sigue_fija(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    _con_voz_y_generos(client, uid)
    _cancion_con_concepto(client, studio, uid)

    llamada = _llamada(studio, "Develop a song concept")
    prompt, instruccion = _prompt(llamada), _instruccion(llamada)
    assert "GENRE COMBINATION (fixed)" not in prompt
    assert "Genres (fixed combination)" not in instruccion
    assert "the artist's usual ground" in prompt
    # La voz, en cambio, sigue etiquetada como fija: es la garantia que
    # llega palabra por palabra hasta Lyria.
    assert "SINGING VOICE OF THIS ARTIST (fixed, include verbatim" in prompt


# --- 3. La Biblia importa el oficio, no el contenido -----------------------


def test_la_biblia_solo_importa_el_oficio_de_las_referencias(client, studio):
    uid = _universo(
        client,
        studio,
        gender="mujer",
        inspiration_urls=["https://www.youtube.com/watch?v=abc123XYZ"],
    )["id"]
    client.post(f"/api/universes/{uid}/bible/generate", json={"brief": "Rap nocturno"})
    studio.jobs.wait_for_idle(20)

    llamada = _llamada(studio, "Build a complete Artist Bible")
    prompt, instruccion = _prompt(llamada), _instruccion(llamada)
    assert "REFERENCE CRAFT (craft only" in instruccion
    assert "technique, flow, metrics" in instruccion
    assert "THE REFERENCES TEACH CRAFT, NOT CONTENT" in prompt
    assert "come from the artist's own concept and brief" in prompt


# --- 4. Normalizacion y guardia anti-fabricacion ---------------------------

_URL_MUSICA = "https://music.youtube.com/watch?v=7GDp7S1HgSk&si=lkYH8FcB7k8Fa722"


def test_normaliza_cualquier_forma_de_enlace_de_youtube():
    esperado = "https://www.youtube.com/watch?v=7GDp7S1HgSk"
    assert inspiration_service.normalize_youtube_url(_URL_MUSICA) == esperado
    assert (
        inspiration_service.normalize_youtube_url("https://youtu.be/7GDp7S1HgSk?t=9")
        == esperado
    )
    assert (
        inspiration_service.normalize_youtube_url(
            "https://www.youtube.com/shorts/7GDp7S1HgSk"
        )
        == esperado
    )
    assert inspiration_service.normalize_youtube_url(esperado) == esperado


def _analisis_falso(monkeypatch, datos):
    def fake_generate(client, model, **kwargs):
        return SimpleNamespace(data=datos)

    monkeypatch.setattr(inspiration_service.gemini_text, "generate", fake_generate)


def test_el_analisis_manda_la_url_normalizada(monkeypatch, studio):
    capturado = {}
    datos = {
        "title": "Ojitos Lindos",
        "genres": "Pop romantico con reggae",
        "rhythm": "Suave, bailable lento",
        "instruments": ["guitarra", "sintetizadores"],
        "structure": "verso, coro, verso, coro",
        "mood": "Romantico y sonador",
        "lyric_themes": ["enamorarse de una mirada"],
        "lyric_style": "Directa y tierna",
    }

    def fake_generate(client, model, **kwargs):
        capturado.update(kwargs)
        return SimpleNamespace(data=datos)

    monkeypatch.setattr(inspiration_service.gemini_text, "generate", fake_generate)
    inspiracion = inspiration_service.analyse_youtube(studio, _URL_MUSICA)
    parte = capturado["extra_parts"][0]
    assert parte["fileData"]["fileUri"] == "https://www.youtube.com/watch?v=7GDp7S1HgSk"
    assert inspiracion.url == "https://www.youtube.com/watch?v=7GDp7S1HgSk"
    assert inspiracion.summary_text


def test_analisis_fabricado_es_error_visible_y_marca(client, studio, monkeypatch):
    """La forma exacta del caso real: el modelo "vio" la pagina de
    navegador obsoleto e invento un analisis glitch pop. Eso es un fallo,
    no un resumen: el endpoint responde error, la cancion queda marcada y
    sin resumen, y la propuesta de concepto avisa en vez de fingir."""
    _analisis_falso(
        monkeypatch,
        {
            "title": "Your browser is deprecated",
            "genres": "Glitch pop, synthwave, industrial electronico",
            "rhythm": "120 BPM, ritmo mecanico",
            "instruments": ["sintetizadores industriales"],
            "structure": "verso, coro",
            "mood": "Futurista, distopico, oscuro, robotico",
            "lyric_themes": ["denuncia contra el sistema"],
            "lyric_style": "Denuncia en segunda persona",
        },
    )
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{sid}/inspiration", json={"url": _URL_MUSICA}
    )
    assert respuesta.status_code == 502, respuesta.text
    assert "no es utilizable" in respuesta.json()["error"]["message"]

    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert guardada["inspiration_failed"] is True
    assert "browser is deprecated" in guardada["inspiration_error"]
    assert not (guardada["inspiration_summary"] or "").strip()

    propuesta = client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={})
    assert propuesta.status_code == 409, propuesta.text
    assert "no se pudo analizar" in propuesta.json()["error"]["message"]


def test_analisis_vacio_es_error_y_no_guarda_fantasma(client, studio, monkeypatch):
    _analisis_falso(monkeypatch, {})
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]

    respuesta = client.post(
        f"/api/universes/{uid}/songs/{sid}/inspiration",
        json={"url": "https://www.youtube.com/watch?v=abc123XYZ"},
    )
    assert respuesta.status_code == 502, respuesta.text
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert guardada["inspiration_failed"] is True
    assert not (guardada["inspiration_summary"] or "").strip()


def test_la_propuesta_avisa_con_enlace_sin_resumen_o_fabricado(client, studio):
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]

    # Enlace guardado sin resumen utilizable (el fallo silencioso de antes).
    studio.db.update(
        f"universes/{uid}/songs/{sid}",
        {
            "inspiration_url": "https://www.youtube.com/watch?v=abc123XYZ",
            "inspiration_summary": "",
        },
    )
    propuesta = client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={})
    assert propuesta.status_code == 409, propuesta.text

    # Y con el resumen fabricado que ya existe en produccion: tampoco pasa.
    studio.db.update(
        f"universes/{uid}/songs/{sid}",
        {
            "inspiration_summary": (
                "Reference: Your browser is deprecated\n"
                "Genres and mix: Glitch pop, synthwave, industrial electronico"
            )
        },
    )
    propuesta = client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={})
    assert propuesta.status_code == 409, propuesta.text
    assert "browser is deprecated" in propuesta.json()["error"]["message"]


def test_un_resumen_escrito_a_mano_levanta_la_marca(client, studio, monkeypatch):
    _analisis_falso(monkeypatch, {})
    uid = _universo(client, studio, gender="mujer")["id"]
    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    sid = cancion["id"]
    client.post(
        f"/api/universes/{uid}/songs/{sid}/inspiration",
        json={"url": "https://www.youtube.com/watch?v=abc123XYZ"},
    )
    assert client.get(f"/api/universes/{uid}/songs/{sid}").json()["inspiration_failed"]

    client.patch(
        f"/api/universes/{uid}/songs/{sid}",
        json={"inspiration_summary": "Resumen mio: duo romantico, ritmo suave"},
    )
    guardada = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert guardada["inspiration_failed"] is False
    propuesta = client.post(f"/api/universes/{uid}/songs/{sid}/concept", json={})
    assert propuesta.status_code == 200, propuesta.text
