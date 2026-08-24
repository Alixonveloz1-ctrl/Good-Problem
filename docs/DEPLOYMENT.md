# Despliegue

Referencia técnica. Para instalar, se ejecuta `./setup.sh` desde Cloud Shell:
no pide argumentos y va explicando en pantalla lo que hace.

Todo desde el iPhone. Si algún paso necesita una computadora, está marcado y
explicado por qué.

---

## Regla del proyecto: ninguna clave JSON

**No se genera, no se descarga y no se almacena ninguna clave JSON de cuenta de
servicio en ningún punto del sistema.** Si existe alguna de un flujo anterior,
se elimina desde IAM.

| Quién llama a quién | Cómo se autentica |
|---|---|
| Cloud Run → Vertex AI, Firestore, Storage, Text-to-Speech | Cuenta de servicio adjunta, vía Application Default Credentials. Las librerías de Google la toman solas |
| Cloud Run → URLs firmadas de Storage | API `signBlob` de IAM con esa misma identidad. Por eso no hace falta un archivo de clave |
| Cloud Build → GitHub | Conexión gestionada por Google con su app de GitHub |
| Cloud Build → Cloud Run | Su propia cuenta de servicio |
| Cloud Tasks → el worker | Token OIDC emitido en el momento |
| Safari → Cloud Run | Entrada con Google (`accounts.google.com/gsi`) y luego una cookie de sesión firmada |

Tampoco se guarda la credencial en una variable de entorno del servicio: eso
dejaría una credencial en la configuración cuando el runtime ya tiene identidad
propia.

Secret Manager guarda **una sola cosa**: la clave de voz clonada de Chirp 3, que
es un identificador de la API y no una credencial de acceso a la cuenta.

---

## 1. Provisión

Desde **Cloud Shell**, en la app de Google Cloud para iOS:

```bash
git clone -b main https://github.com/Alixonveloz1-ctrl/Good-Problem.git
cd Good-Problem
./setup.sh
```

El script toma el proyecto y la cuenta de la sesión de Cloud Shell, habilita las
APIs, crea Firestore, el bucket, la cola de Cloud Tasks, las dos cuentas de
servicio con sus roles y el acceso del propietario, publica el servicio con
`gcloud run deploy --source .` y le conecta la cola con la URL que acaba de
obtener.

También genera `AAUS_SESSION_SECRET` y un código de instalación de ocho
caracteres, y los conserva entre ejecuciones: regenerarlos cerraría la sesión
abierta en el iPhone sin motivo. Se puede ejecutar las veces que haga falta.

Deja pendiente **un solo paso manual**, y no por comodidad: Google no publica
ninguna API para crear un cliente OAuth de tipo web ni para añadirle orígenes de
JavaScript, así que ese cliente hay que crearlo a mano en la consola. El script
imprime los tres enlaces exactos y el código.

Roles de la cuenta de servicio del runtime, y ninguno más:

- `roles/aiplatform.user` — Gemini, Gemini Image, Lyria, Veo
- `roles/datastore.user` — Firestore
- `roles/storage.objectAdmin` — Cloud Storage
- `roles/serviceusage.serviceUsageConsumer` — Cloud Text-to-Speech
- `roles/secretmanager.secretAccessor` — la clave de voz de Chirp
- `roles/cloudtasks.enqueuer`, `roles/run.invoker`, `roles/logging.logWriter`

## 2. CI/CD

En la consola de Cloud Build, conectar el repositorio (Google gestiona la
conexión con su app de GitHub) y crear un disparador sobre `main` que use
`cloudbuild.yaml`, con estas sustituciones:

```
_OWNER_EMAIL = propietario@gmail.com
_REGION      = us-central1
_BUCKET      = MI-PROYECTO-aaus
```

A partir de ahí, un push a `main` ejecuta tests, construye las dos imágenes y
despliega el servicio y el Cloud Run Job de ensamblaje.

Para un despliegue puntual, desde Cloud Shell:

```bash
gcloud run deploy aaus --source . --region us-central1 \
  --service-account aaus-run@MI-PROYECTO.iam.gserviceaccount.com \
  --allow-unauthenticated
```

## 3. Acceso: entrar con la cuenta de Google

El PRD daba por hecho IAM más **Identity Aware Proxy**: un servicio con
`--no-allow-unauthenticated` y el proxy delante convirtiendo la sesión de Google
del navegador en una petición autorizada, sin pantalla de login ni pantalla de
consentimiento que configurar.

No se sostiene, por dos motivos que solo se ven al intentarlo:

1. En una cuenta personal de Gmail, IAP exige crear a mano una marca y un
   cliente de OAuth en la consola —la misma pantalla de consentimiento que se
   quería evitar—. Hasta que eso está hecho, el servicio responde
   `Empty Google Account OAuth client ID(s)/secret(s)` y nada más.
2. Las APIs de administración de OAuth de IAP las apagó Google el 19 de marzo de
   2026, así que `gcloud iap oauth-clients` ya no sirve para automatizar ese
   paso.

Así que la puerta la pone la aplicación:

- El servicio es **público en la red** (`--allow-unauthenticated`), y tiene que
  serlo: para dibujar la pantalla de entrada hay que poder cargarla antes de
  saber quién eres.
- El navegador entra con **Google Identity Services**. Google devuelve un token
  firmado; el servidor lo verifica con la librería oficial (firma, caducidad,
  emisor, y que fuera emitido para *este* cliente) y comprueba que el correo sea
  `AAUS_OWNER_EMAIL`. Las dos cosas: la primera sola dejaría entrar a cualquiera
  con una cuenta de Google.
- A cambio se entrega una cookie de sesión firmada con HMAC (`aaus_session`,
  30 días, `HttpOnly`, `Secure`, `SameSite=Lax`).

### La puerta es un middleware, no un decorador por ruta

`app/auth.py:gate()` se aplica a **todas** las peticiones desde `main.py`, y no
ruta por ruta. Una ruta nueva se puede escribir sin acordarse de pedir
identidad; de hecho pasó, y `/media/` servía cualquier archivo generado a quien
acertara la ruta. Un middleware no se olvida.

| Qué | Quién puede |
|---|---|
| `/`, `/assets/*` | Cualquiera. Es lo que dibuja la pantalla de entrada |
| `/api/health`, `/api/auth/*` | Cualquiera. Nadie puede identificarse si para identificarse hay que estar ya dentro |
| `/api/internal/*` | Solo Cloud Tasks, con su token OIDC. La cookie del navegador **no** vale |
| Todo lo demás bajo `/api/` y `/media/` | Solo la sesión del propietario |

### El paso que Google no deja automatizar

Hay que crear un cliente OAuth de tipo **Aplicación web** en la consola y poner
la URL del servicio en *Orígenes autorizados de JavaScript*. No existe API para
esto. Y hay que **publicar** la aplicación en la pantalla de consentimiento: en
modo Prueba, Google bloquea al propio dueño.

Lo que sale de ahí son unos setenta caracteres, y Cloud Shell en un móvil no
deja pegar. Por eso el Client ID entra por `POST /api/auth/setup` desde el propio
navegador, autorizado con el código de ocho caracteres que el instalador imprime
(`AAUS_SETUP_CODE`). Se guarda en Firestore (`config/auth`), así que sobrevive a
los redespliegues; `AAUS_OAUTH_CLIENT_ID`, si está puesta, manda sobre él.

Ese código **sigue valiendo después de instalar**, y es a propósito: un Client ID
mal copiado deja la pantalla de entrada sin botón, y entonces «entra primero
para corregirlo» es imposible. La pantalla de entrada ofrece *Cambiar el Client
ID* para exactamente eso. Cinco intentos fallidos cierran la ruta un cuarto de
hora.

### La cola de trabajos

Los trabajos largos no se ejecutan dentro de la petición: Cloud Tasks los empuja
de vuelta a `POST /api/internal/jobs/run` del mismo servicio, y por eso una
generación sobrevive a que se cierre Safari (PRD 37).

Esa petición trae un token OIDC firmado por la cuenta `aaus-tasks`. El worker
comprueba firma, caducidad, destinatario y que el correo sea el de esa cuenta.
La audiencia se pone **a mano** en `auth.py:service_audience()`, que es también
lo que usa `services/jobs.py` al encolar: si se dejara al valor por defecto,
Cloud Tasks firmaría para la URL completa con su ruta y el worker comprobaría
contra la URL base, y cada trabajo moriría en un 401 sin ningún error visible en
la app.

Y `AAUS_TASKS_TARGET_URL` es la URL del propio servicio, que no existe hasta
haberlo desplegado: el paso `conectar-cola` de `cloudbuild.yaml` la lee después
del despliegue y actualiza el servicio con ella.

### Lo que la compilación no toca

`cloudbuild.yaml` usa `--update-env-vars`, nunca `--set-env-vars`. El correo del
dueño, la clave de sesión, el código y el Client ID los pone `setup.sh` una vez;
un `--set-env-vars` en el despliegue los borraría todos y dejaría el estudio
público y sin puerta. El paso `comprobar-la-puerta` tumba la compilación si
`AAUS_OWNER_EMAIL` acaba vacío, porque es el único de estos fallos que no se ve
mirando la aplicación.

## 4. Instalar la PWA en el iPhone

1. Abrir la URL del servicio en Safari e iniciar sesión con la cuenta del
   propietario.
2. Compartir → Añadir a pantalla de inicio.

Se abre en pantalla completa, en vertical, con su icono. Los jobs siguen
corriendo en Google Cloud aunque se cierre.

## 5. Voz hablada con Chirp 3

Dos trámites, una sola vez:

1. Solicitar acceso a **Chirp 3: Instant Custom Voice** en la consola de Cloud
   Text-to-Speech.
2. Grabar dos audios: una muestra de ~10 segundos de la voz y la grabación de
   consentimiento con el texto exacto que exige Google (está en
   `providers/chirp.py:CONSENT_SCRIPT`).

Después, desde la app:

```
POST /api/universes/{id}/content/voice-clone
{ "sample_base64": "...", "consent_base64": "..." }
```

La clave devuelta se guarda en Secret Manager y se referencia desde el Voice
Profile. A partir de ahí, entrevistas, BTS y diario del artista suenan igual
siempre.

## 6. Control de gasto

**La aplicación no controla el gasto.** No lleva contador, no muestra el crédito
restante y no rechaza ninguna generación por presupuesto. Es una desviación
deliberada del PRD 44, a petición del propietario: el gasto se consulta en la
consola de Google Cloud.

Lo que conviene dejar montado allí:

- **Budget alerts** sobre la cuenta de facturación. Avisan por correo; no
  detienen nada.
- Si quieres un freno de verdad, se monta en Google Cloud, no aquí: un
  presupuesto con una función de Cloud Functions suscrita al tema de Pub/Sub que
  desactive la facturación del proyecto al llegar al tope.

Dos cosas que conviene tener presentes de los $300 de bienvenida, porque la app
ya no te las va a recordar:

- **Caducan a los 90 días del alta**, se usen o no.
- Si se agotan por gasto o por calendario, la cuenta de prueba se cierra y los
  proyectos se detienen, con 30 días de gracia para pasar a cuenta de pago.

El crédito no cubre la Gemini API de AI Studio ni modelos de socios en Vertex.
Los modelos propios de Google —Gemini, Veo, Lyria— sí.

Dentro de la app, lo único que sigue hablando de dinero es lo que cuesta algo
**antes** de lanzarlo: el precio de cada opción en el selector de modelo y la
estimación del Production Plan. El video se factura por segundo, así que el
selector muestra el precio del clip completo.

## 7. Primer arranque

`AAUS_DRY_RUN` vale `true` por defecto, a propósito: un despliegue mal
configurado no puede gastar dinero por accidente. `cloudbuild.yaml` lo pone en
`false` explícitamente al desplegar.

Para comprobar que el servicio está vivo y en qué modo:

```
GET /api/health
```

## 8. Cuando Google apague o añada un modelo

No hay que tocar código ni volver a desplegar. Se edita el documento
`config/models` de Firestore, desde la consola o con:

```
PUT /api/registry/models      (documento completo)
POST /api/registry/reload     (releer sin reiniciar)
```

Los modelos bloqueados en `guards.py` —`lyria-3`, `lyria-2`, las versiones de
Imagen— no se pueden reactivar desde ahí. Aparecerán en la lista de excluidos
con el motivo.

## 9. Ensamblaje pesado

El servicio ensambla en proceso cuando el proyecto es pequeño. Para un
videoclip largo conviene lanzar el Cloud Run Job, que tiene FFmpeg, más CPU y
una hora de límite:

```bash
gcloud run jobs execute aaus-assembly --region us-central1 \
  --update-env-vars UNIVERSE_ID=uni_x,PROJECT_ID=vp_y,JOB_ID=job_z
```

El Job actualiza el mismo documento de Job que ve el teléfono, así que los
estados son los mismos.
