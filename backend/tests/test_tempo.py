"""El tempo real y la medida de la letra (2026-11-07).

El dueno reporto que la cancion salia «a mil por hora» escogiera el
genero que escogiera, y acepto el arreglo con su matiz: si el genero
amerita cantar rapido, que cante rapido — el problema era que no
habia un control real. Lo que estas pruebas fijan:

- la tabla de tempo cubre TODOS los generos escogibles de la app;
- en una mezcla manda el genero principal (el primero que escogio);
- el presupuesto de palabras sale de la duracion y del paso del
  genero (una balada cabe menos palabras que un rap en los mismos
  segundos — es la cuenta de por que la letra larga salia corriendo);
- el encargo a Lyria lleva el tempo del genero y ya NO lleva el BPM
  que el Director inventaba en el concepto;
- el texto que Lyria recibe lleva la orden de ritmo: tempo firme,
  prohibido acelerar para que quepa la letra;
- la instruccion de escribir la letra lleva su medida en palabras, y
  contar palabras no cuenta las marcas de seccion.
"""

from __future__ import annotations

from app.domain import artist as artist_domain
from app.domain import tempo as tempo_domain
from app.orchestrator import director, handlers


def test_la_tabla_cubre_todos_los_generos_escogibles():
    assert set(tempo_domain.GENERO_TEMPO) == set(artist_domain.MUSIC_GENRE_KEYS)


def test_en_la_mezcla_manda_el_genero_principal():
    tempo = tempo_domain.tempo_de_la_cancion(["regueton", "trap"])
    assert tempo is not None
    assert tempo.bpm == 88
    linea = tempo_domain.linea_tempo(["regueton", "trap"])
    assert "Tempo: 88 BPM" in linea
    # Sin genero de la tabla no se inventa ningun numero.
    assert tempo_domain.tempo_de_la_cancion([]) is None
    assert tempo_domain.linea_tempo(["genero inventado"]) == ""


def test_el_presupuesto_sale_de_la_duracion_y_del_paso():
    regueton = tempo_domain.GENERO_TEMPO["regueton"]  # 140 palabras/min
    balada = tempo_domain.GENERO_TEMPO["balada"]  # 115 palabras/min
    rap = tempo_domain.GENERO_TEMPO["rap"]  # 185 palabras/min
    assert tempo_domain.presupuesto_palabras(180, regueton) == 420
    assert tempo_domain.presupuesto_palabras(180, balada) < 420
    assert tempo_domain.presupuesto_palabras(180, rap) > 420
    # La letra de unas 650 palabras no cabe en 180 segundos a paso
    # natural: esa era la cuenta del problema.
    assert tempo_domain.presupuesto_palabras(180, regueton) < 650


def test_contar_palabras_sin_las_marcas_de_seccion():
    letra = "[Verso 1]\nuna dos tres\n\n[Coro]\ncuatro cinco\n"
    assert tempo_domain.contar_palabras(letra) == 5


def test_el_encargo_lleva_el_tempo_del_genero_y_no_el_inventado():
    cancion = {
        "music_prompt": "trap oscuro y callejero",
        "genre": "Trap",
        "bpm": 999,
        "genres": ["regueton"],
        "concept": {"genre": "Trap", "bpm": 888, "mood": "oscuro"},
    }
    prompt = handlers._compose_music_prompt(cancion, [], {}, bible=None)
    assert "Tempo: 88 BPM" in prompt
    assert "999" not in prompt
    assert "888" not in prompt


def test_la_instruccion_de_la_letra_lleva_su_medida():
    # Sin BPM del dueno, manda el natural del genero: regueton a 88,
    # 420 palabras en tres minutos.
    prompt = director.build_prompt(
        "lyrics",
        {
            "concept": {"title": "Neon"},
            "genre_keys": ["regueton"],
            "genres_text": "Reguetón",
        },
    )
    assert "THE MEASURE OF THIS LYRIC" in prompt
    assert "88 BPM" in prompt
    assert "420 words" in prompt
    assert "cut off" in prompt

    # Con su BPM puesto, la medida se calcula a SU velocidad.
    prompt = director.build_prompt(
        "lyrics",
        {
            "concept": {"title": "Neon"},
            "genre_keys": ["regueton"],
            "genres_text": "Reguetón",
            "bpm_usuario": 70,
        },
    )
    assert "70 BPM" in prompt
    assert "330 words" in prompt


def test_el_bpm_del_dueno_manda_en_el_encargo():
    linea = tempo_domain.linea_tempo_cancion(["regueton"], 100)
    assert "Tempo: 100 BPM" in linea
    # El numero es el tempo de la PISTA, no la velocidad de la voz:
    # la voz canta encima con el fraseo del genero, sin camara lenta
    # ni voz acelerada (correccion del dueno del 2026-11-08).
    assert "the tempo of the track" in linea
    assert "the beat the owner chose" in linea
    assert "never a slow-motion voice" in linea
    assert "for the singing voice" not in linea
    # Sin su numero, la linea es la del genero, sin marca de dueno.
    assert "the owner chose" not in tempo_domain.linea_tempo_cancion(["regueton"], None)


def test_el_presupuesto_de_letra_y_el_techo_absoluto():
    # Regueton a su natural (88 BPM, 140 por minuto): 420 en 3 minutos.
    assert tempo_domain.presupuesto_para_letra(["regueton"], 88) == 420
    # A 180 BPM cabria mucho mas, pero el techo absoluto manda: 550.
    assert tempo_domain.presupuesto_para_letra(["regueton"], 180) == 550
    assert tempo_domain.TECHO_PALABRAS == 550
    # La cuenta del aviso: 500 palabras a 88 BPM se pasan de 3 minutos.
    assert tempo_domain.duracion_estimada_segundos(500, ["regueton"], 88) > 180
    assert tempo_domain.duracion_estimada_segundos(420, ["regueton"], 88) == 180


def test_el_selector_guarda_el_bpm_y_la_ficha_lo_calcula(client, studio):
    creado = client.post("/api/universes", json={"name": "Nova"}).json()
    studio.jobs.wait_for_idle(20)
    uid = creado["id"]
    cancion = client.post(
        f"/api/universes/{uid}/songs",
        json={"title": "Neon", "genres": ["regueton"]},
    ).json()
    sid = cancion["id"]

    fuera = client.patch(
        f"/api/universes/{uid}/songs/{sid}", json={"bpm_usuario": 300}
    )
    assert fuera.status_code == 400, fuera.text

    puesta = client.patch(
        f"/api/universes/{uid}/songs/{sid}", json={"bpm_usuario": 70}
    )
    assert puesta.status_code == 200, puesta.text
    ficha = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert ficha["bpm_usuario"] == 70
    assert ficha["bpm_efectivo"] == 70
    assert ficha["bpm_natural"] == 88

    # Una letra larga a 70 BPM se pasa: el aviso viene en la ficha.
    letra_larga = "\n".join(f"palabra{i} otra mas aqui" for i in range(120))
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": letra_larga, "author": "user"},
    )
    ficha = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert ficha["palabras_letra"] == 480
    assert ficha["pasa_de_tres_minutos"] is True

    # Y generar la musica con esa cuenta falla a la vista, sin gastar
    # la llamada: el contador de llamadas de musica no se mueve.
    antes = len([c for c in studio.calls.all() if c.method == "interactions"])
    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/generate", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)
    despues = len([c for c in studio.calls.all() if c.method == "interactions"])
    assert despues == antes
    ficha = client.get(f"/api/universes/{uid}/songs/{sid}").json()
    assert ficha["versions"] == []


def test_el_texto_de_lyria_lleva_la_orden_de_ritmo(client, studio):
    creado = client.post("/api/universes", json={"name": "Nova"}).json()
    studio.jobs.wait_for_idle(20)
    uid = creado["id"]
    cancion = client.post(
        f"/api/universes/{uid}/songs", json={"title": "Neon"}
    ).json()
    sid = cancion["id"]
    client.put(
        f"/api/universes/{uid}/songs/{sid}/lyrics",
        json={"lyrics": "una letra de prueba, con su rima puesta", "author": "user"},
    )
    respuesta = client.post(f"/api/universes/{uid}/songs/{sid}/generate", json={})
    assert respuesta.status_code == 200, respuesta.text
    studio.jobs.wait_for_idle(20)

    llamada = [c for c in studio.calls.all() if c.method == "interactions"][-1]
    texto = llamada.payload["input"][0]["text"]
    # Un solo parrafo musical de actuacion: el bloque rigido PACING
    # desaparecio (Lyria lo obedecia al pie de la letra y la voz
    # salia en camara lenta o acelerada).
    assert "PERFORMANCE:" in texto
    assert "PACING:" not in texto
    assert "slow motion" in texto
    assert "repeat the chorus fewer times" in texto
    # La diccion queda intacta, palabra por palabra: es la orden que
    # curo los cortes de palabras en la 3.5.
    assert "DICTION:" in texto
