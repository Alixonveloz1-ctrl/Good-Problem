import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Song } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { Card, Empty, ErrorNote, Field, Loading, Sheet, TopBar, DeleteButton } from '../components/ui'
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
  // Guardar sin decir nada parecia que no pasaba nada: cada boton de
  // guardar enciende su aviso, y el aviso se apaga al volver a editar.
  const [avisoGeneros, setAvisoGeneros] = useState(false)
  const [avisoResumen, setAvisoResumen] = useState(false)

  useEffect(() => {
    if (!data) return
    setLyrics(data.lyrics ?? '')
    setGeneros(data.genres ?? [])
    setMezcla(data.genre_free ?? '')
    setResumen(data.inspiration_summary ?? '')
  }, [data])

  // La combinacion se guarda SOLA, en el acto de cambiarla. Antes vivia
  // solo en la pantalla hasta que se apretaba su propio boton de guardar,
  // y cualquier otra accion que recargara la ficha (guardar la letra,
  // generar la cancion) la devolvia a los generos que si estaban
  // guardados — los del artista — perdiendo lo elegido sin avisar. Sin
  // recargar despues de guardar: lo que se ve ya es lo que hay guardado.
  const guardarGenerosAhora = async (g: string[], m: string) => {
    const hecho = await action.run(() => api.patch(base, { genres: g, genre_free: m }))
    if (hecho) setAvisoGeneros(true)
    return Boolean(hecho)
  }

  const analizarEnlace = async () => {
    const hecho = await action.run(() =>
      api.post(`${base}/inspiration`, { url: enlace }),
    )
    if (hecho) setEnlace('')
    await reload()
  }

  const guardarResumen = async () => {
    const hecho = await action.run(() => api.patch(base, { inspiration_summary: resumen }))
    if (hecho) setAvisoResumen(true)
    await reload()
  }

  const run = async (fn: () => Promise<{ id: string }>) => {
    const job = await action.run(fn)
    if (job) setJobId(job.id)
  }

  const base = `/api/universes/${universeId}/songs/${songId}`
  const concept = (data?.concept ?? {}) as Record<string, unknown>
  // Ningun paso pide aprobar nada: cada paso necesita que el anterior
  // EXISTA. Hay concepto, hay letra guardada, hay audio generado.
  const hayConcepto = Object.keys(concept).length > 0
  const hayLetra = Boolean((data?.lyrics ?? '').trim())
  const tieneAudio = Boolean(data?.approved_master_path) || (data?.versions.length ?? 0) > 0

  return (
    <>
      <TopBar title={data?.title || 'Cancion'} back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />

        {data && (
          <>
            {/* Lo de esta cancion: su combinacion y su referencia propia */}
            <Card>
              <h3>Generos de esta cancion</h3>
              <p className="muted" style={{ margin: 0 }}>
                Viene relleno con la combinacion de su artista — y si analizas una cancion en la
                referencia de abajo, con los generos de esa cancion. Si la cambias aqui, se guarda
                sola en el acto, sin boton que apretar, y cambia solo esta cancion; la del artista
                sigue como esta en su Identidad. Es la combinacion que entra en la letra y en el
                encargo a Lyria.
              </p>
              <ElegirGeneros
                valor={generos}
                alCambiar={(valor) => {
                  setGeneros(valor)
                  setAvisoGeneros(false)
                  void guardarGenerosAhora(valor, mezcla)
                }}
              />
              <Field
                label="O escribe tu mezcla para esta cancion"
                value={mezcla}
                onChange={(valor) => {
                  setMezcla(valor)
                  setAvisoGeneros(false)
                }}
                onBlur={() => void guardarGenerosAhora(generos, mezcla)}
              />
              {textoGeneros(generos, mezcla) && (
                <p className="muted">Suena a: {textoGeneros(generos, mezcla)}</p>
              )}
              {avisoGeneros && (
                <p className="muted" style={{ margin: 0 }}>
                  ✓ Guardado
                </p>
              )}

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
              {(data.inspiration_failed ||
                (data.inspiration_url && !(data.inspiration_summary ?? '').trim())) && (
                <div className="error">
                  Este enlace no se pudo analizar
                  {data.inspiration_error ? `: ${data.inspiration_error}` : ''}. No hay
                  resumen guardado y la propuesta de concepto avisara antes de generarse
                  sin el. Pega el enlace normal de YouTube (youtube.com/watch?v=…) y vuelve
                  a analizar, o escribe tu el resumen de su estilo aqui abajo.
                </div>
              )}
              {(resumen || data.inspiration_url) && (
                <>
                  <Field
                    label="Resumen de su estilo (editable: alimenta esta cancion)"
                    value={resumen}
                    onChange={(valor) => {
                      setResumen(valor)
                      setAvisoResumen(false)
                    }}
                    multiline
                  />
                  <button className="btn block" onClick={guardarResumen} disabled={action.busy}>
                    Guardar el resumen
                  </button>
                  {avisoResumen && (
                    <p className="muted" style={{ margin: 0 }}>
                      ✓ Guardado
                    </p>
                  )}
                </>
              )}
            </Card>

            {/* 1. Concept */}
            <Card>
              <div className="row between">
                <h3>1 · Concepto musical</h3>
              </div>
              <Field
                label="Idea (opcional)"
                value={brief}
                onChange={setBrief}
                multiline
                placeholder="Una noche que no termina, luces de neon, despedida…"
              />
              <p className="muted" style={{ margin: 0 }}>
                Si la dejas vacia, el Director inventa la idea: de la cancion que analizaste, o
                del artista si no analizaste ninguna.
              </p>
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
                  onClick={async () => {
                    await guardarGenerosAhora(generos, mezcla)
                    run(() =>
                      api.post(`${base}/concept`, {
                        brief,
                        overrides: genreOverride ? { genre: genreOverride } : {},
                        idempotency_key: newIdempotencyKey('concept'),
                      }),
                    )
                  }}
                >
                  Pedir propuesta
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
              </div>
              <Field label="Letra" value={lyrics} onChange={setLyrics} multiline />
              <div className="btn-grid">
                <button
                  className="btn"
                  disabled={action.busy}
                  onClick={async () => {
                    await guardarGenerosAhora(generos, mezcla)
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
                  disabled={action.busy || !hayConcepto}
                  onClick={async () => {
                    await guardarGenerosAhora(generos, mezcla)
                    run(() =>
                      api.post(`${base}/lyrics/generate`, {
                        idempotency_key: newIdempotencyKey('lyrics'),
                      }),
                    )
                  }}
                >
                  Que la escriba el Director
                </button>
              </div>
              {!hayConcepto && (
                <div className="muted">
                  El Director escribe la letra a partir de la propuesta de concepto: pidela
                  primero, en la tarjeta de arriba.
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
                disabled={action.busy || !hayLetra}
                onClick={async () => {
                  await guardarGenerosAhora(generos, mezcla)
                  run(() =>
                    api.post(`${base}/generate`, {
                      duration_seconds: data.requested_duration_seconds,
                      idempotency_key: newIdempotencyKey('song'),
                    }),
                  )
                }}
              >
                Generar cancion · $0,08
              </button>
              {!hayLetra && (
                <div className="muted">
                  Lyria canta sobre la letra guardada: escribe la tuya o pide que la escriba el
                  Director, y guardala.
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

            {/* 4. El audio vigente. Solo se ensena la version actual: las
                anteriores quedaron sustituidas al regenerar, y ensenarlas
                seria ruido. */}
            {data.versions.length > 0 && (
              <>
                <div className="section-title">Su audio</div>
                {(() => {
                  const actual =
                    data.versions.find((v) => v.version === data.approved_version) ??
                    data.versions[data.versions.length - 1]
                  return (
                    <Card key={actual.version}>
                      <div className="row between">
                        <strong>Version {actual.version} · la actual</strong>
                      </div>
                      {actual.url && (
                        <audio controls preload="none" src={actual.url} style={{ width: '100%' }} />
                      )}
                      <div className="muted mono">{actual.model}</div>
                      <div className="muted">
                        Es el audio que usa su videoclip y su descarga. Si no te gusta, genera
                        otra vez y la nueva la sustituye.
                      </div>
                    </Card>
                  )
                })()}
              </>
            )}

            <div className="btn-grid">
              {hayLetra && (
                <button
                  className="btn"
                  disabled={action.busy}
                  onClick={async () => {
                    await guardarGenerosAhora(generos, mezcla)
                    run(() =>
                      api.post(`${base}/generate`, {
                        idempotency_key: newIdempotencyKey('song'),
                      }),
                    )
                  }}
                >
                  Regenerar cancion
                </button>
              )}
              {tieneAudio ? (
                <button
                  className="btn primary"
                  disabled={action.busy}
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
                  Cuando generes la cancion, desde aqui mismo podras montar su videoclip.
                </div>
              )}
            </div>

            {data.cover_path && (
              <img className="media square" src={mediaUrl(data.cover_path) ?? ''} alt="Portada" />
            )}
          </>
        )}
      </main>
    </>
  )
}
