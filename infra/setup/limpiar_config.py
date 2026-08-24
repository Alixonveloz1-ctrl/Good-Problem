"""Deja la configuración de Firebase en una línea y sólo con lo que se usa.

Si faltan las tres que el login necesita no imprime nada, y quien llama toma el
otro camino. Devolver una configuración a medias sería peor: la app arrancaría
creyendo que puede identificar a alguien.
"""

import json
import sys

CLAVES = ("apiKey", "authDomain", "projectId", "appId", "storageBucket", "messagingSenderId")

try:
    crudo = json.load(sys.stdin)
except Exception:
    raise SystemExit

limpio = {k: v for k, v in crudo.items() if k in CLAVES and isinstance(v, str) and v}
if all(k in limpio for k in ("apiKey", "authDomain", "projectId")):
    print(json.dumps(limpio, separators=(",", ":")))
