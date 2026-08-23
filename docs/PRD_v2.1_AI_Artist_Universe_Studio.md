# PRD — AI Artist Universe Studio
## MVP v2.1 — Google Cloud First / iPhone First

**Fecha:** 23 de agosto de 2026
**Base:** MVP v2.0 del 21 de agosto de 2026
**Estado:** Plan de producto / arquitectura MVP

---

## Qué se corrigió respecto a v2.0

El documento es el mismo, con la misma estructura. Solo cambió lo que estaba desactualizado o mal planteado:

1. **Generador de imagen.** El PRD original decía «Gemini Image». Ese nombre correspondía a Imagen, cuyos endpoints Google apagó el 17 de agosto de 2026, y que además nunca aceptó imágenes de referencia. Se sustituye por los tres modelos de imagen de Gemini, que sí las aceptan.
2. **Generador de video.** Se especifican los tres modelos Veo 3.1 disponibles, con selección manual y precio real por segundo.
3. **Generador de música.** Google publica tres modelos con nombres parecidos. Solo **Lyria 3 Pro** hace canciones completas; Lyria 3 y Lyria 2 hacen clips de 30 segundos y quedan fuera del sistema.
4. **Audio en el video.** Veo se llama siempre con el audio desactivado. La pista viene de Lyria. Esto cuesta la mitad por segundo.
5. **GitHub y Google Cloud.** Se corrige el flujo de despliegue: no se genera ni se almacena ninguna clave JSON en ninguna parte.
6. **Autenticación.** Un solo usuario, el propietario. Sin registro ni pantalla de consentimiento OAuth.
7. **Control de costos.** Precios reales, corte automático de presupuesto y el plazo de 90 días del crédito.

Todo lo demás del PRD original se conserva íntegro.

---

## 1. Resumen

AI Artist Universe Studio es una aplicación web mobile-first para crear y producir artistas musicales virtuales desde un iPhone.

Cada artista existe dentro de un **Universe** independiente que contiene su identidad, Artist Bible, personaje, vestuario, escenarios, música, perfil vocal, historias, canciones, imágenes, videoclips, Shorts, Reels, entrevistas, BTS, assets y Canon.

La infraestructura principal será Google Cloud:

- Gemini
- Gemini Image (los tres modelos)
- Lyria 3 Pro
- Veo 3.1 (los tres modelos)
- Cloud Text-to-Speech
- Cloud Run
- Firestore
- Cloud Storage
- Cloud Tasks / Pub/Sub
- FFmpeg en Google Cloud
- Secret Manager
- Cloud Logging / Monitoring

GitHub será el repositorio y sistema de versionado.

## 2. Objetivo del MVP

El MVP debe permitir, exclusivamente desde un iPhone:

1. Crear artistas y Universes.
2. Construir la Artist Bible.
3. Crear personajes, atuendos y locaciones.
4. Tener un Director/Producer desde la etapa musical.
5. Generar ideas, letras o utilizar letras proporcionadas por el usuario.
6. Generar canciones con Lyria 3 Pro.
7. Mantener la mayor consistencia vocal posible mediante un Voice Profile persistente en prompts.
8. Aprobar o regenerar cada etapa.
9. Crear historias y videoclips dirigidos por IA.
10. Crear personajes secundarios cuando el Director los requiera.
11. Crear storyboard.
12. Generar primero imágenes de referencia de cada escena.
13. Aprobar/regenerar imágenes antes de usar Veo.
14. Generar clips de video con Veo.
15. Aprobar/regenerar clips antes del ensamblaje.
16. **Elegir a mano, en cada paso, qué generador de imagen y qué generador de video utilizar.**
17. Ensamblar el videoclip en Google Cloud.
18. Generar versiones 16:9 y 9:16.
19. Generar Shorts, Reels, TikToks, BTS y entrevistas.
20. Entregar archivos finales listos para subir manualmente.

## 3. Principio fundamental

La aplicación **no** debe funcionar como un botón de "Generate Everything".

Debe funcionar como una producción creativa supervisada:

**La IA propone y produce. El usuario decide.**

Cada etapa importante tendrá:

- Approve
- Regenerate
- Edit
- Reject
- Continue

Ninguna etapa crítica debe avanzar automáticamente sin aprobación.

## 4. Decisión sobre identidad vocal

Para el MVP **NO se utilizará un proveedor externo de identidad vocal**.

No se incorporan inicialmente Kits, ACE Studio, Musicfy ni servicios equivalentes.

La voz cantada del artista se definirá mediante un **Voice Profile** persistente dentro de la Artist Bible y se incluirá en las instrucciones de Lyria.

Esto no garantiza una voz idéntica entre canciones. Es una limitación aceptada del MVP. Lyria acepta texto e imágenes de referencia, pero no audio de referencia, de modo que no existe forma de fijar una voz cantada. La limitación no afecta al género: el género que se pida es el que se genera.

Para el contenido hablado —entrevistas, BTS, diario del artista, anuncios— sí existe solución dentro de Google Cloud: **Chirp 3 Instant Custom Voice** en Cloud Text-to-Speech clona una voz a partir de una muestra de 10 segundos y devuelve una clave reutilizable, de modo que todo el contenido hablado suena idéntico siempre. Requiere solicitar acceso y grabar un consentimiento, ambos trámites.

La arquitectura debe permitir reemplazar posteriormente el Voice Engine sin rediseñar el resto del sistema.

## 5. Principio de costos

Google Cloud será la plataforma principal para reducir dependencias y costos externos.

No se pagarán planes anuales de servicios externos durante el MVP para resolver identidad vocal.

Los procesos caros, especialmente generación de video, deberán requerir aprobación previa y contar con control de consumo.

**El costo está concentrado casi por completo en los segundos de video que genera Veo.** Todo lo demás junto —imágenes, música, texto, cómputo, almacenamiento— rara vez pasa de $8 por canción. De ahí salen tres reglas:

1. **El video se genera siempre sin audio, en todos los formatos.** La pista musical viene de Lyria y la voz hablada de Chirp. Pagar el audio de Veo sería pagar dos veces por algo que se descarta en el montaje. Cuesta la mitad.
2. **El modelo lo elige el usuario en cada generación.** No hay modelo fijo en el código.
3. **Lo que se pueda reutilizar, se reutiliza.** El Director organiza el storyboard buscando reaprovechar tomas antes de generar nuevas.

## 6. iPhone First

El iPhone es el centro de control.

El usuario debe poder:

- Crear y editar Universes.
- Generar contenido.
- Escuchar canciones.
- Revisar imágenes.
- Revisar videos.
- Aprobar.
- Regenerar.
- Elegir el modelo de cada generación.
- Administrar Jobs.
- Descargar exports.

No debe ser necesario:

- Terminal local.
- Computadora.
- Renderizado local.
- Modelos locales.
- Mantener Safari abierto para que continúe una generación.

La aplicación debe ser una PWA mobile-first cuando sea viable.

## 7. Arquitectura

```text
                         iPHONE
                           |
                           v
                AI ARTIST UNIVERSE STUDIO
                           |
                           v
                      CLOUD RUN
                           |
                  GENERATION ORCHESTRATOR
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
       GEMINI          GEMINI IMAGE     LYRIA 3 PRO
       Director          Visuals          Music
          |                |                |
          +----------------+----------------+
                           |
                           v
                       VEO 3.1
                         Video
                           |
                           v
                  MEDIA ASSEMBLY ENGINE
                       FFmpeg
                           |
                           v
                    CLOUD STORAGE
                           |
                           v
                         iPHONE
```

## 8. Universe

Cada artista es un Universe aislado.

Contenido:

- Artist Bible
- Character Master
- Supporting Characters
- Wardrobe
- Locations
- Music Identity
- Voice Profile
- Songs
- Video Projects
- Storyboards
- Content
- Canon
- Drafts
- Assets
- Jobs
- Exports

Toda entidad debe estar vinculada a `universe_id`.

## 9. Artist Bible

### Identidad
- Nombre artístico
- Nombre ficticio opcional
- Edad aparente
- Origen
- Idiomas
- Personalidad
- Historia
- Público objetivo
- Temas recurrentes

### Identidad musical
- Género
- Subgéneros
- BPM
- Instrumentación
- Producción
- Estructuras
- Temas líricos
- Idioma
- Mood
- Características vocales

### Identidad visual
- Apariencia
- Estética
- Paleta
- Iluminación
- Fotografía
- Cinematografía
- Arquitectura
- Escenarios
- Motivos recurrentes
- Elementos prohibidos

### Comunicación
- Forma de hablar
- Humor
- Expresiones
- Estilo de entrevistas
- Temas recurrentes

### Preferencias de generación
- Modelo de imagen preferido
- Modelo de video preferido
- Resolución de trabajo
- Presupuesto

## 10. Voice Profile

Ejemplo:

```text
Female
Young adult
Warm mezzo-soprano
Breathy but clear
Slight natural rasp
Soft lower register
Airy upper register
Intimate delivery
Controlled vibrato
Emotional but restrained
Clear pronunciation
```

Este perfil se reutiliza en todas las generaciones musicales del artista.

Para la voz hablada se guarda además la clave de voz clonada de Chirp 3, en Secret Manager.

## 11. Director

El Director existe desde el principio.

Participa en:

- Concepto
- Género
- Canción
- Letra
- Hook
- Estructura
- Historia
- Videoclip
- Personajes
- Casting
- Locaciones
- Vestuario
- Storyboard
- Escenas
- Organización y reutilización de tomas
- Contenido promocional

Gemini implementará inicialmente este rol.

El Director puede analizar información disponible sobre tendencias y formatos para proponer conceptos con potencial de descubrimiento. Nunca debe prometer viralidad.

**El usuario puede modificar cualquier propuesta del Director.** Si el Director propone balada y el usuario quiere hip hop, el usuario cambia el género y el Director rehace la propuesta a partir de ese cambio. Si el usuario está de acuerdo, aprueba y se avanza.

## 12. Letra proporcionada por el usuario

El usuario puede subir o pegar una letra.

El Director:

1. Analiza tema y estructura.
2. Detecta hooks.
3. Propone género.
4. Propone BPM.
5. Propone interpretación.
6. Propone producción.
7. Presenta la propuesta.
8. Espera aprobación.

La letra no se modifica automáticamente sin aprobación.

## 13. Creación musical desde cero

El usuario puede proporcionar una idea.

El Director desarrolla:

- Concepto
- Título
- Hook
- Letra
- Género
- Estructura
- Producción
- Voice Profile
- Concepto visual

Cada etapa importante se aprueba antes de avanzar.

## 14. Music Production Workflow

```text
IDEA / LETRA
      |
      v
DIRECTOR
      |
      v
MUSIC CONCEPT
      |
      v
USER APPROVAL
      |
      v
LYRICS
      |
      v
USER APPROVAL
      |
      v
LYRIA 3 PRO
      |
      v
SONG VERSION
      |
      +---- REGENERATE
      |
      v
USER APPROVAL
      |
      v
SONG MASTER
```

Una canción rechazada no desencadena el videoclip.

**Modelo de música:** solo `lyria-3-pro`, que genera canciones completas de hasta 3 minutos a la duración solicitada. Los modelos `lyria-3` (sin «Pro») y `lyria-2` generan clips de 30 segundos y están excluidos del sistema: no aparecen en el selector y el orquestador tiene prohibido recurrir a ellos, tampoco como respaldo ante un fallo. Precio: $0,08 por canción. Los prompts van en inglés de Estados Unidos.

## 15. Song Object

Guardar:

- Song ID
- Universe ID
- Title
- Concept
- Lyrics
- Autor de la letra (usuario / IA / mixto)
- Music prompt
- Voice profile
- Genre
- BPM
- Mood
- Structure
- Lyria model/version
- Parameters
- Audio files
- Versions
- Approved master
- Cover
- Video project
- Associated content
- Metadata
- Status
- Version history
- Costo acumulado

## 16. Canon

Estados:

- DRAFT
- APPROVED
- REJECTED
- ARCHIVED

Los assets aprobados se convierten en Canon y se utilizan como contexto preferente y como imágenes de referencia en generaciones posteriores.

## 17. Character Department

El Director puede decidir que una producción necesita personajes adicionales.

Ejemplo:

```text
NOVA
+
PARTNER
+
FRIEND
+
STRANGER
```

Cada personaje tendrá:

- Identidad
- Edad aparente
- Apariencia
- Personalidad
- Vestuario
- Referencias
- Canon

Los personajes se crean antes de las escenas.

## 18. Character Master

Para cada personaje:

- Portrait
- Full body
- Profile
- Three-quarter
- Neutral expression
- Emotional expressions
- Relevant poses

El usuario aprueba el Character Master antes de utilizarlo como referencia.

Una vez aprobado, estas imágenes se adjuntan como referencia en toda generación posterior donde aparezca el personaje. Es lo que sostiene la consistencia visual, así que conviene generarlas con el modelo de mayor calidad. El usuario elige cuál.

## 19. Wardrobe

Categorías:

- Signature
- Casual
- Performance
- Interview
- Music Video
- Night
- Special

Cada outfit almacena:

- Nombre
- Descripción
- Imagen
- Piezas
- Accesorios
- Colores
- Uso
- Restricciones
- Estado

## 20. Locations

Biblioteca de:

- Apartment
- Studio
- Rooftop
- Street
- Backstage
- Concert stage
- Café
- Entornos ficticios

Cada ubicación almacena:

- Nombre
- Descripción
- Referencias
- Iluminación
- Hora
- Arquitectura
- Mood
- Canon status

## 21. Video Director Workflow

Después de aprobar la canción:

```text
SONG MASTER
     |
     v
DIRECTOR
     |
     v
VIDEO CONCEPT
     |
     v
STORY
     |
     v
CASTING
     |
     v
LOCATIONS
     |
     v
WARDROBE
     |
     v
STORYBOARD
```

El Director decide si el video será:

- Performance
- Narrative
- Cinematic
- Minimal
- Hybrid

## 22. Story

Cuando la canción tenga narrativa, el Director crea:

- Premise
- Beginning
- Development
- Conflict
- Climax
- Resolution

La historia debe relacionarse con la letra, el mood, la identidad del artista y el Universe.

## 23. Storyboard

Cada escena define:

- Scene ID
- Duration
- Song timestamp
- Characters
- Location
- Wardrobe
- Action
- Emotion
- Camera
- Lighting
- Environment
- Dialogue si aplica
- Visual objective
- Si la toma reutiliza material ya aprobado, y de qué escena

El usuario aprueba el storyboard antes de la generación masiva.

**Organización y reutilización.** Al armar el storyboard, el Director busca qué tomas puede reaprovechar antes de proponer generar nuevas: un estribillo que se repite, una locación que ya aparece, un plano que sirve con otro encuadre. Lo que no se puede reutilizar se genera de nuevo. El usuario puede forzar la generación de cualquier toma que el Director haya propuesto reutilizar, y al revés.

**Duración de las escenas.** Veo genera clips de 4, 6 u 8 segundos, y nada más. Ocho segundos es obligatorio si se quiere 1080p o usar imágenes de referencia, que es siempre el caso aquí. Por tanto las escenas se diseñan en bloques de 8 segundos.

## 24. Scene Image Generation

La generación de imágenes es obligatoria antes de Veo.

```text
Storyboard Scene
      |
      v
Gemini Image  (el usuario elige el modelo)
      |
      v
Scene Reference Image
      |
      +---- REGENERATE
      |
      v
USER APPROVAL
      |
      v
LOCK IMAGE
      |
      v
VEO
```

Una escena no entra a video hasta que su imagen esté aprobada.

**Modelos de imagen disponibles.** El usuario elige en cada generación:

| Modelo | Precio por imagen | Imágenes de referencia | Resoluciones |
|---|---|---|---|
| `gemini-3-pro-image` (Nano Banana Pro) | $0,134 (1K–2K) · $0,24 (4K) | 5 personajes · 6 objetos · 3 de estilo | 1K, 2K, 4K |
| `gemini-3.1-flash-image` (Nano Banana 2) | $0,067 (1K) · $0,101 (2K) · $0,151 (4K) | 4 personajes · 10 objetos | 512px, 1K, 2K, 4K |
| `gemini-3.1-flash-lite-image` | $0,034 (1K) | Sin referencia de personaje · 14 objetos | 1K |

**Imagen (Imagen 3 e Imagen 4) queda fuera del sistema.** Google apagó los endpoints de Imagen 4 el 17 de agosto de 2026, y ninguna versión de Imagen 4 aceptó imágenes de referencia, que es justo lo que se necesita para mantener al personaje consistente.

## 25. Scene Image Requirements

La imagen debe respetar:

- Character Master
- Supporting Character Master
- Wardrobe
- Location
- Artist Bible
- Storyboard
- Camera
- Lighting
- Mood

Guardar prompt, modelo utilizado y referencias empleadas.

## 26. Video Generation

Veo recibe:

- Imagen de escena aprobada
- Instrucciones de escena
- Referencias de personajes cuando estén soportadas
- Cámara
- Acción
- Duración
- Mood
- Contexto

Workflow:

```text
APPROVED IMAGE
      |
      v
VEO  (el usuario elige el modelo)
      |
      v
VIDEO CLIP
      |
      +---- REGENERATE
      |
      v
USER APPROVAL
      |
      v
LOCK CLIP
```

Un clip defectuoso se regenera antes del ensamblaje.

**Modelos de video disponibles.** El usuario elige en cada generación. Precio **por segundo de video generado** — la consola de Vertex rotula la unidad como «1 count», lo que se lee como «por video», pero no lo es: un clip de 8 segundos a $0,05 factura $0,40.

| Modelo | Precio por segundo, sin audio |
|---|---|
| `veo-3.1` · 1080p | $0,20 |
| `veo-3.1` · 4K | $0,40 |
| `veo-3.1-fast` · 1080p | $0,10 |
| `veo-3.1-fast` · 720p | $0,08 |
| `veo-3.1-lite` · 1080p | $0,05 |
| `veo-3.1-lite` · 720p | $0,03 |

**El audio de Veo se desactiva siempre**, en todos los formatos. La opción de generar con audio no se expone en ninguna pantalla. Activarlo duplicaría el precio por segundo para producir una pista que el ensamblaje descarta, porque el audio sale de Lyria y la voz hablada de Chirp.

**Otras restricciones de Veo:**

- Clips de 4, 6 u 8 segundos. Ocho es obligatorio para 1080p, 4K o imágenes de referencia.
- Hasta 3 imágenes de referencia por generación.
- Extensión de escena: +7 segundos por vez, hasta unos 148 segundos. `veo-3.1-lite` no la soporta.
- Relaciones de aspecto: 16:9 y 9:16.
- Solo se factura si el video se genera con éxito.

## 27. AI Producer

El Producer controla:

- Número de escenas
- Personajes
- Locaciones
- Imágenes necesarias
- Generaciones de video
- Reutilización de assets
- Complejidad
- Estimación de costo

Antes de una producción costosa debe presentar un Production Plan.

## 28. Production Plan

Ejemplo:

```text
PROJECT:
NOVA — SONG 001

VIDEO TYPE:
Narrative

SCENES:
24

CHARACTERS:
3

LOCATIONS:
5

WARDROBE:
4

SCENE IMAGES:
21   (modelo: gemini-3.1-flash-image 1K)

VIDEO CLIPS:
18   (modelo: veo-3.1-fast 1080p, sin audio)

TOMAS REUTILIZADAS:
6

VERTICAL DERIVATIVES:
4

ESTIMATED GENERATION COST:
$21,40

GASTADO EN ESTE ARTISTA:
$34,10

CRÉDITO RESTANTE:
$248,50   ·   caduca en 63 días
```

El usuario puede:

- Approve
- Modify
- Cancel

## 29. Media Assembly Engine

No es un servicio externo.

Es un componente de nuestro sistema ejecutado en Google Cloud.

Inicialmente:

- Cloud Run Jobs
- FFmpeg
- Cloud Storage

Funciones:

- Mezclar audio
- Superponer voz hablada de Chirp cuando corresponda
- Ensamblar video
- Cortar clips
- Sincronizar escenas
- Transiciones
- Captions
- Versiones
- Render final

## 30. Master Audio

El videoclip siempre utiliza el audio aprobado.

```text
LYRIA 3 PRO
  |
  v
SONG
  |
  v
APPROVE
  |
  v
MASTER AUDIO
```

## 31. Video Master

```text
MASTER AUDIO
+
APPROVED SCENE CLIPS
+
STORYBOARD ORDER
+
EDITING INSTRUCTIONS
       |
       v
CLOUD MEDIA ASSEMBLY
       |
       v
FINAL VIDEO
```

## 32. Formatos

- YouTube: 16:9
- TikTok: 9:16
- Instagram Reels: 9:16
- Facebook Reels: 9:16
- YouTube Shorts: 9:16

Las versiones verticales se derivan del master por reencuadre en FFmpeg y no tienen costo de generación.

## 33. Content Studio

A partir de una canción/video aprobado:

- Shorts
- Reels
- TikToks
- Teasers
- BTS
- Interviews
- Artist announcements
- Photoshoots
- Promotional images
- Lyric clips

Todo debe respetar el Canon.

## 34. BTS

Tipos:

- Recording session
- Music video set
- Rehearsal
- Dressing room
- Artist diary
- Preparation
- Performance preparation

Debe conservar continuidad visual.

El audio es voz de Chirp superpuesta sobre video generado sin audio.

## 35. Interviews

Gemini puede generar:

- Preguntas
- Respuestas
- Entrevistas cortas
- Rapid questions
- Song interviews
- Artist introductions

La personalidad viene de la Artist Bible.

El audio es voz de Chirp superpuesta sobre video generado sin audio.

## 36. Aprobación humana

Toda etapa crítica tendrá:

- APPROVE
- REGENERATE
- EDIT
- REJECT
- SAVE TO CANON

Nada crítico avanza automáticamente.

## 37. Generation Queue

Estados:

- QUEUED
- PROCESSING
- READY
- APPROVED
- REJECTED
- FAILED
- CANCELLED

Los Jobs continúan en Google Cloud aunque el usuario cierre el iPhone.

**Política de fallo:** un Job fallido se reintenta con el mismo modelo que se solicitó. El sistema nunca sustituye el modelo pedido por otro distinto ni de menor capacidad.

## 38. Mobile UI

### Home
- Universes
- Recent projects
- Active jobs
- Pending approvals
- Crédito restante y días que faltan para que caduque

### Universe
- Artist
- Bible
- Music
- Characters
- Wardrobe
- Locations
- Videos
- Content
- Canon

### Production

Mostrar:

```text
Concept
↓
Music
↓
Story
↓
Characters
↓
Storyboard
↓
Images
↓
Video
↓
Assembly
↓
Export
```

Cada etapa muestra status, acciones disponibles, modelo en uso y costo acumulado.

## 39. Mobile UX

- Portrait-first
- Botones grandes
- Tarjetas
- Sin tablas anchas
- Sin hover
- Bottom sheets
- Reproducción de audio/video
- Selector de archivos de iOS
- Descarga a Files
- PWA cuando sea viable

El selector de modelo es un bottom sheet accesible desde cualquier pantalla de generación, con el precio de cada opción visible en la lista.

## 40. GitHub

GitHub será:

- Repositorio
- Versionado
- Issues
- Pull Requests
- CI/CD
- Documentación

El desarrollo debe favorecer:

```text
GitHub
   ↓
Cloud Build
   ↓
Cloud Run
```

sin depender de una computadora local.

**Autenticación entre servicios: sin claves JSON en ninguna parte.**

- **La app en Cloud Run llamando a Vertex AI, Firestore, Storage y Text-to-Speech.** Cloud Run se ejecuta con una cuenta de servicio adjunta, y las librerías cliente de Google toman esa identidad solas mediante Application Default Credentials. No hay archivo de credenciales, y tampoco se guarda la clave en una variable de entorno: eso dejaría una credencial en la configuración del servicio cuando el runtime ya tiene identidad propia. Basta con conceder a esa cuenta los roles de Vertex AI User, Firestore User, Storage Object Admin y Cloud TTS User.

- **Despliegue.** Un disparador de **Cloud Build conectado al repositorio de GitHub**: la conexión la gestiona Google con su app de GitHub, Cloud Build corre con su propia cuenta de servicio, y un push a `main` despliega. Sin claves y operable desde el iPhone. Para despliegues puntuales, `gcloud run deploy --source .` desde Cloud Shell en la app de Google Cloud para iOS.

- **Regla del proyecto:** no se genera, no se descarga y no se almacena ninguna clave JSON de cuenta de servicio en ningún punto del sistema. Si existe alguna de un flujo anterior, se elimina desde IAM. Secret Manager guarda únicamente la clave de voz clonada de Chirp, que es un identificador de la API y no una credencial de acceso a la cuenta.

## 41. Google Cloud

### Cloud Run
Frontend, backend, orchestrator, workers/jobs.

### Firestore
Universes, Bibles, Characters, Wardrobe, Locations, Songs, Scenes, Content, Jobs, Canon, registro de gasto.

### Cloud Storage
Images, audio, video, references, exports.

### Vertex AI
Gemini, Gemini Image, Lyria 3 Pro, Veo 3.1.

### Cloud Text-to-Speech
Chirp 3 Instant Custom Voice para el contenido hablado.

### Cloud Tasks / Pub/Sub
Procesamiento asíncrono.

### Secret Manager
Clave de voz clonada.

### Cloud Logging / Monitoring
Errores y diagnóstico.

### IAM
Acceso del propietario al servicio.

### Autenticación de usuario
La aplicación tiene un solo usuario: el propietario. No hay registro, ni invitaciones, ni roles, ni recuperación de contraseña. El acceso se controla con IAM sobre el servicio de Cloud Run, contra la cuenta de Google del propietario. Esto elimina la necesidad de construir login dentro de la app y **elimina también la pantalla de consentimiento OAuth**, que es uno de los pocos pasos que obligarían a usar una computadora. Las reglas de Firestore se reducen a permitir únicamente al propietario. `universe_id` se conserva en todas las entidades, no por multiusuario, sino porque habrá varios artistas y cada uno debe estar aislado.

### Registro de modelos
Los modelos no se escriben como constantes en el código. Viven en un documento de configuración en Firestore con su nombre, precio, capacidades y estado. La app lee de ahí para llenar el selector y para estimar costos. Cuando Google apague o añada un modelo —como pasó con Imagen 4, Veo 3 y Veo 2 este mismo año— se edita ese documento y no hay que tocar código ni volver a desplegar.

## 42. Generation Orchestrator

Responsabilidades:

1. Recibir solicitud, con clave de idempotencia para que un error de red no genere dos veces.
2. Identificar Universe.
3. Verificar presupuesto disponible.
4. Recuperar Artist Bible.
5. Recuperar Canon.
6. Recuperar assets y referencias.
7. Determinar rol creativo.
8. Resolver qué modelo usar: el que eligió el usuario, si no el preferido de la Artist Bible.
9. Crear instrucciones estructuradas.
10. Ejecutar modelo.
11. Crear Job.
12. Registrar el consumo y su costo.
13. Guardar resultado.
14. Esperar aprobación.
15. Continuar cuando corresponda.

## 43. Roles creativos

Inicialmente pueden existir como roles dentro de un único Orchestrator:

- Director
- Music Director
- Producer
- Creative Director
- Casting Director
- Cinematographer
- Editor

No es necesario construir siete agentes independientes para el MVP.

## 44. Cost Control

- Estimaciones cuando estén disponibles.
- Confirmación antes de procesos costosos.
- Número de variantes configurable.
- Sin regeneraciones automáticas ilimitadas.
- Reutilización de assets aprobados.
- Protección contra duplicados por errores de red.
- Registro de consumo.
- Budget alerts de Google Cloud.
- **Corte automático al alcanzar el presupuesto**: los trabajos nuevos se rechazan, no solo se avisa.
- **Contador de gasto visible en la misma pantalla que el botón de regenerar.**

### El plazo del crédito

El crédito de bienvenida de $300 de Google Cloud **caduca a los 90 días del alta, se use o no**. Si se agota por gasto o por calendario, la cuenta de prueba se cierra y los proyectos se detienen, con 30 días de gracia para pasar a cuenta de pago. El Home muestra los días restantes.

El crédito no cubre la Gemini API de AI Studio ni modelos de socios en Vertex. Los modelos propios de Google —Gemini, Veo, Lyria— sí.

### Costo de referencia

Videoclip de 3 minutos, 24 escenas, con `gemini-3.1-flash-image` y `veo-3.1-fast` 1080p sin audio, contando dos intentos por pieza:

| Partida | Cálculo | Costo |
|---|---|---|
| Canción | 15 intentos × $0,08 | $1,20 |
| Imágenes de escena | 42 × $0,067 | $2,81 |
| Video | 288 s × $0,10 | $28,80 |
| Director (Gemini) | ~1M tokens | $2,00 |
| Ensamblaje y almacenamiento | Cloud Run Jobs + GCS | $1,00 |
| **Total por canción** | | **≈$35,80** |

Con `veo-3.1-lite` a 720p el mismo videoclip baja a unos **$15**. Con `veo-3.1` a 1080p sube a unos **$65**. De ahí que el selector de modelo sea la palanca principal.

## 45. Regeneración granular

Si falla una parte, solo se regenera esa parte:

- Canción → canción
- Personaje → personaje
- Outfit → outfit
- Imagen → imagen
- Clip → clip
- Ensamblaje → render

No se regenera toda la producción por un error localizado.

## 46. Provenance

Cada asset almacena:

- Universe ID
- Parent ID
- Model
- Model version
- Prompt
- References
- Parameters
- Timestamp
- Output
- Status
- Version
- Costo
- Aportación del usuario: qué escribió, editó, aprobó o rechazó

## 47. Firestore conceptual

```text
users
config
  └── modelos disponibles

universes
  |
  +-- artist_bible
  +-- characters
  +-- wardrobe
  +-- locations
  +-- songs
  +-- video_projects
  +-- scenes
  +-- images
  +-- videos
  +-- content
  +-- canon
  +-- jobs
  +-- gasto
  +-- exports
```

## 48. Cloud Storage

```text
/universes/{universe_id}/
  /character/
  /wardrobe/
  /locations/
  /songs/{song_id}/
  /video-projects/{project_id}/
  /scenes/{scene_id}/
  /content/
  /references/
  /exports/
  /temp/
```

## 49. Export Package

```text
ARTIST/
  SONG_001/
    AUDIO/
      master.wav
      master.mp3
    COVER/
      cover.jpg
    MUSIC_VIDEO/
      youtube_16x9.mp4
      vertical_9x16.mp4
    SHORTS/
      short_01.mp4
      short_02.mp4
      short_03.mp4
    BTS/
      bts_01.mp4
    INTERVIEWS/
      interview_01.mp4
    METADATA/
      metadata.json
      song_info.txt
```

Todo debe poder descargarse desde el iPhone.

## 50. MVP: IN SCOPE

1. Authentication
2. Universe Manager
3. Artist Bible
4. Canon
5. Character Studio
6. Wardrobe
7. Locations
8. Director
9. Music Studio
10. Lyria 3 Pro integration
11. Image Studio
12. Story/Storyboard
13. Veo 3.1 integration
14. Selector manual de modelo de imagen y de video
15. Scene approval
16. Media Assembly
17. Content Studio
18. Voz hablada con Chirp 3
19. Jobs
20. Export
21. Mobile PWA
22. GitHub/Cloud deployment

## 51. MVP: OUT OF SCOPE

- Distribución automática a Spotify
- Publicación automática en YouTube
- Publicación automática en TikTok
- Publicación automática en Instagram
- Publicación automática en Facebook
- Royalty accounting
- Marketplace
- Usuarios externos
- Team collaboration
- CRM
- Merchandising
- Publicidad
- Analytics avanzado
- Record-label management
- Proveedor externo de identidad vocal cantada
- Aplicación nativa iOS

## 52. Desarrollo por fases

### Fase 0 — Infraestructura
GitHub, Google Cloud, billing, budgets con corte, Firestore, Storage, Cloud Run, acceso IAM del propietario, CI/CD con Cloud Build, documento de modelos disponibles.

### Fase 1 — Universe
Universe, Artist Bible, Canon, versioning.

### Fase 2 — Personaje
Character Master, aprobación, Wardrobe, Locations.

### Fase 3 — Director + Música
Director, letras, letra propia, Music Concept, Voice Profile, Lyria 3 Pro, aprobación/regeneración.

### Fase 4 — Video Pre-production
Historia, casting, personajes secundarios, locaciones, vestuario, storyboard.

### Fase 5 — Imágenes
Los tres modelos Gemini Image, selector, referencias de escenas, aprobación/regeneración.

### Fase 6 — Video
Los tres modelos Veo 3.1, selector, clips, revisión, regeneración, aprobación.

### Fase 7 — Assembly
FFmpeg, audio, video, transiciones, captions, 16:9, 9:16.

### Fase 8 — Content
Chirp 3, Shorts, Reels, TikTok, BTS, entrevistas, teasers.

### Fase 9 — Export
Packages, metadata, descarga y compatibilidad con Files de iOS.

## 53. Acceptance Test

Todo exclusivamente desde un iPhone:

1. Crear Universe.
2. Crear artista.
3. Crear Artist Bible.
4. Crear Character Master.
5. Aprobar personaje.
6. Crear atuendo.
7. Crear locación.
8. Crear concepto musical.
9. Proporcionar letra o permitir que Gemini cree una.
10. Cambiar el género que propuso el Director y ver que la propuesta se rehace.
11. Aprobar letra.
12. Generar canción con Lyria 3 Pro a la duración pedida.
13. Comprobar que no existe ninguna opción de generar clips de 30 segundos, ni siquiera tras un fallo.
14. Regenerar si no gusta.
15. Aprobar canción.
16. Solicitar propuesta de videoclip al Director.
17. Aprobar historia.
18. Crear personajes secundarios si son necesarios.
19. Aprobar personajes.
20. Aprobar storyboard, incluyendo las tomas que el Director propone reutilizar.
21. Elegir el modelo de imagen y generar las imágenes de escena.
22. Cambiar el modelo de imagen en una generación concreta.
23. Regenerar imágenes defectuosas.
24. Aprobar imágenes.
25. Elegir el modelo de video y generar los clips con Veo.
26. Cambiar el modelo de video en una generación concreta.
27. Comprobar en los logs que ninguna llamada a Veo pidió audio.
28. Regenerar clips defectuosos.
29. Aprobar clips.
30. Ensamblar videoclip en Google Cloud.
31. Generar 16:9.
32. Generar 9:16.
33. Crear Shorts/Reels/BTS/entrevista.
34. Aprobar contenido.
35. Comparar el costo real con el estimado.
36. Exportar.
37. Descargar desde iPhone.

Si cualquiera de estos pasos requiere una computadora, el MVP no cumple.

## 54. Definición final

AI Artist Universe Studio es un estudio creativo virtual controlado desde un iPhone.

No es un generador automático de contenido.

Es una producción supervisada.

La IA funciona como un equipo creativo: Director, Productor, Director Musical, Director Creativo, Casting, Cinematografía y Edición, inicialmente implementados mediante roles dentro de un Generation Orchestrator.

El sistema construye primero la idea, después la canción, después la producción visual, después los personajes y referencias, después las imágenes, después el video y finalmente el ensamblaje.

Cada etapa puede ser aprobada o regenerada, y en cada generación el usuario elige con qué modelo trabajar.

Todo el procesamiento pesado ocurre en Google Cloud.

La música se genera exclusivamente con Lyria 3 Pro, en canciones completas y a la duración solicitada. El video se genera siempre sin audio, porque la pista sale de Lyria y la voz hablada de Chirp.

La identidad vocal cantada perfecta queda fuera del MVP. Lyria utiliza un Voice Profile persistente para intentar mantener la mayor consistencia posible, y la arquitectura permitirá incorporar posteriormente una solución dedicada de voz si el proyecto comienza a generar ingresos suficientes para justificarla. La identidad vocal hablada sí está resuelta con Chirp 3.

El objetivo del MVP no es crear una compañía discográfica.

El objetivo es crear una herramienta capaz de producir, desde un iPhone, un artista virtual coherente y un lanzamiento musical completo de principio a fin.
