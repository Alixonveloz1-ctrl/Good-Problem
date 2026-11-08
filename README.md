# AI Artist Universe Studio

Estudio creativo virtual para producir artistas musicales completos desde un
iPhone. **La IA propone y produce. El usuario decide.**

Implementación del [PRD v2.1](docs/PRD_v2.1_AI_Artist_Universe_Studio.md).

---

## Qué hace

Cada artista vive en un **Universe** aislado: identidad, Artist Bible,
personaje, vestuario, escenarios, música, perfil vocal, historias, canciones,
imágenes, videoclips, Shorts, BTS, entrevistas y Canon.

El recorrido completo, sin tocar una computadora:

```
Concepto → Música → Historia → Personajes → Storyboard
        → Imágenes → Video → Ensamblaje → Export
```

Ninguna etapa avanza sola. Cada una tiene Approve, Regenerate, Edit, Reject y
Save to Canon.

Lo que decide el equipo creativo no se le pregunta al usuario. El **Editor**
decide cómo se corta el videoclip —corte seco o transición en cada unión— a
partir del storyboard y de la canción, y el usuario aprueba el resultado, no
cada decisión de montaje.

Todos los planos duran **8 segundos** y salen de una imagen aprobada. Veo puede
continuar un clip ya generado, pero esa función está fuera del sistema: no
acepta las fotos del personaje, devuelve 720p, y no dejaría ninguna imagen que
aprobar antes de gastar.

## Las cuatro reglas que sostienen el sistema

Están en el código, no solo en el documento. Viven en
[`backend/app/domain/guards.py`](backend/app/domain/guards.py) y no se pueden
desactivar editando la configuración.

| Regla | Por qué | Dónde se comprueba |
|---|---|---|
| La música solo llega a `lyria-3-pro` | `lyria-3` y `lyria-2` hacen clips de 30 s, no canciones. Prohibidos también como respaldo tras un fallo | `assert_music_model` |
| Veo se llama siempre con el audio desactivado | La pista sale de Lyria. Activarlo costaría el doble por segundo para producir algo que el montaje tira | `enforce_video_audio_disabled` |
| Clips de 4, 6 u 8 s, y 8 obligatorio con 1080p, 4K o imágenes de referencia | Es lo único que Veo acepta, y aquí siempre hay imágenes de referencia | `resolve_clip_duration` |
| Un reintento usa el modelo que se pidió | El sistema nunca sustituye por otro distinto ni de menor capacidad | `assert_same_model_on_retry` |

Además: **el video se factura por segundo.** La consola de Vertex rotula la
unidad como «1 count», que se lee como «por video», pero no lo es. Un clip de
8 s a $0,05 factura $0,40. Toda la aritmética está en
[`pricing.py`](backend/app/domain/pricing.py) y contrastada con los números del
propio PRD. Por eso el selector muestra lo que cuesta el clip entero, no el
precio por segundo.

## El dinero se mira en Google Cloud

**Apartado del PRD a petición del propietario.** El §44 pedía un contador de
gasto dentro de la app, la cuenta atrás de los 90 días del crédito y un corte
automático al llegar al presupuesto. Nada de eso existe: el estudio no lleva
cuentas ni frena ninguna generación. El gasto se consulta en la consola de
Google Cloud, y los avisos de presupuesto se configuran allí
(los avisos de presupuesto se configuran en la consola de facturación).

Lo que sí queda es lo que cuesta cada cosa **antes** de lanzarla: el precio de
cada opción en el selector de modelo y la estimación del Production Plan. Y cada
generación deja registrado lo que costó dentro de su Job y de la procedencia del
asset (PRD 46), que es trazabilidad, no un contador.

El riesgo asumido: aquí cada generación es un botón que se pulsa a mano, no hay
ningún «generar todo», así que no hay forma de que un bucle se dispare solo.

## Modelos

No son constantes del código. Viven en un documento de Firestore
(`config/models`), sembrado desde
[`backend/seed/model_registry.json`](backend/seed/model_registry.json). Cuando
Google apague o añada un modelo se edita ese documento: no hay que tocar código
ni volver a desplegar.

| Tipo | Modelos | Precio |
|---|---|---|
| Texto | `gemini-3-pro` | ~$2 por millón de tokens |
| Imagen | `gemini-3-pro-image`, `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image` | $0,034 – $0,24 por imagen |
| Música | `lyria-3-pro` | $0,08 por canción |
| Video | `veo-3.1`, `veo-3.1-fast`, `veo-3.1-lite` | $0,03 – $0,40 **por segundo** |

El usuario elige modelo y variante **en cada generación**, desde un bottom sheet
con el precio de cada opción a la vista.

## Estructura

```
backend/
  app/
    domain/        guards, registro de modelos, precios, entidades
    orchestrator/  el Generation Orchestrator y los handlers por tipo
    providers/     Vertex AI (REST + ADC) y Storage
    services/      presupuesto, jobs, aprobaciones, contexto, plan, exports
    routers/       la API HTTP
    assembly/      Media Assembly Engine (FFmpeg, dentro del servicio)
  seed/            documento inicial del registro de modelos
  tests/           el acceptance test del PRD, extremo a extremo
frontend/          PWA mobile-first (React + Vite)
infra/             provisión de Google Cloud, sin ninguna clave JSON
docs/              PRD, arquitectura y despliegue
```

## Desarrollo local

Todo funciona sin proyecto de Google Cloud: base de datos en memoria, archivos
en disco y proveedores en **dry run**, que nunca llaman a una API de pago.

```bash
# Backend
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/python -m uvicorn app.main:app --reload --port 8080

# Frontend (otra terminal)
cd frontend
npm ci && npm run dev        # http://localhost:5173

# Tests
cd backend && ./.venv/bin/python -m pytest -q
```

`AAUS_DRY_RUN` es `true` por defecto **a propósito**: un despliegue mal
configurado no puede gastar dinero por accidente. Producción lo pone en `false`
de forma explícita.

## Despliegue

**[▶ Abrir en Cloud Shell](https://shell.cloud.google.com/cloudshell/editor?cloudshell_git_repo=https%3A%2F%2Fgithub.com%2FAlixonveloz1-ctrl%2FGood-Problem)**
descarga el proyecto solo. Después, dentro de Cloud Shell:

```bash
./setup.sh
```

El script no pide argumentos: toma el proyecto y la cuenta de Cloud Shell, monta
todo, publica la aplicación y al final imprime el único paso que queda, con los
enlaces exactos. Volver a ejecutarlo es seguro y no pierde nada de lo instalado.

El login lo monta también él: activa Firebase sobre el mismo proyecto, crea la
aplicación web, lee su configuración y autoriza los dominios. Como mucho queda
un interruptor que tocar en la consola de Firebase. No hay nada que copiar ni
escribir a mano.

[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) explica el detalle técnico: roles,
identidades y por qué cada cosa está donde está.

**No se genera, no se descarga y no se almacena ninguna clave JSON de cuenta de
servicio en ningún punto del sistema.** Cloud Run usa la identidad de su cuenta
de servicio adjunta y Cloud Build se conecta a GitHub con la app de Google. La
versión simplificada no guarda ningún secreto: al quitar la voz hablada clonada
desapareció el único uso de Secret Manager.

## Lo que el MVP no resuelve

La **identidad vocal cantada**. Lyria acepta texto e imágenes de referencia,
pero no audio de referencia, así que no hay forma de fijar una voz cantada entre
canciones. El Voice Profile viaja en cada prompt y es lo mejor que se puede
hacer; es una limitación asumida, no un descuido. La arquitectura permite
sustituir el Voice Engine más adelante sin rediseñar el resto.

El **contenido hablado ya no existe**: la versión simplificada quitó el
Content Studio (entrevistas, BTS, cortos) y con él la voz hablada clonada de
Chirp 3. El estudio es solo crear el artista, su canción y su videoclip.

## La versión simplificada (2026-11)

Un universo es UN artista. Lo fijo del artista vive en su ficha: su **estilo
visual** (realista, anime, óleo…), que sale en su cara y en todos los planos;
su **voz cantada**, un solo texto que viaja palabra por palabra en cada letra
y en cada encargo a Lyria; sus **géneros combinables** (hasta tres, que cada
canción hereda y puede ajustar); y sus **referencias de YouTube**, que la
propia app analiza con Gemini y guarda como resumen de estilo editable. El
artista puede nacer también de una **foto subida**: tal cual como su cara,
como base para generarla en su estilo, o como fuente de su estilo visual. El
vestuario y las locaciones ya no son secciones: van escritos dentro del
storyboard de cada videoclip, con planos cortos pensados para cortar cada
3–5 segundos y la música sonando desde el segundo 0. El montaje final se
renderiza de verdad en el servicio, que lleva FFmpeg en su imagen: sin MP4
renderizado, un proyecto no se puede aprobar.

---

## Modelos

- **Letras: la base de oficio cubre el espectro completo.** Estructura
  de canción entera (intro, versos, pre-coro, coro, puente hablado,
  tercer verso), escenas concretas en vez de consignas, rima audible
  constante y la temperatura que pida cada canción — de la
  insinuación y la picardía al sexo gráfico — sin que la app la baje.
  La letra que el Director escribe pasa una revisión contra esa base
  antes de guardarse.
- **Tempo: la velocidad la manda el género.** Cada género escogible
  tiene su tempo natural (BPM, paso y fraseo) y ese es el que viaja
  en el encargo; el BPM que el Director inventaba en el concepto ya
  no llega a Lyria. El encargo ordena tempo firme: prohibido acelerar
  para que quepa la letra — si algo no cabe, se repite menos el coro.
  Y la letra nace medida: la app calcula cuántas palabras caben
  cantadas bien en los segundos pedidos al paso del género, y la
  escritura y su revisión se quedan dentro de esa medida. (La
  primera generación del dueño tras este despliegue es la prueba de
  oído del control.)
- **Música: Lyria por dos puertas.** Sin clave: Lyria 3 Pro
  (`lyria-3-pro-preview`) por Vertex, con la identidad del proyecto.
  Con la clave de Gemini del dueño puesta como variable de entorno
  del servicio (AAUS_GEMINI_API_KEY): Lyria 3.5
  (`lyria-3.5`) por la API de Gemini. El encargo es el mismo en las
  dos puertas e incluye una orden de dicción: cada palabra completa,
  sílaba a sílaba, sin recortar palabras para caber en el ritmo.
  (El 2026-11-07 se probó Lyria 3.5 por Vertex con una canción real y
  Vertex contestó que no está soportada por su API de interacciones;
  esa misma noche el dueño habilitó su clave y se abrió la segunda
  puerta. La clave vive como variable de entorno del servicio,
  puesta por el dueño en la consola, y ningún GET la devuelve.)
