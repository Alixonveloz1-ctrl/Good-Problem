"""El valor de una variable de entorno del servicio ya desplegado, o vacío.

Se hace leyendo el JSON entero y no con una expresión de --format porque de eso
depende que la clave de sesión sobreviva a cada instalación: si la lectura falla
en silencio, el instalador genera una clave nueva, y una clave nueva echa de la
aplicación a quien estuviera dentro. Un fallo así no se ve al ejecutar el
script, solo cuando alguien vuelve a la app y le pide entrar otra vez.
"""

import json
import sys

try:
    datos = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit

contenedores = datos.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
variables = contenedores[0].get("env", []) if contenedores else []
print(next((v.get("value", "") for v in variables if v.get("name") == sys.argv[1]), ""))
