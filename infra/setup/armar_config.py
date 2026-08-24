"""La configuración del login sin depender de la aplicación web de Firebase.

Son los tres datos que Firebase Authentication necesita. El appId, que es lo
único que aporta la aplicación web, lo piden Analytics e Installations, y esta
app no lleva ninguno de los dos: exigirlo dejaría la entrada rota esperando algo
que no hace falta.
"""

import json
import sys

clave, proyecto = sys.argv[1], sys.argv[2]
print(
    json.dumps(
        {
            "apiKey": clave,
            "authDomain": f"{proyecto}.firebaseapp.com",
            "projectId": proyecto,
        },
        separators=(",", ":"),
    )
)
