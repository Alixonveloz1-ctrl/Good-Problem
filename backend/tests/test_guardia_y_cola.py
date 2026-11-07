"""El arreglo completo de las referencias (2026-11): ver el video de
verdad, revalidar lo guardado y una cola que no muere en silencio.

Tres huecos que el paquete anterior dejo, cada uno con su caso real:

1. El analisis «funcionaba» sin ver el video: el enlace viajaba
   declarado como «video/mp4» y detras del texto, y Vertex devolvia la
   pagina HTML «browser is deprecated» en vez de la cancion. La forma
   que si funciona (la de Drama) declara «video/*», pone el video
   primero y corta con metadatos objeto {seconds: n}.
2. La guardia anti-fabricacion solo miraba el analisis al entrar. El
   resumen FINALMENTE guardado es un campo libre: la lista de la
   Biblia se persiste verbatim al guardar, y ninguna lectura lo
   revalidaba — en produccion quedo guardado, bajo el titulo correcto
   «Canserbero - Es Épico», un resumen que empieza «Reference: Your
   browser is deprecated», y entro en todos los prompts. Ahora la
   comprobacion corre sobre el texto guardado, al leer, al marcar y
   en cada puerta de prompt.
3. La cola entregaba una sola vez: una entrega perdida (un
   despliegue, un 503) dejaba el trabajo «En cola» para siempre, sin
   error. El vigilante lo re-encola una vez y, si tampoco llega, lo
   marca FAILED con el motivo a la vista.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from app.clock import now
from app.domain.enums import JobState
from app.errors import ProviderError
from app.orchestrator import schemas_json as S
from app.services import inspiration as inspiration_service
from app.services.context import load_bible, summarize_bible
from app.services.jobs import MENSAJE_COLA_NO_ENTREGO


def _universo(client, studio, **extra):
    creado = client.post("/api/universes", json={"name": "Nova", **extra}).json()
    studio.jobs.wait_for_idle(20)
    return creado


def _hace(minutos: int) -> str:
    return (now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")


# --- 1. El analisis ve el video: la forma de la llamada --------------------


def test_el_titulo_es_requerido_en_el_esquema_del_analisis():
    # Sin titulo no hay analisis: un resultado que no nombra el video
    # que vio es un error de esquema, no un resumen «valido».
    assert "title" in S.INSPIRATION_SCHEMA["required"]


def test_el_video_va_primero_y_declarado_como_video(client, studio):
    """La llamada registrada tiene que llevar la forma de Drama: la
    parte del video PRIMERA, declarada «video/*», y la instruccion
    despues — no el enlace al final declarado como un mp4 remoto."""
    uid = _universo(client, studio, gender="mujer")["id"]
    client.post(
        f"/api/universes/{uid}/bible/inspirations",
        json={"url": "https://www.youtube.com/watch?v=abc123XYZ"},
    )

    for llamada in studio.calls.all():
        partes = llamada.payload["contents"][0]["parts"]
        if any("fileData" in parte for parte in partes):
            assert "fileData" in partes[0], "el video tiene que ir primero"
            assert partes[0]["fileData"]["mimeType"] == "video/*"
            assert partes[0]["fileData"]["fileUri"] == (
                "https://www.youtube.com/watch?v=abc123XYZ"
            )
            assert "text" in partes[1], "la instruccion va despues del video"
            assert "videoMetadata" not in partes[0]
            return
    raise AssertionError("ninguna llamada llevo la parte del video")


def test_los_trozos_llevan_los_cortes_como_objetos(monkeypatch, studio):
    """Un video largo se mira por trozos de 20 minutos, y cada corte
    viaja como objeto {seconds: n} — no como la cadena «1200s» que
    Vertex no interpreta como corte de video."""
    llamadas = []

    def fake_generate(client, model, **kwargs):
        llamadas.append(kwargs)
        if kwargs.get("extra_parts"):
            if len(llamadas) == 1:
                # La mirada entera falla (video largo): a trozos.
                raise ProviderError("demasiado grande")
            return SimpleNamespace(
                data={
                    "title": "Una cancion larga",
                    "genres": "Rap",
                    "rhythm": "Lento",
                    "instruments": ["piano"],
                    "structure": "verso, coro",
                    "mood": "Denso",
                    "lyric_themes": ["el barrio"],
                    "lyric_style": "Narrativo",
                }
            )
        # La llamada de fusion de los trozos.
        return SimpleNamespace(
            data={
                "title": "Una cancion larga",
                "genres": "Rap",
                "rhythm": "Lento",
                "instruments": ["piano"],
                "structure": "verso, coro",
                "mood": "Denso",
                "lyric_themes": ["el barrio"],
                "lyric_style": "Narrativo",
            }
        )

    monkeypatch.setattr(inspiration_service.gemini_text, "generate", fake_generate)
    inspiracion = inspiration_service.analyse_youtube(
        studio, "https://www.youtube.com/watch?v=larga12345"
    )
    assert inspiracion.title == "Una cancion larga"

    con_video = [k for k in llamadas if k.get("extra_parts")]
    # La mirada entera + tres trozos, todos con el video primero.
    assert len(con_video) == 4
    for kwargs in con_video:
        assert kwargs["extra_parts_first"] is True
    assert "videoMetadata" not in con_video[0]["extra_parts"][0]
    cortes = [k["extra_parts"][0]["videoMetadata"] for k in con_video[1:]]
    assert cortes == [
        {"startOffset": {"seconds": 0}, "endOffset": {"seconds": 1200}},
        {"startOffset": {"seconds": 1200}, "endOffset": {"seconds": 2400}},
        {"startOffset": {"seconds": 2400}, "endOffset": {"seconds": 3600}},
    ]
    for kwargs in con_video:
        assert kwargs["extra_parts"][0]["fileData"]["mimeType"] == "video/*"


# --- 2. Lo guardado se revalida: el artefacto real de produccion -----------

_ARTEFACTO = {
    "url": "https://www.youtube.com/watch?v=xK8SEUzk7BU",
    "title": "Canserbero - Es Épico",
    "genres": "Rap Conciencia, Hip-Hop, Rap",
    "rhythm": "Ritmo lento y medido, 70 BPM",
    "instruments": ["Piano", "Sintetizadores", "Bajo"],
    "structure": "Intro, Verso 1, Coro, Verso 2, Coro, Verso 3, Coro, Outro",
    "mood": "Oscuro, Dramático, Reflexivo, Épico",
    "lyric_themes": ["la muerte, el destino y la vida"],
    "lyric_style": "Poético, Introspectivo, Narrativo",
    "summary_text": (
        "Reference: Your browser is deprecated\n"
        "Genres and mix: Rap Conciencia, Hip-Hop, Rap\n"
        "Rhythm and feel: Ritmo lento y medido, 70 BPM"
    ),
    # El cliente jura que es utilizable: la marca no se fia del cliente,
    # se recalcula del texto guardado.
    "inspiration_usable": True,
}

_BUEN_RESUMEN = {
    "url": "https://www.youtube.com/watch?v=85qUEUMJGvk",
    "title": "Amándote",
    "genres": "Rap acústico",
    "rhythm": "Suave",
    "instruments": ["guitarra acústica"],
    "structure": "verso, coro",
    "mood": "Melancólico",
    "lyric_themes": ["amar a distancia"],
    "lyric_style": "Poético",
    "summary_text": (
        "Reference: Amándote\n"
        "Genres and mix: Rap acústico\n"
        "Rhythm and feel: Suave"
    ),
}


def test_el_artefacto_real_queda_marcado_y_fuera_de_los_prompts(client, studio):
    """La forma exacta que quedo guardada en produccion: titulo
    correcto, resumen que empieza «Reference: Your browser is
    deprecated». Entra por la ruta real de guardado de la Biblia (el
    PUT verbatim de la pantalla) y tiene que salir marcada como no
    utilizable en la escritura y en la lectura, y fuera de cada
    prompt — mientras el resumen bueno de al lado sigue entrando."""
    uid = _universo(client, studio, gender="mujer")["id"]

    respuesta = client.put(
        f"/api/universes/{uid}/bible/inspirations",
        json={"inspirations": [_ARTEFACTO, _BUEN_RESUMEN]},
    )
    assert respuesta.status_code == 200, respuesta.text
    marcado, bueno = respuesta.json()
    assert marcado["inspiration_usable"] is False
    assert "browser is deprecated" in marcado["inspiration_unusable_reason"]
    assert bueno["inspiration_usable"] is True

    # La lectura recalcula la marca: tampoco ahi pasa por valido.
    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["inspirations"][0]["inspiration_usable"] is False
    assert biblia["inspirations"][1]["inspiration_usable"] is True

    # Fuera de los prompts: ni el bloque de inspiraciones, ni el
    # resumen de la Biblia, ni el encargo de un concepto de cancion.
    guardada = load_bible(studio.db, uid)
    bloque = inspiration_service.bible_inspiration_text(guardada)
    assert "browser is deprecated" not in bloque
    assert "Amándote" in bloque
    assert "browser is deprecated" not in summarize_bible(guardada)

    cancion = client.post(f"/api/universes/{uid}/songs", json={"title": "Neon"}).json()
    client.post(
        f"/api/universes/{uid}/songs/{cancion['id']}/concept",
        json={"brief": "Una idea"},
    )
    studio.jobs.wait_for_idle(20)
    for llamada in studio.calls.all():
        if llamada.method != "generateContent":
            continue
        texto = str(llamada.payload)
        assert "browser is deprecated" not in texto


def test_la_creacion_no_traga_el_enlace_que_falla(client, studio, monkeypatch):
    """«Como Mario» desaparecio al crear el artista porque su analisis
    fallo y el fallo se trago en silencio. Ahora el enlace queda en la
    lista visible de fallidos de la ficha, y al pegarlo bien sale solo
    de la lista."""

    def fake_fallo(client, model, **kwargs):
        raise ProviderError("Vertex no respondio")

    monkeypatch.setattr(inspiration_service.gemini_text, "generate", fake_fallo)
    enlace = "https://www.youtube.com/watch?v=_qkNEdaMYLs"
    uid = _universo(client, studio, gender="mujer", inspiration_urls=[enlace])["id"]

    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["inspirations"] == []
    assert biblia["inspirations_failed"] == [enlace]

    def fake_bien(client, model, **kwargs):
        return SimpleNamespace(
            data={
                "title": "Como Mario",
                "genres": "Rap juguetón",
                "rhythm": "Rápido, con saltos",
                "instruments": ["sintetizadores de videojuego"],
                "structure": "verso, coro",
                "mood": "Divertido",
                "lyric_themes": ["videojuegos y barrio"],
                "lyric_style": "Directo, con referencias",
            }
        )

    monkeypatch.setattr(inspiration_service.gemini_text, "generate", fake_bien)
    respuesta = client.post(
        f"/api/universes/{uid}/bible/inspirations", json={"url": enlace}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["inspiration_usable"] is True

    biblia = client.get(f"/api/universes/{uid}/bible").json()
    assert biblia["inspirations_failed"] == []
    assert len(biblia["inspirations"]) == 1


# --- 3. La cola no muere en silencio: el vigilante --------------------------


def _trabajo_en_cola(studio, uid, **extra):
    trabajo = studio.jobs.create(
        uid,
        kind="text",
        model="gemini-3.1-pro-preview",
        variant="",
        target_type="artist_bible",
        target_id="current",
        request={},
        estimated_cost_usd=0.0,
    )
    if extra:
        trabajo = studio.jobs.repo(uid).update(trabajo["id"], extra)
    return trabajo


def test_el_vigilante_reencola_una_vez_y_luego_marca_el_fallo(studio, monkeypatch):
    uid = "uni_vigilante"
    encargos = []
    monkeypatch.setattr(
        studio.jobs, "enqueue", lambda u, j: encargos.append((u, j))
    )

    viejo = _trabajo_en_cola(studio, uid, created_at=_hace(11))
    fresco = _trabajo_en_cola(studio, uid)
    en_marcha = _trabajo_en_cola(
        studio,
        uid,
        created_at=_hace(30),
        state=JobState.PROCESSING.value,
        attempts=1,
    )

    # Primera lectura: el viejo se re-encola una vez; los demas, intactos.
    studio.jobs.list(uid)
    assert encargos == [(uid, viejo["id"])]
    guardado = studio.jobs.repo(uid).require(viejo["id"])
    assert guardado["state"] == JobState.QUEUED.value
    assert guardado["watchdog_requeued_at"]

    # Segunda lectura seguida: no se re-encola dos veces.
    studio.jobs.list(uid)
    assert encargos == [(uid, viejo["id"])]

    # Si tampoco esa entrega llega, a la siguiente ventana el trabajo
    # queda FAILED con el motivo a la vista — nunca «en cola» eterno.
    studio.jobs.repo(uid).update(
        viejo["id"], {"watchdog_requeued_at": _hace(11)}
    )
    studio.jobs.list(uid)
    guardado = studio.jobs.repo(uid).require(viejo["id"])
    assert guardado["state"] == JobState.FAILED.value
    assert guardado["error"] == MENSAJE_COLA_NO_ENTREGO
    assert encargos == [(uid, viejo["id"])]

    assert studio.jobs.repo(uid).require(fresco["id"])["state"] == (
        JobState.QUEUED.value
    )
    assert studio.jobs.repo(uid).require(en_marcha["id"])["state"] == (
        JobState.PROCESSING.value
    )
