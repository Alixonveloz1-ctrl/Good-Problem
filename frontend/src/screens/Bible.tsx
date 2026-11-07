import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { ClaveDeEnvio } from '../lib/claveEnvio'
import { useAction, useResource } from '../hooks/useApi'
import type { ArtistBible, Inspiration, Registry, SingingVoice } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { ElegirEstilo, ElegirGeneros } from '../components/Seleccion'
import { textoGeneros } from '../lib/catalogo'
import { Card, ErrorNote, Field, Loading, TopBar } from '../components/ui'

const SECTION_LABELS: Record<string, string> = {
  identity: 'Identidad',
  musical: 'Identidad musical',
  communication: 'Comunicacion',
}

const VOZ_VACIA: SingingVoice = {
  sex: '',
  apparent_age: '',
  pitch: '',
  timbre: '',
  language_accent: '',
  singing_style: '',
  text: '',
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
  // La clave de ESTE encargo: la misma entre toques hasta que el envio
  // devuelva su trabajo. Si la respuesta se pierde a los 45 segundos y
  // el servidor si creo el trabajo, el siguiente toque lo recupera en
  // vez de quedarse sin nada (ver lib/claveEnvio).
  const [claveBiblia] = useState(() => new ClaveDeEnvio(() => newIdempotencyKey('bible')))

  const [estilo, setEstilo] = useState('')
  const [voz, setVoz] = useState<SingingVoice>(VOZ_VACIA)
  const [generos, setGeneros] = useState<string[]>([])
  const [mezcla, setMezcla] = useState('')
  const [inspiraciones, setInspiraciones] = useState<Inspiration[]>([])
  const [enlace, setEnlace] = useState('')

  useEffect(() => {
    if (!data) return
    setEstilo(data.visual.style_key ?? '')
    setVoz({ ...VOZ_VACIA, ...(data.singing_voice ?? {}) })
    setGeneros(data.music_genres ?? [])
    setMezcla(data.music_genre_free ?? '')
    setInspiraciones(data.inspirations ?? [])
  }, [data])

  const generate = async () => {
    const job = await action.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/bible/generate`, {
        brief,
        idempotency_key: claveBiblia.paraEnviar(),
      }),
    )
    if (job) {
      // Encargo conseguido: el proximo lleva una clave nueva.
      claveBiblia.conseguida()
      setJobId(job.id)
    }
  }

  const guardarEstilo = async () => {
    await action.run(() =>
      api.put(`/api/universes/${universeId}/bible/visual-style`, { style_key: estilo }),
    )
    await reload()
  }

  const guardarVoz = async () => {
    await action.run(() =>
      api.put(`/api/universes/${universeId}/bible/singing-voice`, {
        sex: voz.sex,
        apparent_age: voz.apparent_age,
        pitch: voz.pitch,
        timbre: voz.timbre,
        language_accent: voz.language_accent,
        singing_style: voz.singing_style,
      }),
    )
    await reload()
  }

  const guardarGeneros = async () => {
    await action.run(() =>
      api.put(`/api/universes/${universeId}/bible/genres`, {
        music_genres: generos,
        music_genre_free: mezcla,
      }),
    )
    await reload()
  }

  const analizarEnlace = async () => {
    const creada = await action.run(() =>
      api.post<Inspiration>(`/api/universes/${universeId}/bible/inspirations`, { url: enlace }),
    )
    if (creada) setEnlace('')
    await reload()
  }

  const guardarInspiraciones = async () => {
    await action.run(() =>
      api.put(`/api/universes/${universeId}/bible/inspirations`, {
        inspirations: inspiraciones,
      }),
    )
    await reload()
  }

  const quitarInspiracion = async (indice: number) => {
    await action.run(() =>
      api.del(`/api/universes/${universeId}/bible/inspirations/${indice}`),
    )
    await reload()
  }

  const setPreference = async (patch: Record<string, string>) => {
    await action.run(() => api.put(`/api/universes/${universeId}/bible/preferences`, patch))
    await reload()
  }

  return (
    <>
      <TopBar title="Identidad" back />
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
              <h3>Su estilo visual</h3>
              <p className="muted" style={{ margin: 0 }}>
                Queda fijo: su cara, las fotos de cada plano y los videos salen todos con este
                estilo. Si lo cambias despues de generar su cara, habra que rehacerla.
              </p>
              <ElegirEstilo valor={estilo} alCambiar={setEstilo} />
              {estilo === 'photo' && (
                <p className="muted">
                  {data.visual.photo_style_description
                    ? `Estilo leido de tu foto: ${data.visual.photo_style_description}`
                    : 'Sube una foto desde su ficha y elige «Copiar el estilo de mi foto» para leerlo.'}
                </p>
              )}
              {data.visual.master_stale && (
                <p className="error">
                  Su estilo cambio despues de generar su cara: esa cara esta desactualizada y hay
                  que rehacerla desde su ficha.
                </p>
              )}
              <button className="btn block" onClick={guardarEstilo} disabled={action.busy}>
                Guardar su estilo
              </button>
            </Card>

            <Card>
              <h3>Su voz cantada</h3>
              <p className="muted" style={{ margin: 0 }}>
                Esta descripcion se guarda como un solo texto y viaja palabra por palabra en cada
                letra y en cada encargo a Lyria de este artista, para que su voz salga lo mas
                parecida posible de cancion en cancion. Lyria no puede garantizar la misma voz
                exacta: esta descripcion fija es lo mas cerca que se puede llegar. Cambiarla solo
                afecta a las canciones futuras.
              </p>
              <Field label="Sexo de la voz" value={voz.sex} onChange={(v) => setVoz({ ...voz, sex: v })} placeholder="Mujer" />
              <Field label="Edad que se oye" value={voz.apparent_age} onChange={(v) => setVoz({ ...voz, apparent_age: v })} placeholder="Unos 25 anos" />
              <Field label="Grave o aguda" value={voz.pitch} onChange={(v) => setVoz({ ...voz, pitch: v })} placeholder="Media, mas bien grave" />
              <Field label="Timbre" value={voz.timbre} onChange={(v) => setVoz({ ...voz, timbre: v })} placeholder="Calida, con un poco de aire" />
              <Field label="Idioma y acento" value={voz.language_accent} onChange={(v) => setVoz({ ...voz, language_accent: v })} placeholder="Espanol neutro" />
              <Field label="Estilo de cantar" value={voz.singing_style} onChange={(v) => setVoz({ ...voz, singing_style: v })} placeholder="Intima en los versos, con fuerza en el coro" />
              {data.singing_voice.text && (
                <div>
                  <div className="muted">El texto que viaja a Lyria, tal cual:</div>
                  <pre className="prompt">{data.singing_voice.text}</pre>
                </div>
              )}
              <button className="btn block" onClick={guardarVoz} disabled={action.busy}>
                Guardar su voz
              </button>
            </Card>

            <Card>
              <h3>Sus generos</h3>
              <p className="muted" style={{ margin: 0 }}>
                Su combinacion fija. Cada cancion la hereda y puede ajustarla solo para ella.
              </p>
              <ElegirGeneros valor={generos} alCambiar={setGeneros} />
              <Field
                label="O escribe tu mezcla"
                value={mezcla}
                onChange={setMezcla}
                placeholder="Balada con guitarra de corrido y bateria de trap…"
              />
              {textoGeneros(generos, mezcla) && (
                <p className="muted">Suena a: {textoGeneros(generos, mezcla)}</p>
              )}
              <button className="btn block" onClick={guardarGeneros} disabled={action.busy}>
                Guardar sus generos
              </button>
            </Card>

            <Card>
              <h3>Sus referencias</h3>
              <p className="muted" style={{ margin: 0 }}>
                Pega enlaces de YouTube de canciones que te gusten. La app los escucha y guarda un
                resumen de su estilo —generos, ritmo, instrumentos, como esta escrita la letra— y
                ese resumen alimenta sus canciones. Siempre material original: no se copia ni la
                letra ni la melodia, y Lyria no puede oir el enlace ni clonar la voz de nadie.
              </p>
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
              {(data.inspirations_failed ?? []).length > 0 && (
                <div>
                  <p className="error" style={{ margin: 0 }}>
                    Estos enlaces no se pudieron analizar cuando se creo el artista:
                  </p>
                  {(data.inspirations_failed ?? []).map((enlaceFallido) => (
                    <div key={enlaceFallido} className="sub">
                      {enlaceFallido}
                    </div>
                  ))}
                  <p className="muted" style={{ margin: 0 }}>
                    Vuelve a pegar el que quieras en el campo de arriba y analizalo: al
                    entrar bien, sale de esta lista solo.
                  </p>
                </div>
              )}
              {inspiraciones.map((inspiracion, indice) => (
                <div key={`${inspiracion.url}-${indice}`} className="card">
                  <div className="row between">
                    <strong>{inspiracion.title || 'Cancion de referencia'}</strong>
                    <button
                      className="btn small ghost"
                      onClick={() => quitarInspiracion(indice)}
                      disabled={action.busy}
                    >
                      Quitar
                    </button>
                  </div>
                  <div className="sub">{inspiracion.url}</div>
                  {inspiracion.inspiration_usable === false && (
                    <>
                      <p className="error" style={{ margin: 0 }}>
                        Este resumen no viene de la cancion: vuelve a pegar el enlace.
                      </p>
                      <p className="muted" style={{ margin: 0 }}>
                        {inspiracion.inspiration_unusable_reason
                          ? `Motivo: ${inspiracion.inspiration_unusable_reason}. `
                          : ''}
                        Mientras tanto, no alimenta ninguna cancion.
                      </p>
                    </>
                  )}
                  <Field
                    label="Resumen de su estilo (editable: esto es lo que leen sus canciones)"
                    value={inspiracion.summary_text}
                    multiline
                    onChange={(v) =>
                      setInspiraciones(
                        inspiraciones.map((otra, i) =>
                          i === indice ? { ...otra, summary_text: v } : otra,
                        ),
                      )
                    }
                  />
                </div>
              ))}
              {inspiraciones.length > 0 && (
                <button className="btn block" onClick={guardarInspiraciones} disabled={action.busy}>
                  Guardar los resumenes
                </button>
              )}
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

            <p className="muted" style={{ margin: 0 }}>
              Esta ficha no se aprueba ni se edita a mano: los datos que
              tambien viven en otras fichas —como su edad, que vive en los
              rasgos de su ficha— se actualizan solos desde alli.
            </p>
          </>
        )}
      </main>
    </>
  )
}

function BibleSection({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values ?? {}).filter(
    ([key, value]) =>
      !['style_key', 'style_label', 'photo_style_description', 'master_stale'].includes(key) &&
      value !== null &&
      value !== '' &&
      !(Array.isArray(value) && value.length === 0),
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
