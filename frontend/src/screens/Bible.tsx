import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { ArtistBible, Registry } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { Card, ErrorNote, Field, Loading, StatusBadge, TopBar } from '../components/ui'

const SECTION_LABELS: Record<string, string> = {
  identity: 'Identidad',
  musical: 'Identidad musical',
  visual: 'Identidad visual',
  communication: 'Comunicacion',
}

export function BibleScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<ArtistBible>(
    `/api/universes/${universeId}/bible`,
  )
  const registry = useResource<Registry>('/api/registry/models')
  const action = useAction()
  const [brief, setBrief] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [voiceLines, setVoiceLines] = useState('')

  useEffect(() => {
    if (data) setVoiceLines((data.voice_profile.lines ?? []).join('\n'))
  }, [data])

  const generate = async () => {
    const job = await action.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/bible/generate`, {
        brief,
        idempotency_key: newIdempotencyKey('bible'),
      }),
    )
    if (job) setJobId(job.id)
  }

  const saveVoice = async () => {
    await action.run(() =>
      api.put(`/api/universes/${universeId}/bible/voice-profile`, {
        lines: voiceLines.split('\n').map((line) => line.trim()).filter(Boolean),
      }),
    )
    await reload()
  }

  const approve = async () => {
    await action.run(() => api.post(`/api/universes/${universeId}/bible/approve`))
    await reload()
  }

  const setPreference = async (patch: Record<string, string>) => {
    await action.run(() => api.put(`/api/universes/${universeId}/bible/preferences`, patch))
    await reload()
  }

  return (
    <>
      <TopBar title="Artist Bible" back action={data && <StatusBadge status={data.status} />} />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />

        <Card>
          <h3>Pedir una propuesta</h3>
          <Field
            label="Brief"
            value={brief}
            onChange={setBrief}
            multiline
            placeholder="Cantante de synth pop nocturno, voz calida, ciudad de madrugada…"
          />
          <button className="btn primary block" onClick={generate} disabled={action.busy}>
            {action.busy ? 'Enviando…' : 'Que el Director la escriba'}
          </button>
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
        </Card>

        {data && (
          <>
            <Card>
              <h3>Voice Profile</h3>
              <p className="muted" style={{ margin: 0 }}>
                Se incluye tal cual en cada prompt de Lyria. No garantiza una voz identica entre
                canciones: Lyria no acepta audio de referencia, y esa es una limitacion asumida del
                MVP.
              </p>
              <Field
                label="Una caracteristica por linea"
                value={voiceLines}
                onChange={setVoiceLines}
                multiline
                placeholder={'Female\nWarm mezzo-soprano\nBreathy but clear'}
              />
              <button className="btn block" onClick={saveVoice} disabled={action.busy}>
                Guardar
              </button>
              <div className="muted">
                Voz hablada:{' '}
                {data.voice_profile.speaking_voice_secret
                  ? 'clonada con Chirp 3'
                  : 'sin clonar todavia'}
              </div>
            </Card>

            <Card>
              <h3>Modelos preferidos</h3>
              <p className="muted" style={{ margin: 0 }}>
                Solo se usan cuando no eliges modelo en una generacion concreta.
              </p>
              <div className="field">
                <label>Imagen</label>
                <select
                  value={data.preferences.preferred_image_model ?? ''}
                  onChange={(event) =>
                    setPreference({ preferred_image_model: event.target.value })
                  }
                >
                  <option value="">Sin preferencia</option>
                  {(registry.data?.models ?? [])
                    .filter((model) => model.kind === 'image')
                    .map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label}
                      </option>
                    ))}
                </select>
              </div>
              <div className="field">
                <label>Video</label>
                <select
                  value={data.preferences.preferred_video_model ?? ''}
                  onChange={(event) =>
                    setPreference({ preferred_video_model: event.target.value })
                  }
                >
                  <option value="">Sin preferencia</option>
                  {(registry.data?.models ?? [])
                    .filter((model) => model.kind === 'video')
                    .map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label}
                      </option>
                    ))}
                </select>
              </div>
            </Card>

            {Object.entries(SECTION_LABELS).map(([key, label]) => (
              <Card key={key}>
                <h3>{label}</h3>
                <BibleSection values={data[key as keyof ArtistBible] as Record<string, unknown>} />
              </Card>
            ))}

            <button className="btn ok block" onClick={approve} disabled={action.busy}>
              Aprobar Artist Bible
            </button>
          </>
        )}
      </main>
    </>
  )
}

function BibleSection({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values ?? {}).filter(
    ([, value]) => value !== null && value !== '' && !(Array.isArray(value) && value.length === 0),
  )
  if (entries.length === 0) return <div className="muted">Sin definir todavia.</div>
  return (
    <div className="list">
      {entries.map(([key, value]) => (
        <div key={key}>
          <div className="muted">{key.replace(/_/g, ' ')}</div>
          <div>{Array.isArray(value) ? value.join(', ') : String(value)}</div>
        </div>
      ))}
    </div>
  )
}
