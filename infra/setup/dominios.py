"""Los dominios que faltan por autorizar, o nada si ya están todos.

Se añaden a los que ya hay en vez de reemplazarlos: la lista trae localhost y el
propio dominio de Firebase, y borrarlos rompería cosas que funcionan.
"""

import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        actual = json.load(f).get("authorizedDomains", [])
except Exception:
    actual = []

faltan = [d for d in sys.argv[2:] if d and d not in actual]
print(json.dumps({"authorizedDomains": actual + faltan}) if faltan else "")
