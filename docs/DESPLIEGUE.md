# Poner la aplicación en marcha

Todo desde el iPhone. No hace falta un ordenador en ningún paso.

Vas a necesitar:

- Una cuenta de Google donde quieras que viva el estudio.
- La app **Google Cloud** instalada en el iPhone (App Store, gratis).
- Una tarjeta para activar la facturación. Sin ella, Google no deja usar Veo ni
  Lyria, aunque tengas los $300 de crédito.

Tiempo: entre 30 y 45 minutos, casi todo esperando.

---

## Antes de empezar: mete el código en `main`

El proyecto está en GitHub, pero en una rama llamada
`claude/new-session-mit2h4`. El despliegue automático mira la rama **main**, así
que hay que juntarlas.

Desde el móvil, en github.com:

1. Entra en tu repositorio **Good-Problem**.
2. Verás un aviso de la rama `claude/new-session-mit2h4`. Toca **Compare & pull
   request**.
3. Toca **Create pull request** y luego **Merge pull request**.

Ya está en `main`.

---

## Paso 1 · Crear el proyecto de Google Cloud

En la app de Google Cloud, con la cuenta que vayas a usar:

1. Arriba del todo, toca el selector de proyecto y luego **Nuevo proyecto**.
2. Ponle un nombre, por ejemplo `universe-studio`.
3. Apunta el **ID del proyecto** que te asigna. Es algo como
   `universe-studio-479201`. **Ese es el dato que vas a usar todo el rato**, no
   el nombre.
4. Ve a **Facturación** y asocia el proyecto a tu cuenta de facturación.

---

## Paso 2 · Instalar todo con un comando

En la misma app, abre **Cloud Shell** (el icono `>_` arriba a la derecha). Es
una terminal de Google, no de tu móvil. Tarda un momento en arrancar.

Escribe esto, cambiando las dos cosas en mayúsculas:

```bash
git clone https://github.com/Alixonveloz1-ctrl/Good-Problem.git
cd Good-Problem
bash infra/setup.sh TU-ID-DE-PROYECTO tucorreo@gmail.com us-central1
```

Tarda unos diez minutos. Te va a pedir permiso un par de veces: acepta.

Esto crea todo lo que la aplicación necesita: la base de datos, el sitio donde
se guardan los vídeos, la cola de trabajos, los permisos y los avisos de gasto.

Cuando termine, te deja una lista de lo que falta. Es lo que viene ahora.

---

## Paso 3 · Conectar GitHub para que se despliegue solo

En la consola de Google Cloud (`console.cloud.google.com` desde Safari):

1. Busca **Cloud Build** → **Activadores** (Triggers).
2. **Conectar repositorio** → elige **GitHub** → autoriza → elige
   **Good-Problem**.
3. **Crear activador**:
   - Evento: *Enviar a una rama*
   - Rama: `^main$`
   - Configuración: *Archivo de configuración de Cloud Build*
   - Ubicación: `cloudbuild.yaml`
4. Abajo, en **Variables de sustitución**, añade estas tres:

   | Variable | Valor |
   |---|---|
   | `_OWNER_EMAIL` | tu correo de Google |
   | `_REGION` | `us-central1` |
   | `_BUCKET` | `TU-ID-DE-PROYECTO-aaus` |

5. Guarda y toca **Ejecutar** para lanzarlo la primera vez.

Tarda unos diez minutos. Cuando acabe, tienes una dirección web tipo
`https://aaus-xxxxx.us-central1.run.app`.

Si abres esa dirección ahora, te dirá que no tienes permiso. Es lo correcto:
falta el paso 4.

---

## Paso 4 · Poner el candado (IAP)

Esto es lo que hace que solo puedas entrar tú, con tu cuenta de Google, sin que
haya que construir una pantalla de contraseña dentro de la app.

En la consola:

1. Busca **Identity-Aware Proxy**.
2. La primera vez te pedirá configurar la **pantalla de consentimiento**: elige
   **Interno** si tu cuenta es de empresa, o **Externo** si es una cuenta normal
   de Gmail. Pon el nombre de la app y tu correo. No hace falta nada más.
3. En la lista, busca tu servicio `aaus` y **activa** el interruptor.
4. Selecciónalo, toca **Añadir principal**, pon tu correo y dale el rol
   **IAP-secured Web App User**.

Ahora abre la dirección del paso 3. Te pedirá iniciar sesión con Google y
entrarás.

---

## Paso 5 · El dato que hace que las generaciones arranquen

Este paso es fácil de saltarse y sin él **la app se queda pensando para
siempre**: pides una imagen y nunca llega.

Al activar IAP, Google te crea una credencial. Hay que dársela a la cola de
trabajos.

1. En la consola, busca **Credenciales de API**.
2. En la sección **ID de cliente de OAuth 2.0** verás una entrada creada
   automáticamente por IAP. Copia su **ID de cliente** (termina en
   `.apps.googleusercontent.com`).
3. Vuelve a **Cloud Build** → **Activadores** → tu activador → **Editar**.
4. Añade una variable más:

   | Variable | Valor |
   |---|---|
   | `_IAP_AUDIENCE` | el ID de cliente que copiaste |

5. Guarda y toca **Ejecutar** otra vez.

**Por qué:** los trabajos largos, como generar un vídeo, no se hacen mientras
esperas. Se meten en una cola de Google que los ejecuta por su cuenta, y por eso
puedes cerrar Safari y seguir con tu vida. Pero esa cola también tiene que pasar
el candado del paso 4, y este dato es su llave.

---

## Paso 6 · Instalarla en la pantalla de inicio

1. Abre la dirección en **Safari** (no en Chrome).
2. Toca **Compartir** → **Añadir a pantalla de inicio**.

Se abre a pantalla completa, en vertical, con su icono. Ya es tu app.

---

## Comprobar que todo está bien

Entra en la app y ve a **Ajustes**. Deberías ver:

- **Proyecto:** el ID de tu proyecto (no «local»).
- **Almacenamiento:** `gcs`.
- **Modo:** *En producción* en verde. Si dice *Dry run*, no está gastando ni
  generando de verdad: revisa el paso 3.

Luego haz la prueba de fuego: crea un artista, pídele el Artist Bible al
Director, y espera. Si en un minuto tienes propuesta, todo funciona. Si se queda
pensando, es el paso 5.

---

## La voz del artista (opcional, para entrevistas y BTS)

Solo si vas a hacer contenido hablado.

1. En la consola, busca **Text-to-Speech** y **solicita acceso** a *Chirp 3:
   Instant Custom Voice*. Google tarda en responder.
2. Cuando te lo concedan, en la app entra en tu artista → **Voz del artista** y
   sigue los dos pasos de grabación.

Sin eso, la música y el vídeo funcionan igual. Solo se queda sin la voz hablada.

---

## Cuando quieras cambiar algo

Ya no tienes que repetir nada de esto. Cada vez que el código cambie en `main`,
Google lo despliega solo en unos diez minutos.

Para cambiar precios de modelos o quitar uno que Google apague, tampoco hace
falta desplegar: se edita un documento en la base de datos y la app lo lee.

---

## Si algo va mal

**«No tienes permiso» al abrir la dirección** — Falta el paso 4, o tu correo no
está en la lista de IAP.

**Las generaciones se quedan pensando y nunca terminan** — Es el paso 5, casi
seguro. Comprueba que `_IAP_AUDIENCE` está en el activador y que volviste a
ejecutar el despliegue.

**En Ajustes dice «Dry run»** — El despliegue no cogió la variable
`AAUS_DRY_RUN=false`. Vuelve a ejecutar el activador de Cloud Build.

**Error al generar, diciendo que falta permiso sobre Vertex AI** — La API no
está activada o falta un rol. Vuelve a ejecutar `infra/setup.sh`: es seguro
repetirlo.

**Quiero ver cuánto llevo gastado** — En la app de Google Cloud, **Facturación**
→ **Informes**. La aplicación no lleva cuentas a propósito.
