"""El nombre de la clave recién creada.

gcloud la devuelve envuelta en una operación unas veces y suelta otras, así que
se miran los dos sitios.
"""

import json
import sys

try:
    datos = json.load(sys.stdin)
except Exception:
    datos = {}
print(datos.get("response", {}).get("name") or datos.get("name") or "")
