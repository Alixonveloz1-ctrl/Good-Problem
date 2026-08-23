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

## Las cuatro reglas que sostienen el sistema

Están en el código, no solo en el documento. Viven en
[`backend/app/domain/guards.py`](backend/app/domain/guards.py) y no se pueden
desactivar editando la configuración.

| Regla | Por qué | Dónde se comprueba |
|---|---|---|
| La música solo llega a `lyria-3-pro` | `lyria-3` y `lyria-2` hacen clips de 30 s, no canciones. Prohibidos también como respaldo tras un fallo | `assert_music_model` |
| Veo se llama siempre con el audio desactivado | La pista sale de Lyria y la voz de Chirp. Activarlo costaría el doble por segundo para producir algo que el montaje tira | `enforce_video_audio_disabled` |
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
(`infra/setup.sh` los deja creados).

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
| Voz hablada | Chirp 3 Instant Custom Voice | $30 por millón de caracteres |

El usuario elige modelo y variante **en cada generación**, desde un bottom sheet
con el precio de cada opción a la vista.

## Estructura

```
backend/
  app/
    domain/        guards, registro de modelos, precios, entidades
    orchestrator/  el Generation Orchestrator y los handlers por tipo
    providers/     Vertex AI (REST + ADC), Chirp, Storage, Secret Manager
    services/      presupuesto, jobs, aprobaciones, contexto, plan, exports
    routers/       la API HTTP
    assembly/      Media Assembly Engine (FFmpeg, Cloud Run Job)
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

[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) tiene el procedimiento completo,
ejecutable desde Cloud Shell en la app de Google Cloud para iOS.

```bash
bash infra/setup.sh MI-PROYECTO propietario@gmail.com us-central1
```

**No se genera, no se descarga y no se almacena ninguna clave JSON de cuenta de
servicio en ningún punto del sistema.** Cloud Run usa la identidad de su cuenta
de servicio adjunta; Cloud Build se conecta a GitHub con la app de Google; y
Secret Manager guarda únicamente la clave de voz clonada de Chirp 3, que es un
identificador de la API y no una credencial de acceso a la cuenta.

## Lo que el MVP no resuelve

La **identidad vocal cantada**. Lyria acepta texto e imágenes de referencia,
pero no audio de referencia, así que no hay forma de fijar una voz cantada entre
canciones. El Voice Profile viaja en cada prompt y es lo mejor que se puede
hacer; es una limitación asumida, no un descuido. La arquitectura permite
sustituir el Voice Engine más adelante sin rediseñar el resto.

La **voz hablada sí está resuelta**: Chirp 3 clona una voz a partir de una
muestra de 10 segundos y devuelve una clave reutilizable, de modo que las
entrevistas, el BTS y el diario del artista suenan siempre igual.
