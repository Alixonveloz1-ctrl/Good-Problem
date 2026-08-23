# Despliegue

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
| Safari → Cloud Run | La sesión de Google del propietario, a través de IAP |

Tampoco se guarda la credencial en una variable de entorno del servicio: eso
dejaría una credencial en la configuración cuando el runtime ya tiene identidad
propia.

Secret Manager guarda **una sola cosa**: la clave de voz clonada de Chirp 3, que
es un identificador de la API y no una credencial de acceso a la cuenta.

---

## 1. Provisión

Desde **Cloud Shell**, en la app de Google Cloud para iOS:

```bash
git clone https://github.com/<usuario>/<repo>.git
cd <repo>
bash infra/setup.sh MI-PROYECTO propietario@gmail.com us-central1
```

El script habilita las APIs, crea Firestore, el bucket, Artifact Registry, la
cola de Cloud Tasks, la cuenta de servicio del runtime con sus roles, el budget
alert y el acceso del propietario. Volver a ejecutarlo es seguro.

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
  --no-allow-unauthenticated
```

## 3. Acceso: IAM más IAP

El PRD dice que el acceso se controla con IAM sobre el servicio de Cloud Run
contra la cuenta de Google del propietario. Es correcto, con un matiz que
conviene tener claro antes de empezar:

Un servicio con `--no-allow-unauthenticated` espera una cabecera
`Authorization: Bearer <token>` que **Safari no envía por sí solo**. Lo que
convierte la sesión de Google del navegador en una petición autorizada es
**Identity Aware Proxy**.

Activarlo, una vez, desde la consola:

1. Security → Identity-Aware Proxy.
2. Activar IAP sobre el servicio de Cloud Run `aaus`.
3. Conceder `roles/iap.httpsResourceAccessor` únicamente a la cuenta del
   propietario (`setup.sh` ya lo hace).

Con IAP delante, el navegador entra con la sesión de Google que ya tiene. No hay
login dentro de la app y **no hay pantalla de consentimiento OAuth que
configurar**, que era justamente el paso que habría obligado a usar una
computadora.

La aplicación comprueba además la cabecera `X-Goog-Authenticated-User-Email`
contra `AAUS_OWNER_EMAIL` (`app/auth.py`). Es la segunda cerradura: si la
petición llegó al contenedor, IAP ya respondió por ella.

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

Lo que hay que dejar montado allí, y `infra/setup.sh` ya lo crea:

- **Budget alerts** sobre la cuenta de facturación, con avisos al 50 %, 90 % y
  100 %. Avisan por correo; no detienen nada.
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
