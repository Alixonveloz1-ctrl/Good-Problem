"""El appId de la aplicación web de Firebase, o vacío si todavía no existe.

Vive en un archivo y no dentro de setup.sh a propósito: incrustar Python dentro
de un script de bash que a su vez se genera desde otro sitio es donde se cuelan
los errores de comillas, y aquí además se puede probar.
"""

import json
import sys

try:
    apps = json.load(sys.stdin).get("apps", [])
except Exception:
    apps = []
print(apps[0]["appId"] if apps else "")
