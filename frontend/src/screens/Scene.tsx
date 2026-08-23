import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Scene } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import type { Registry } from '../api/types'
import { Card, ErrorNote, Field, Loading, StatusBadge, TopBar } from '../components/ui'

interface SceneDetail extends Scene {
  image: { url: string; model: string; variant: string } | null
  clip: {
    url: string
    model: string
    variant: string
    duration_seconds: number
    generate_audio: boolean
  } | null
}

export function SceneScreen() {
  const { universeId = '', sceneId = '' } = useParams()
  const { data, loading, error, reload } = useResource<SceneDetail>(
    `/api/universes/${universeId}/scenes/${sceneId}`,
  )
  const registry = useResource<Registry>('/api/registry/models')
  const action = useAction()
  const [imageModel, setImageModel] = useState<ModelChoice | null>(null)
  const [videoModel, setVideoModel] = useState<ModelChoice | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')

  const base = `/api/universes/${universeId}/scenes/${sceneId}`

  const run = async (fn: () => Promise<{ id: string }>) => {
    const job = await action.run(fn)
    if (job) setJobId(job.id)
  }

  const imageApproved = data?.image_status === 'APPROVED'
  const clipApproved = data?.clip_status === 'APPROVED'
  // Veo solo continua una toma con veo-3.1 y veo-3.1-fast; lite no puede.
  const puedeAlargar = Boolean(
    clipApproved &&
      data?.clip &&
      (registry.data?.models ?? []).find((m) => m.id === data.clip?.model)?.capabilities
        .supports_extend,
  )

  return (
    <>
      <TopBar
        title={data ? `Escena ${data.index + 1}` : 'Escena'}
        back
        action={data && <StatusBadge status={data.status} />}
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />

        {data && (
          <>
            <Card>
              <div className="row between">
                <h3>Plano</h3>
                <span className="muted">{data.duration_seconds}s · {data.song_timestamp}</span>
              </div>
              <div>{data.action}</div>
              {data.camera && <div className="muted">Camara: {data.camera}</div>}
              {data.lighting && <div className="muted">Luz: {data.lighting}</div>}
              {data.dialogue && <div className="muted">Dialogo: {data.dialogue}</div>}
              {data.reuses_scene_id && (
                <div className="notice">
                  El Director propuso reutilizar una toma ya aprobada. {data.reuse_note}
                  <button
                    className="btn small block"
                    style={{ marginTop: 8 }}
                    onClick={async () => {
                      await action.run(() =>
                        api.post(`${base}/reuse`, {
                          reuses_scene_id: data.reuses_scene_id,
                          force_generate: true,
                          note: 'Forzado por el usuario',
                        }),
                      )
                      await reload()
                    }}
                  >
                    Forzar una toma nueva
                  </button>
                </div>
              )}
            </Card>

            {/* Image first, always (PRD 24) */}
            <Card>
              <div className="row between">
                <h3>1 · Imagen de referencia</h3>
                <StatusBadge status={data.image_status} />
              </div>
              {data.image ? (
                <img className="media wide" src={data.image.url} alt={`Escena ${data.index + 1}`} />
              ) : (
                <div className="placeholder">Todavia no hay imagen. Veo no entra hasta que la haya.</div>
              )}
              <Field
                label="Prompt (opcional, sobreescribe el del storyboard)"
                value={prompt}
                onChange={setPrompt}
                multiline
              />
              <ModelPicker kind="image" value={imageModel} onChange={setImageModel} />
              <div className="btn-grid">
                <button
                  className="btn primary"
                  disabled={action.busy}
                  onClick={() =>
                    run(() =>
                      api.post(`${base}/image`, {
                        prompt: prompt || undefined,
                        model: imageModel?.model,
                        variant: imageModel?.variant,
                        idempotency_key: newIdempotencyKey('img'),
                      }),
                    )
                  }
                >
                  {data.image ? 'Regenerar' : 'Generar imagen'}
                </button>
                <button
                  className="btn ok"
                  disabled={action.busy || !data.image}
                  onClick={async () => {
                    await action.run(() => api.post(`${base}/image/approve`))
                    await reload()
                  }}
                >
                  Aprobar y bloquear
                </button>
                <button
                  className="btn danger"
                  disabled={action.busy || !data.image}
                  onClick={async () => {
                    await action.run(() => api.post(`${base}/image/reject`))
                    await reload()
                  }}
                >
                  Rechazar
                </button>
              </div>
            </Card>

            {/* Then Veo */}
            <Card>
              <div className="row between">
                <h3>2 · Clip con Veo</h3>
                <StatusBadge status={data.clip_status} />
              </div>
              {data.clip ? (
                <video className="media wide" controls preload="none" src={data.clip.url} />
              ) : (
                <div className="placeholder">Sin clip.</div>
              )}
              <ModelPicker
                kind="video"
                value={videoModel}
                onChange={setVideoModel}
                seconds={data.duration_seconds}
                label="Modelo de video"
              />
              <div className="notice">
                El audio de Veo va siempre desactivado. La pista sale de Lyria y la voz hablada de
                Chirp, asi que generarlo costaria el doble por segundo para tirarlo en el montaje.
              </div>
              <div className="btn-grid">
                <button
                  className="btn primary"
                  disabled={action.busy || !imageApproved}
                  onClick={() =>
                    run(() =>
                      api.post(`${base}/clip`, {
                        model: videoModel?.model,
                        variant: videoModel?.variant,
                        duration_seconds: data.duration_seconds,
                        idempotency_key: newIdempotencyKey('clip'),
                      }),
                    )
                  }
                >
                  {data.clip ? 'Regenerar clip' : 'Generar clip'}
                </button>
                <button
                  className="btn ok"
                  disabled={action.busy || !data.clip}
                  onClick={async () => {
                    await action.run(() => api.post(`${base}/clip/approve`))
                    await reload()
                  }}
                >
                  Aprobar clip
                </button>
                <button
                  className="btn danger"
                  disabled={action.busy || !data.clip}
                  onClick={async () => {
                    await action.run(() => api.post(`${base}/clip/reject`))
                    await reload()
                  }}
                >
                  Rechazar
                </button>
              </div>
              {!imageApproved && (
                <div className="muted">
                  Una escena no entra a video hasta que su imagen este aprobada.
                </div>
              )}
            </Card>

            {puedeAlargar && (
              <Card>
                <h3>3 · Alargar esta toma</h3>
                <p className="muted" style={{ margin: 0 }}>
                  Veo continua el plano 7 segundos mas, sin corte. Quedaria en{' '}
                  {data.duration_seconds + 7} segundos.
                </p>
                <div className="notice">
                  Dos cosas antes de pulsarlo. La continuacion sale siempre a <strong>720p</strong>,
                  aunque esta toma sea 1080p. Y Veo no recibe aqui las fotos del personaje: solo
                  mira el ultimo segundo del clip. Si la toma termina sin verse la cara, puede
                  cambiartela.
                </div>
                <button
                  className="btn block"
                  disabled={action.busy}
                  onClick={() =>
                    run(() =>
                      api.post(`${base}/clip/extend`, {
                        idempotency_key: newIdempotencyKey('ext'),
                      }),
                    )
                  }
                >
                  Alargar +7 s
                </button>
                <div className="muted">
                  Tendras que volver a aprobarla: dura mas y llega en 720p.
                </div>
              </Card>
            )}

            {jobId && (
              <JobWatcher
                universeId={universeId}
                jobId={jobId}
                onReady={() => {
                  setJobId(null)
                  void reload()
                }}
              />
            )}

            {data.clip && (
              <div className="muted">
                Clip generado con {data.clip.model} en {data.clip.variant},{' '}
                {data.clip.duration_seconds} segundos, sin audio.
              </div>
            )}
          </>
        )}
      </main>
    </>
  )
}
