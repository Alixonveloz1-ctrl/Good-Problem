"""Elige una clave de API del proyecto para el navegador.

Prefiere la que Firebase crea para eso; si no hay, cualquiera sirve: una clave
de API no da acceso a nada por sí sola, sólo identifica al proyecto.
"""

import json
import sys

try:
    claves = json.load(sys.stdin)
except Exception:
    claves = []
if not isinstance(claves, list):
    claves = []

preferidas = [k for k in claves if "browser" in (k.get("displayName") or "").lower()]
elegidas = preferidas or claves
print(elegidas[0].get("name", "") if elegidas else "")
