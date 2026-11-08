"""El tempo real: la velocidad natural de cada genero y la medida de la letra.

El problema que esto resuelve, dicho por el dueno el 2026-11-07: la
cancion salia «a mil por hora» escogiera el genero que escogiera. Por
dentro habia dos causas sumadas:

1. No existia un control de tempo de verdad. El unico numero que
   llegaba a Lyria era el BPM que el Director inventaba al crear el
   concepto — sin relacion con los generos que el dueno escoge ni con
   ninguna orden de fraseo —, asi que cambiar de genero no cambiaba
   la velocidad.
2. La letra nacia sin medida: la estructura completa de siempre
   (versos largos, tercer verso, coro repetido) suma unas 650
   palabras, que cantadas con calma piden 4-5 minutos, pero la
   duracion pedida era de 180 segundos. Lyria obedece la duracion, y
   la unica forma de meter todo era acelerar.

Aqui vive la respuesta a las dos:

- ``GENERO_TEMPO``: por cada genero escogible, su BPM representativo,
  su paso de canto (espacioso / medio / rapido) y su frase de entrega
  en ingles para el encargo. Si el genero ES rapido, rapido canta —
  pero firme y controlado, que es lo que el dueno pidio: «si el
  genero amerita que se cante rapido, no hay ningun problema; el
  problema es que no hay un control real».
- ``presupuesto_palabras``: cuantas palabras caben cantadas bien en
  los segundos pedidos al paso del genero. La letra y su revision
  reciben esa medida y escriben dentro de ella.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TempoGenero:
    bpm: int
    """El BPM representativo del genero, el que viaja en el encargo."""

    paso: str
    """Su clase de paso al cantar: «espacioso», «medio» o «rapido»."""

    palabras_por_minuto: int
    """Palabras que caben cantadas bien en un minuto a ese paso."""

    frase: str
    """La entrega natural del genero, en ingles, para el encargo."""


GENERO_TEMPO: dict[str, TempoGenero] = {
    "pop": TempoGenero(110, "medio", 150, "steady pop phrasing, clear and unhurried"),
    "rock": TempoGenero(128, "medio", 145, "driving rock phrasing with air between the lines"),
    "balada": TempoGenero(68, "espacioso", 115, "slow ballad phrasing: long pauses, every line breathed"),
    "bachata": TempoGenero(130, "medio", 140, "romantic bachata phrasing, smooth and unhurried"),
    "salsa": TempoGenero(175, "rapido", 175, "salsa phrasing: energetic and articulated, with call-and-response space"),
    "merengue": TempoGenero(150, "rapido", 170, "fast merengue phrasing, punchy and rhythmic"),
    "regueton": TempoGenero(88, "medio", 140, "reggaeton perreo groove: phrasing behind the beat, relaxed, never rushed"),
    "trap": TempoGenero(140, "espacioso", 125, "trap half-time feel: sparse, spacious phrasing with pauses between bars"),
    "rap": TempoGenero(92, "rapido", 185, "hip-hop flow at a steady head-nod tempo: the flow may be dense, the tempo never moves"),
    "rnb": TempoGenero(85, "espacioso", 125, "smooth R&B phrasing, melismatic and unhurried"),
    "corridos": TempoGenero(145, "medio", 145, "corrido storytelling phrasing with air between verses"),
    "regional": TempoGenero(95, "espacioso", 120, "ranchera phrasing: big held notes and long pauses"),
    "cumbia": TempoGenero(105, "medio", 140, "cumbia phrasing: laid-back and danceable, lines with air"),
    "vallenato": TempoGenero(128, "medio", 140, "vallenato storytelling phrasing, unhurried"),
    "electronica": TempoGenero(126, "medio", 135, "EDM phrasing: few, spaced vocal lines over the beat"),
    "synthwave": TempoGenero(105, "medio", 135, "synthwave phrasing, cool and spaced"),
    "jazz": TempoGenero(110, "espacioso", 125, "jazz phrasing behind the beat, with lots of air"),
    "blues": TempoGenero(80, "espacioso", 120, "blues phrasing: slow, dragged, long pauses"),
    "country": TempoGenero(105, "medio", 145, "country storytelling phrasing, clear and unhurried"),
    "metal": TempoGenero(160, "rapido", 160, "metal phrasing: powerful, articulated lines with space between them"),
    "punk": TempoGenero(172, "rapido", 175, "punk phrasing: fast and raw, short shouted lines"),
    "indie": TempoGenero(115, "medio", 140, "indie phrasing, relaxed and conversational"),
    "folk": TempoGenero(100, "medio", 140, "folk storytelling phrasing, clear and unhurried"),
    "flamenco": TempoGenero(130, "medio", 135, "flamenco phrasing inside its compas, melisma and dramatic pauses"),
}

PASO_POR_DEFECTO = 145
"""Palabras por minuto cuando el genero no esta en la tabla (texto libre)."""


def tempo_de_la_cancion(generos: list[str] | None) -> TempoGenero | None:
    """El tempo que manda: el del primer genero escogido que este en la tabla.

    La mezcla la ordena el dueno en la pantalla; el primer genero es
    el principal y es el que pone la velocidad. Si ninguno esta en la
    tabla (solo texto libre), no hay numero que mandar: None.
    """
    for clave in generos or []:
        if clave in GENERO_TEMPO:
            return GENERO_TEMPO[clave]
    return None


def linea_tempo(generos: list[str] | None) -> str:
    """La linea de tempo del encargo a Lyria, o vacia si no hay tabla."""
    tempo = tempo_de_la_cancion(generos)
    if tempo is None:
        return ""
    return f"Tempo: {tempo.bpm} BPM. Delivery: {tempo.frase}."


def presupuesto_palabras(duracion_segundos: int, tempo: TempoGenero | None) -> int:
    """Cuantas palabras caben cantadas bien en esa duracion a ese paso.

    Redondeado a la decena: es una medida de trabajo para quien
    escribe, no una cifra de laboratorio.
    """
    por_minuto = tempo.palabras_por_minuto if tempo is not None else PASO_POR_DEFECTO
    return max(60, round(duracion_segundos * por_minuto / 60 / 10) * 10)


def contar_palabras(letra: str) -> int:
    """Las palabras cantadas de una letra: fuera las marcas de seccion."""
    total = 0
    for linea in (letra or "").splitlines():
        linea = linea.strip()
        if not linea or (linea.startswith("[") and linea.endswith("]")):
            continue
        total += len(linea.split())
    return total


# --- El BPM del dueno y los tres minutos ------------------------------------
#
# El dueno pidio el mando el 2026-11-07: un selector de BPM en la
# cancion, escogido ANTES de generar la letra, y ese numero es la
# velocidad de la voz que se le pide a Lyria. La duracion ya no es un
# numero fijo que la app imponga: nace de la letra y de ese BPM. Y
# una restriccion suya: ninguna letra puede pasar de tres minutos ni
# cantada a la velocidad mas alta — porque Lyria entrega hasta tres
# minutos, y una cancion mas larga no se generaria completa.

BPM_MINIMO = 60
BPM_MAXIMO = 180
DURACION_MAXIMA_SEGUNDOS = 180
"""Lo que Lyria entrega de una vez: el techo de la cancion."""

TECHO_PALABRAS = (
    max(t.palabras_por_minuto for t in GENERO_TEMPO.values())
    * DURACION_MAXIMA_SEGUNDOS
    // 60
    // 10
) * 10
"""El techo absoluto de una letra: 550 palabras.

Son las que caben en tres minutos al paso mas rapido de la tabla
(el rap, 185 por minuto). Ni cantada a toda velocidad, una letra de
la app se pasa de los tres minutos.
"""


def bpm_natural(generos: list[str] | None) -> int | None:
    """El BPM de la tabla para el genero principal, si lo hay."""
    tempo = tempo_de_la_cancion(generos)
    return tempo.bpm if tempo is not None else None


def bpm_efectivo(generos: list[str] | None, bpm_usuario: int | None) -> int | None:
    """El BPM que manda: el del dueno si lo puso; si no, el natural."""
    if bpm_usuario:
        return max(BPM_MINIMO, min(BPM_MAXIMO, int(bpm_usuario)))
    return bpm_natural(generos)


def paso_efectivo(generos: list[str] | None, bpm: int | None) -> float:
    """Palabras cantadas por minuto al BPM dado.

    El paso del genero escalado en la misma proporcion que el BPM se
    mueve del suyo natural: si el dueno baja el BPM a la mitad, en un
    minuto cabe la mitad de palabras. Sin genero de la tabla, el paso
    por defecto, sin escalar: no hay natural contra el que medir.
    """
    tempo = tempo_de_la_cancion(generos)
    if tempo is None or not bpm:
        return float(tempo.palabras_por_minuto if tempo is not None else PASO_POR_DEFECTO)
    return tempo.palabras_por_minuto * bpm / tempo.bpm


def duracion_estimada_segundos(
    palabras: int, generos: list[str] | None, bpm: int | None
) -> int:
    """El largo natural de esa letra a ese BPM, en segundos."""
    if palabras <= 0:
        return 0
    return round(palabras / paso_efectivo(generos, bpm) * 60)


def presupuesto_para_letra(generos: list[str] | None, bpm: int | None) -> int:
    """Las palabras que la app puede escribir para esta cancion.

    Las que caben en tres minutos al BPM escogido, y nunca mas del
    techo absoluto: la letra nace para no pasarse ni a su velocidad
    ni a ninguna.
    """
    caben = paso_efectivo(generos, bpm) * DURACION_MAXIMA_SEGUNDOS / 60
    return max(60, min(TECHO_PALABRAS, round(caben / 10) * 10))


def linea_tempo_cancion(generos: list[str] | None, bpm_usuario: int | None) -> str:
    """La linea de tempo del encargo: manda el BPM del dueno."""
    tempo = tempo_de_la_cancion(generos)
    bpm = bpm_efectivo(generos, bpm_usuario)
    if bpm is None:
        return ""
    if bpm_usuario:
        frase = tempo.frase if tempo is not None else "the genre's natural phrasing"
        return (
            f"Tempo: {bpm} BPM — the tempo the owner chose for the singing "
            f"voice. Delivery: {frase}."
        )
    return linea_tempo(generos)


def calculo_de_la_cancion(cancion: dict, generos: list[str] | None) -> dict:
    """Lo que la pantalla enseña: BPM vigente, cuenta y aviso.

    ``pasa_de_tres_minutos`` es el aviso del dueno: con la letra que
    hay y al BPM que hay, la cancion no se generaria completa.
    """
    bpm = bpm_efectivo(generos, cancion.get("bpm_usuario"))
    palabras = contar_palabras(cancion.get("lyrics") or "")
    estimada = duracion_estimada_segundos(palabras, generos, bpm)
    return {
        "bpm_efectivo": bpm,
        "bpm_natural": bpm_natural(generos),
        "palabras_letra": palabras,
        "duracion_estimada_segundos": estimada,
        "pasa_de_tres_minutos": bool(
            palabras and estimada > DURACION_MAXIMA_SEGUNDOS
        ),
    }
