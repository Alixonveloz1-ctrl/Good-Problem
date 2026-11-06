import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Song } from '../api/types'
import { ApprovalBar } from '../components/ApprovalBar'
import { JobWatcher } from '../components/JobWatcher'
import { Card, Empty, ErrorNote, Field, Loading, Sheet, StatusBadge, TopBar, DeleteButton } from '../components/ui'
import { ElegirGeneros } from '../components/Seleccion'
import { textoGeneros } from '../lib/catalogo'

export function SongsScreen() {
  const { universeId = '' } = useParams()
  const navigate = useNavigate()
  const { data, loading, error, reload } = useResource<Song[]>(
    `/api/universes/${universeId}/songs`,
  )
  const borrado = useAction()
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [duration, setDuration] = useState('150')
  const action = useAction()

  const create = async () => {
    const created = await action.run(() =>
      api.post<Song>(`/api/universes/${universeId}/songs`, {
        title: title.trim(),
        requested_duration_seconds: Number(duration) || 150,
      }),
    )
    if (created) {
      setCreating(false)
      await reload()
      navigate(`/u/${universeId}/songs/${created.id}`)
    }
  }

  return (
    <>
      <TopBar
        title="Música"
        back
        action={
          <button className="btn small primary" onClick={() => setCreating(true)}>
            Nueva
          </button>
        }
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        {data && data.length === 0 && (
          <Empty
            title="Sin canciones"
            hint="Una idea o una letra tuya. El Director propone y tu decides."
            action={
              <button className="btn primary" onClick={() => setCreating(true)}>
                Crear cancion
              </button>
            }
          />
        )}
        <div className="list">
          {(data ?? []).map((song) => (
            <div key={song.id} className="card fila-borrable">
              <Link to={`/u/${universeId}/songs/${song.id}`} className="grow">
                <div className="row between">
                  <strong>{song.title || 'Sin titulo'}</strong>
                  <StatusBadge status={song.status} />
                </div>
                <div className="muted">{song.genre || 'sin genero'}</div>
                <div className="muted">
                  {song.versions.length} version(es) · {song.requested_duration_seconds}s
                </div>
              </Link>
              <DeleteButton
                busy={borrado.busy}
                onDelete={async () => {
                  await borrado.run(() =>
                    api.del(`/api/universes/${universeId}/songs/${song.id}`),
                  )
                  await reload()
                }}
              />
            </div>
          ))}
        </div>
      </main>

      {creating && (
        <Sheet title="Nueva cancion" onClose={() => setCreating(false)}>
          <Field label="Titulo provisional" value={title} onChange={setTitle} />
          <Field
            label="Duracion en segundos (Lyria 3 Pro, hasta 180)"
            value={duration}
            onChange={setDuration}
            type="number"
          />
          <ErrorNote error={action.error} onDismiss={action.clearError} />
          <button className="btn primary block" onClick={create} disabled={action.busy}>
            Crear
          </button>
        </Sheet>
      )}
    </>
  )
}

export function SongScreen() {
  const { universeId = '', songId = '' } = useParams()
  const navigate = useNavigate()
  const { data, loading, error, reload } = useResource<Song>(
    `/api/universes/${universeId}/songs/${songId}`,
  )
  const action = useAction()
  const [jobId, setJobId] = useState<string | null>(null)
  const [lyrics, setLyrics] = useState('')
  const [brief, setBrief] = useState('')
  const [genreOverride, setGenreOverride] = useState('')
  const [generos, setGeneros] = useState<string[]>([])
  const [mezcla, setMezcla] = useState('')
  const [enlace, setEnlace] = useState('')
  const [resumen, setResumen] = useState('')

  useEffect(() => {
    if (!data) return
    setLyrics(data.lyrics ?? '')
    setGeneros(data.genres ?? [])
    setMezcla(data.genre_free ?? '')
    setResumen(data.inspiration_summary ?? '')
  }, [data])

  const guardarGeneros = async () => {
    await action.run(() =>
      api.patch(base, { genres: generos, genre_free: mezcla }),
    )
    await reload()
  }

  const analizarEnlace = async () => {
    const hecho = await action.run(() =>
      api.post(`${base}/inspiration`, { url: enlace }),
    )
    if (hecho) setEnlace('')
    await reload()
  }

  const guardarResumen = async () => {
    await action.run(() => api.patch(base, { inspiration_summary: resumen }))
    await reload()
  }

  const run = async (fn: () => Promise<{ id: string }>) => {
    const job = await action.run(fn)
    if (job) setJobId(job.id)
  }

  const base = `/api/universes/${universeId}/songs/${songId}`
  const concept = (data?.concept ?? {}) as Record<string, unknown>
  const conceptApproved = concept.status === 'APPROVED'
  const lyricsApproved = data?.lyrics_status === 'APPROVED'

  return (
    <>
      <TopBar
        title={data?.title || 'Cancion'}
        back
        action={data && <StatusBadge status={data.status} />}
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />

        {data && (
          <>
            {/* Lo de esta cancion: su combinacion y su referencia propia */}
            <Card>
              <h3>Generos de esta cancion</h3>
              <p className="muted" style={{ margin: 0 }}>
                Viene relleno con la combinacion de su artista. Si la cambias aqui, cambia solo
                esta cancion; la del artista sigue
                como esta en su Identidad. Entra en la letra y en el encargo a Lyria.
              </p>
              <ElegirGeneros valor={generos} alCambiar={setGeneros} />
              <Field
                label="O escribe tu mezcla para esta cancion"
                value={mezcla}
                onChange={setMezcla}
              />
              {textoGeneros(generos, mezcla) && (
                <p className="muted">Suena a: {textoGeneros(generos, mezcla)}</p>
              )}
              <button className="btn block" onClick={guardarGeneros} disabled={action.busy}>
                Guardar los generos de esta cancion
              </button>

              <div className="section-title">Una referencia solo para esta cancion</div>
              <Field
                label="Enlace de YouTube"
                value={enlace}
                onChange={setEnlace}
                placeholder="https://www.youtube.com/watch?v=…"
              />
              <button
                className="btn block"
                onClick={analizarEnlace}
                disabled={action.busy || !enlace.trim()}
              >
                {action.busy ? 'Escuchandola…' : 'Analizar esta cancion'}
              </button>
              {(resumen || data.inspiration_url) && (
                <>
                  <Field
                    label="Resumen de su estilo (editable: alimenta esta cancion)"
                    value={resumen}
                    onChange={setResumen}
                    multiline
                  />
                  <button className="btn block" onClick={guardarResumen} disabled={action.busy}>
                    Guardar el resumen
                  </button>
                </>
              )}
            </Card>

            {/* 1. Concept */}
            <Card>
              <div className="row between">
                <h3>1 · Concepto musical</h3>
                <StatusBadge status={(concept.status as string) ?? 'DRAFT'} />
              </div>
              <Field
                label="Idea"
                value={brief}
                onChange={setBrief}
                multiline
                placeholder="Una noche que no termina, luces de neon, despedida…"
              />
              <Field
                label="Cambiar el genero que propuso el Director"
                value={genreOverride}
                onChange={setGenreOverride}
                placeholder="hip hop"
              />
              <p className="muted" style={{ margin: 0 }}>
                Si cambias algo, el Director rehace la propuesta a partir de ese cambio.
              </p>
              <div className="btn-grid">
                <button
                  className="btn primary"
                  disabled={action.busy}
                  onClick={() =>
                    run(() =>
                      api.post(`${base}/concept`, {
                        brief,
                        overrides: genreOverride ? { genre: genreOverride } : {},
                        idempotency_key: newIdempotencyKey('concept'),
                      }),
                    )
                  }
                >
                  Pedir propuesta
                </button>
                <button
                  className="btn ok"
                  disabled={action.busy}
                  onClick={async () => {
                    await action.run(() => api.post(`${base}/concept/approve`))
                    await reload()
                  }}
                >
                  Aprobar concepto
                </button>
              </div>
              {Object.entries(concept)
                .filter(([key, value]) => key !== 'status' && value)
                .map(([key, value]) => (
                  <div key={key}>
                    <div className="muted">{key.replace(/_/g, ' ')}</div>
                    <div>{Array.isArray(value) ? value.join(', ') : String(value)}</div>
                  </div>
                ))}
            </Card>

            {/* 2. Lyrics */}
            <Card>
              <div className="row between">
                <h3>2 · Letra</h3>
                <StatusBadge status={data.lyrics_status} />
              </div>
              <Field label="Letra" value={lyrics} onChange={setLyrics} multiline />
              <div className="btn-grid">
                <button
                  className="btn"
                  disabled={action.busy}
                  onClick={async () => {
                    await action.run(() =>
                      api.put(`${base}/lyrics`, { lyrics, author: 'user' }),
                    )
                    await reload()
                  }}
                >
                  Guardar mi letra
                </button>
                <button
                  className="btn"
                  disabled={action.busy || !lyrics.trim()}
                  onClick={() =>
                    run(() =>
                      api.post(`${base}/lyrics/analyze`, {
                        idempotency_key: newIdempotencyKey('analyze'),
                      }),
                    )
                  }
                >
                  Analizar mi letra
                </button>
                <button
                  className="btn"
                  disabled={action.busy || !conceptApproved}
                  onClick={() =>
                    run(() =>
                      api.post(`${base}/lyrics/generate`, {
                        idempotency_key: newIdempotencyKey('lyrics'),
                      }),
                    )
                  }
                >
                  Que la escriba el Director
                </button>
                <button
                  className="btn ok"
                  disabled={action.busy || !lyrics.trim()}
                  onClick={async () => {
                    await action.run(() => api.post(`${base}/lyrics/approve`))
                    await reload()
                  }}
                >
                  Aprobar letra
                </button>
              </div>
              {!conceptApproved && (
                <div className="muted">
                  El Director escribe la letra despues de que apruebes el concepto.
                </div>
              )}
            </Card>

            {/* 3. Lyria */}
            <Card>
              <div className="row between">
                <h3>3 · Generar con Lyria 3 Pro</h3>
                <span className="badge accent">Sin selector</span>
              </div>
              <p className="muted" style={{ margin: 0 }}>
                Cancion completa a la duracion pedida ({data.requested_duration_seconds}s). Lyria 3
                y Lyria 2 hacen clips de 30 s y estan fuera del sistema, tampoco como respaldo si
                algo falla.
              </p>
              <button
                className="btn primary block"
                disabled={action.busy || !lyricsApproved}
                onClick={() =>
                  run(() =>
                    api.post(`${base}/generate`, {
                      duration_seconds: data.requested_duration_seconds,
                      idempotency_key: newIdempotencyKey('song'),
                    }),
                  )
                }
              >
                Generar cancion · $0,08
              </button>
              {!lyricsApproved && (
                <div className="muted">Lyria no se llama hasta que la letra este aprobada.</div>
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

            {/* 4. Versions */}
            {data.versions.length > 0 && (
              <>
                <div className="section-title">Versiones</div>
                <div className="list">
                  {data.versions.map((version) => (
                    <Card key={version.version}>
                      <div className="row between">
                        <strong>Version {version.version}</strong>
                        <StatusBadge status={version.status} />
                      </div>
                      {version.url && (
                        <audio controls preload="none" src={version.url} style={{ width: '100%' }} />
                      )}
                      <div className="muted mono">{version.model}</div>
                      <button
                        className="btn ok block"
                        disabled={action.busy}
                        onClick={async () => {
                          await action.run(() =>
                            api.post(`${base}/versions/${version.version}/approve`),
                          )
                          await reload()
                        }}
                      >
                        Aprobar como master
                      </button>
                    </Card>
                  ))}
                </div>
              </>
            )}

            <ApprovalBar
              status={data.status}
              busy={action.busy}
              onRegenerate={
                lyricsApproved
                  ? () =>
                      run(() =>
                        api.post(`${base}/generate`, {
                          idempotency_key: newIdempotencyKey('song'),
                        }),
                      )
                  : undefined
              }
              onReject={async () => {
                await action.run(() => api.post(`${base}/reject`))
                await reload()
              }}
              extra={
                data.status === 'APPROVED' ? (
                  <button
                    className="btn primary block"
                    onClick={async () => {
                      if (data.video_project_id) {
                        navigate(`/u/${universeId}/projects/${data.video_project_id}`)
                        return
                      }
                      const project = await action.run(() =>
                        api.post<{ id: string }>(`/api/universes/${universeId}/video-projects`, {
                          song_id: songId,
                          title: data.title,
                        }),
                      )
                      if (project) navigate(`/u/${universeId}/projects/${project.id}`)
                    }}
                  >
                    {data.video_project_id ? 'Ir al videoclip' : 'Empezar el videoclip'}
                  </button>
                ) : (
                  <div className="muted">
                    Una cancion rechazada no desencadena el videoclip.
                  </div>
                )
              }
            />

            {data.cover_path && (
              <img className="media square" src={mediaUrl(data.cover_path) ?? ''} alt="Portada" />
            )}
          </>
        )}
      </main>
    </>
  )
}
