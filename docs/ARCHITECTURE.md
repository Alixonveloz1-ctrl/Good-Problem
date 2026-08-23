# Arquitectura

Cómo está construido AI Artist Universe Studio y por qué está construido así.
Complementa el [PRD v2.1](PRD_v2.1_AI_Artist_Universe_Studio.md); donde el PRD
dice *qué*, esto dice *dónde*.

---

## 1. Forma general

```text
                         iPHONE  (Safari / PWA)
                            |
                            v
                    Identity Aware Proxy
                            |
                            v
              CLOUD RUN  ·  un solo servicio
        API + worker de jobs + los estáticos de la PWA
                            |
                 GENERATION ORCHESTRATOR
                            |
        +-------------------+-------------------+
        |          |            |          |    |
        v          v            v          v    v
     GEMINI   GEMINI IMAGE   LYRIA 3 PRO  VEO 3.1  CHIRP 3
    Director    Visuales       Música      Video    Voz
        |          |            |          |    |
        +-------------------+-------------------+
                            |
                            v
              MEDIA ASSEMBLY ENGINE  (Cloud Run Job + FFmpeg)
                            |
                            v
                      CLOUD STORAGE
                            |
                            v
                         iPHONE
```

Un solo servicio de Cloud Run sirve la API, ejecuta los jobs y entrega la PWA.
Un solo servicio significa una sola frontera de IAM que proteger, un solo
despliegue y ninguna configuración de CORS.

## 2. Las capas del backend

| Capa | Carpeta | Qué contiene | Qué no |
|---|---|---|---|
| Dominio | `app/domain/` | Entidades, registro de modelos, precios, invariantes | No sabe de HTTP ni de Google Cloud |
| Proveedores | `app/providers/` | Vertex AI, Chirp, Storage, Secret Manager | No decide *cuándo* generar |
| Servicios | `app/services/` | Presupuesto, jobs, aprobaciones, contexto, plan, exports | No llama a modelos |
| Orquestador | `app/orchestrator/` | Las 15 responsabilidades del PRD 42, los handlers | No conoce FastAPI |
| Routers | `app/routers/` | La API HTTP | No contiene reglas de negocio |

La dependencia va siempre hacia abajo. `guards.py` no importa nada del sistema,
lo cual es deliberado: es el archivo que no debe poder romperse desde fuera.

## 3. Los invariantes

`app/domain/guards.py` codifica las cuatro correcciones de la v2.1. Están en
código y no en configuración porque el registro de modelos vive en Firestore y
es editable desde el móvil: si las reglas estuvieran allí, una edición podría
deshacerlas.

`ModelRegistry.__init__` valida el documento contra `BANNED_MODEL_IDS` al
cargarlo. Añadir `lyria-3` al documento de Firestore no lo activa; lo mueve a la
lista de excluidos con el motivo.

**Prueba de que la regla del audio se cumple.** Cada petición a Vertex se
registra antes de salir del proceso, en `providers/vertex.py:CallLog`, y se
consulta en `GET /api/diagnostics/vertex-calls?prefix=veo`. El paso 27 del
acceptance test («comprobar en los logs que ninguna llamada a Veo pidió audio»)
no depende de revisar el código: se comprueba con una petición.

## 4. El Generation Orchestrator

Todo pasa por `submit` y luego por `run_job`, en ese orden.

```text
submit(GenerationRequest)
  1. identificar Universe
  2. resolver modelo:   usuario > preferencia de la Bible > registro
  3. estimar costo
  4. comprobar presupuesto           <- corte duro, aquí se rechaza
  5. clave de idempotencia
  6. crear Job (QUEUED)
  7. encolar

run_job(universe_id, job_id)
  1. Job -> PROCESSING
  2. recuperar Artist Bible, Canon, referencias
  3. determinar rol creativo
  4. construir instrucciones estructuradas
  5. ejecutar el modelo
  6. registrar consumo y costo real
  7. guardar resultado -> Job READY
  8. esperar aprobación humana
```

El Job queda en `READY`, nunca en `APPROVED`. Solo una acción del usuario lo
mueve más allá.

**La cola.** Cloud Tasks empuja a `POST /api/internal/jobs/run` del mismo
servicio, de modo que un job sigue corriendo aunque Safari se cierre. Sin cola
configurada el job corre en un hilo del proceso, que es lo que necesitan un
portátil y la suite de tests.

**Idempotencia.** Cada petición de generación lleva una clave. La primera que
llega gana; las siguientes devuelven el mismo Job. Una conexión que se cae en el
metro no factura dos veces un video.

## 5. Las puertas de aprobación

Reunidas en `app/services/approvals.py` para que se puedan leer como una lista:

| Puerta | Regla |
|---|---|
| `assert_lyrics_approved` | Lyria no se llama hasta que la letra esté aprobada |
| `assert_song_approved` | Una canción rechazada no desencadena el videoclip |
| `assert_storyboard_approved` | La generación masiva de imágenes espera al storyboard |
| `assert_scene_image_locked` | Una escena no entra a Veo sin imagen aprobada y bloqueada |
| `assert_scene_not_reused` | Una toma marcada para reutilizar no se regenera, salvo que el usuario lo fuerce |
| `assert_ready_for_assembly` | El montaje espera a todos los clips y al master de audio |

## 6. Consistencia visual

Es el problema difícil del producto, y se resuelve con referencias, no con
suerte:

1. El **Character Master** se genera una vez, con el modelo que el usuario
   elija, y se aprueba.
2. Al aprobarlo, sus imágenes pasan a `reference_image_paths`.
3. `services/context.py:load_scene_context` recoge esas rutas, más la locación y
   el vestuario aprobados, en cada generación donde aparezca el personaje.
4. `gemini_image.check_references` rechaza la petición si el modelo elegido no
   puede sostener esas referencias, en vez de descartarlas en silencio. Por eso
   `gemini-3.1-flash-lite-image` aparece en el selector con la etiqueta «Sin
   referencia de personaje».

Veo acepta hasta 3 imágenes de referencia, así que el contexto se ordena de más
a menos identidad: personajes primero, después la locación.

## 7. Reutilización de tomas

El Director marca en el storyboard qué planos reaprovechan material ya aprobado.
Una escena reutilizada:

- no genera imagen ni clip (`assert_scene_not_reused`);
- en el montaje apunta al clip de la escena original
  (`assembly/engine.py:build_edl`);
- se puede forzar a generar de nuevo desde la escena, y al revés.

El Production Plan cuenta las tomas reutilizadas por separado, porque son la
diferencia entre un videoclip de $35 y uno de $50.

## 8. Costos

`domain/pricing.py` es la única aritmética de dinero del sistema, y sus
funciones están contrastadas en `tests/test_invariants.py` contra la tabla de
referencia del PRD 44:

| Partida | Cálculo | Resultado |
|---|---|---|
| Canción | 15 × $0,08 | $1,20 |
| Imágenes | 42 × $0,067 | $2,81 |
| Video | 288 s × $0,10 | $28,80 |
| Director | ~1M tokens | ~$2,13 |

**El estudio no lleva cuentas ni corta nada.** Es una desviación deliberada del
PRD 44, pedida por el propietario: el gasto acumulado, la cuenta atrás del
crédito y el corte automático se quitaron porque esa información se consulta en
la consola de Google Cloud. No existe `BudgetService`, ni libro de gasto, ni
`/api/budget`, ni techo por artista.

Los precios siguen sirviendo para dos cosas, ambas *antes* de gastar:

- el selector de modelo, que muestra lo que costará esa generación concreta;
- el Production Plan, que estima una producción entera antes de lanzarla.

Y cada Job guarda `estimated_cost_usd` y `actual_cost_usd`, que van también a la
procedencia del asset (PRD 46). Eso es trazabilidad —de dónde salió esta pieza y
qué costó— no un contador: ninguna pantalla los muestra y nada los suma.

## 9. Ensamblaje

El Media Assembly Engine no es un servicio externo: es un componente de este
sistema que corre en Google Cloud.

- `assembly/ffmpeg_cmds.py`: funciones puras que devuelven líneas de comando, lo
  que permite verificarlas sin FFmpeg instalado. El montaje puede ir a corte
  seco o con fundidos encadenados; cada fundido solapa dos planos, así que la
  imagen sale más corta que la suma de los clips y el resultado dice cuánto.
- `assembly/engine.py`: resuelve la línea de tiempo, calcula offsets y escribe
  la lista de montaje (EDL) en Storage; después codifica.
- `assembly/job.py`: punto de entrada del Cloud Run Job.

En dry run el motor hace todo su trabajo real —resolver reutilizaciones,
ordenar, calcular— salvo la codificación, y deja la EDL escrita. Lo que no hace
es fingir que produjo un video.

La versión 9:16 se deriva del master 16:9 por recorte central y escalado. No
cuesta nada generarla.

## 10. Alargar una toma

Veo genera 8 segundos y para. Para un plano continuo mas largo existe la
extension: se le pasa el clip ya generado y continua 7 segundos mas, hasta unos
148 s. `veo-3.1-lite` no la soporta.

Tres limites de la API que conviene tener presentes, verificados en la
documentacion de Google y no deducidos del PRD:

- **la peticion no acepta imagenes de referencia.** Solo recibe el video
  anterior y un texto, y deduce quien es el personaje del ultimo segundo de ese
  clip. Si la toma termina sin verse la cara, Veo se la inventa;
- **la salida es siempre 720p**, aunque el clip original sea 1080p o 4K. Por eso
  `start_extension` fuerza esa resolucion en vez de repetir la del clip;
- cada continuacion deja la escena **pendiente de aprobar otra vez**: dura mas y
  llega con menos nitidez, asi que hay que volver a mirarla.

La pantalla de la escena dice las tres cosas antes de que se pulse el boton.

## 11. Content Studio

Dos caminos distintos, porque cuestan cosas distintas:

- **Shorts, Reels, TikToks, teasers y lyric clips** se recortan del master
  aprobado (`engine.cut_short`). No hay generación, así que no hay costo.
- **BTS, entrevistas y anuncios** necesitan material propio y siguen la misma
  regla que una escena: imagen primero, después Veo sin audio
  (`_handle_content_video`), y por último la voz de Chirp encima
  (`engine.mix_content`). Cuando la pieza pertenece a una canción, el master
  aprobado entra como cama de música por debajo de la voz.

Los tres trabajos que no llaman a ningún modelo —`assembly`, `cut` y `mix`—
pasan por `submit_local`, que salta la resolución de modelo pero crea el mismo
Job que ve el teléfono.

## 12. Autenticación

Una sola persona usa esto, así que no hay registro, ni roles, ni recuperación de
contraseña, ni pantalla de consentimiento OAuth: nada que obligue a sacar una
computadora.

El acceso se controla fuera de la aplicación: el servicio de Cloud Run exige
autenticación e Identity Aware Proxy delante solo deja pasar a la cuenta del
propietario. `app/auth.py` lee la cabecera que IAP inyecta y la contrasta con
`AAUS_OWNER_EMAIL`; es la segunda cerradura, no la primera.

**IAP hace falta.** Un servicio de Cloud Run con `--no-allow-unauthenticated`
espera un token Bearer que Safari no envía por sí solo. IAP es lo que convierte
la sesión de Google del navegador en una petición autorizada. Es el único punto
donde el PRD necesita un matiz: la idea de «solo IAM» es correcta, pero en la
práctica se implementa con IAM *más* IAP.

## 13. Almacenamiento

Firestore para documentos, Cloud Storage para binarios, ambos detrás de una
interfaz pequeña (`db/client.py`, `providers/storage.py`) con una
implementación en memoria y otra en disco. Eso es lo que permite que la suite de
tests recorra la producción entera en menos de un segundo y sin red.

Toda entidad lleva `universe_id`. No por multiusuario, sino porque habrá varios
artistas y cada uno debe estar aislado.
