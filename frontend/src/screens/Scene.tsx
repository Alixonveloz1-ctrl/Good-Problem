import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Scene } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import { Card, ErrorNote, Field, Loading, TopBar } from '../components/ui'

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

  const tieneImagen = Boolean(data?.image)

  return (
    <>
      <TopBar title={data ? `Escena ${data.index + 1}` : 'Escena'} back />
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
              {data.location_description && (
                <div className="muted">Donde: {data.location_description}</div>
              )}
              {data.wardrobe_description && (
                <div className="muted">Vestuario: {data.wardrobe_description}</div>
              )}
              {data.camera && <div className="muted">Camara: {data.camera}</div>}
              {data.lighting && <div className="muted">Luz: {data.lighting}</div>}
              {data.dialogue && <div className="muted">Dialogo: {data.dialogue}</div>}
              {(data.planos ?? []).length > 0 && (
                <div>
                  <div className="muted">Planos de esta escena (cortes dentro del clip):</div>
                  <ol style={{ margin: '4px 0', paddingLeft: 20 }}>
                    {(data.planos ?? []).map((plano, i) => (
                      <li key={i}>{plano}</li>
                    ))}
                  </ol>
                </div>
              )}
              {data.reuses_scene_id && (
                <div className="notice">
                  El Director propuso reutilizar una toma ya generada. {data.reuse_note}
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
              </div>
              <div className="muted">
                La imagen que se genera queda en uso tal cual: es la que recibe Veo. Si no te
                gusta, regenera y la nueva la sustituye.
              </div>
            </Card>

            {/* Then Veo */}
            <Card>
              <div className="row between">
                <h3>2 · Clip con Veo</h3>
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
                El audio de Veo va siempre desactivado. La pista sale de Lyria, asi que generarlo
                costaria el doble por segundo para tirarlo en el montaje.
              </div>
              <div className="btn-grid">
                <button
                  className="btn primary"
                  disabled={action.busy || !tieneImagen}
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
              </div>
              {!tieneImagen && (
                <div className="muted">
                  Genera primero la imagen de referencia de esta escena: Veo parte de ella.
                </div>
              )}
            </Card>

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
