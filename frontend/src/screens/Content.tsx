import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { ContentPiece } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import { Card, Empty, ErrorNote, Field, Loading, Sheet, StatusBadge, TopBar } from '../components/ui'

/** Pieces cut out of an approved master cost nothing; the rest need footage. */
const DERIVED_KINDS = new Set(['short', 'reel', 'tiktok', 'teaser', 'lyric_clip'])

const KINDS = [
  ['short', 'Short'],
  ['reel', 'Reel'],
  ['tiktok', 'TikTok'],
  ['teaser', 'Teaser'],
  ['bts', 'BTS'],
  ['interview', 'Entrevista'],
  ['announcement', 'Anuncio'],
  ['lyric_clip', 'Lyric clip'],
]

export function ContentScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<ContentPiece[]>(
    `/api/universes/${universeId}/content`,
  )
  const voz = useResource<{ ready: boolean }>(`/api/universes/${universeId}/content/voice-clone`)
  const [creating, setCreating] = useState(false)
  const [kind, setKind] = useState('short')
  const [title, setTitle] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [imageModel, setImageModel] = useState<ModelChoice | null>(null)
  const [videoModel, setVideoModel] = useState<ModelChoice | null>(null)
  const action = useAction()

  const create = async () => {
    const created = await action.run(() =>
      api.post<ContentPiece>(`/api/universes/${universeId}/content`, { kind, title }),
    )
    if (created) {
      setCreating(false)
      setTitle('')
      await reload()
    }
  }

  const run = async (fn: () => Promise<{ id: string }>) => {
    const job = await action.run(fn)
    if (job) setJobId(job.id)
  }

  return (
    <>
      <TopBar
        title="Contenido"
        back
        action={
          <button className="btn small primary" onClick={() => setCreating(true)}>
            Nuevo
          </button>
        }
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />
        <p className="muted" style={{ margin: 0 }}>
          Shorts, Reels y TikToks se recortan del master aprobado y no cuestan nada. BTS,
          entrevistas y anuncios necesitan material propio: imagen primero, despues Veo sin audio, y
          la voz de Chirp encima en el montaje. Todo respeta el Canon.
        </p>
        {voz.data && !voz.data.ready && (
          <div className="notice">
            Este artista todavia no tiene voz. Sin ella, el boton «Voz de Chirp» no puede
            funcionar.{' '}
            <Link to={`/u/${universeId}/voz`} style={{ color: 'var(--accent)' }}>
              Grabarla ahora
            </Link>
          </div>
        )}
        <ModelPicker kind="image" value={imageModel} onChange={setImageModel} label="Modelo de imagen" />
        <ModelPicker kind="video" value={videoModel} onChange={setVideoModel} label="Modelo de video" />

        {data && data.length === 0 && (
          <Empty title="Sin contenido" hint="Shorts, Reels, TikToks, BTS, entrevistas y teasers." />
        )}

        <div className="list">
          {(data ?? []).map((piece) => (
            <Card key={piece.id}>
              <div className="row between">
                <strong>{piece.title || piece.kind}</strong>
                <StatusBadge status={piece.status} />
              </div>
              <span className="badge">{piece.kind}</span>
              {piece.script && <p className="sub" style={{ whiteSpace: 'pre-wrap' }}>{piece.script}</p>}
              {piece.voice_url && <audio controls preload="none" src={piece.voice_url} style={{ width: '100%' }} />}
              {piece.url && <video className="media" controls preload="none" src={piece.url} />}
              <div className="btn-grid">
                <button
                  className="btn small"
                  disabled={action.busy}
                  onClick={() =>
                    run(() =>
                      api.post(`/api/universes/${universeId}/content/${piece.id}/script`, {
                        idempotency_key: newIdempotencyKey('script'),
                      }),
                    )
                  }
                >
                  Escribir guion
                </button>

                {DERIVED_KINDS.has(piece.kind) ? (
                  <button
                    className="btn small"
                    disabled={action.busy}
                    onClick={() =>
                      run(() =>
                        api.post(`/api/universes/${universeId}/content/${piece.id}/cut`, {
                          start: 0,
                          duration: 15,
                          idempotency_key: newIdempotencyKey('cut'),
                        }),
                      )
                    }
                  >
                    Recortar del master · gratis
                  </button>
                ) : (
                  <>
                    <button
                      className="btn small"
                      disabled={action.busy}
                      onClick={() =>
                        run(() =>
                          api.post(`/api/universes/${universeId}/content/${piece.id}/still`, {
                            model: imageModel?.model,
                            variant: imageModel?.variant,
                            idempotency_key: newIdempotencyKey('still'),
                          }),
                        )
                      }
                    >
                      Generar imagen
                    </button>
                    <button
                      className="btn small"
                      disabled={action.busy}
                      onClick={() =>
                        run(() =>
                          api.post(`/api/universes/${universeId}/content/${piece.id}/clip`, {
                            model: videoModel?.model,
                            variant: videoModel?.variant,
                            idempotency_key: newIdempotencyKey('cclip'),
                          }),
                        )
                      }
                    >
                      Generar video
                    </button>
                  </>
                )}

                <button
                  className="btn small"
                  disabled={action.busy || !piece.script || voz.data?.ready === false}
                  onClick={() =>
                    run(() =>
                      api.post(`/api/universes/${universeId}/content/${piece.id}/voice`, {
                        idempotency_key: newIdempotencyKey('voice'),
                      }),
                    )
                  }
                >
                  Voz de Chirp
                </button>
                <button
                  className="btn small"
                  disabled={action.busy || !piece.voice_url || !piece.url}
                  onClick={() =>
                    run(() =>
                      api.post(`/api/universes/${universeId}/content/${piece.id}/mix`, {
                        idempotency_key: newIdempotencyKey('mix'),
                      }),
                    )
                  }
                >
                  Montar voz sobre el video
                </button>
                <button
                  className="btn small ok"
                  disabled={action.busy}
                  onClick={async () => {
                    await action.run(() =>
                      api.post(`/api/universes/${universeId}/content/${piece.id}/approve`),
                    )
                    await reload()
                  }}
                >
                  Aprobar
                </button>
              </div>
            </Card>
          ))}
        </div>

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
      </main>

      {creating && (
        <Sheet title="Nuevo contenido" onClose={() => setCreating(false)}>
          <div className="field">
            <label>Tipo</label>
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              {KINDS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <Field label="Titulo" value={title} onChange={setTitle} />
          <button className="btn primary block" onClick={create} disabled={action.busy}>
            Crear
          </button>
        </Sheet>
      )}
    </>
  )
}
