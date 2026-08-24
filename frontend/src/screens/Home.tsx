import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Home as HomeData } from '../api/types'
import {
  Card,
  DeleteButton,
  Empty,
  ErrorNote,
  Field,
  JobBadge,
  Loading,
  Sheet,
  TopBar,
} from '../components/ui'

export function HomeScreen() {
  const { data, loading, error, reload } = useResource<HomeData>('/api/home', 8000)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const action = useAction()

  const create = async () => {
    const created = await action.run(() => api.post('/api/universes', { name: name.trim() }))
    if (created) {
      setCreating(false)
      setName('')
      await reload()
    }
  }

  return (
    <>
      <TopBar
        title="Universe Studio"
        action={
          <button className="btn small primary" onClick={() => setCreating(true)}>
            Nuevo
          </button>
        }
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />

        {data && (
          <>
            {data.pending_approvals.length > 0 && (
              <>
                <div className="section-title">Esperando tu decision</div>
                <div className="list">
                  {data.pending_approvals.map((item) => (
                    <Link
                      key={item.job_id}
                      to={`/u/${item.universe_id}/jobs`}
                      className="card tappable"
                    >
                      <div className="row between">
                        <strong>{describeTarget(item.kind, item.target_type)}</strong>
                        <span className="badge accent">Revisar</span>
                      </div>
                      <div className="row between muted">
                        <span>{item.universe_name}</span>
                        <span className="mono">{item.model}</span>
                      </div>
                      <div className="muted mono">{item.target_id}</div>
                    </Link>
                  ))}
                </div>
              </>
            )}

            {data.active_jobs.length > 0 && (
              <>
                <div className="section-title">Generando ahora</div>
                <div className="list">
                  {data.active_jobs.map((job) => (
                    <Card key={job.id}>
                      <div className="row between">
                        <strong>{describeTarget(job.kind, job.target_type)}</strong>
                        <JobBadge state={job.state} />
                      </div>
                      <div className="muted mono">{job.model}</div>
                      <div className="muted">
                        Continua en Google Cloud aunque cierres el iPhone.
                      </div>
                    </Card>
                  ))}
                </div>
              </>
            )}

            <div className="section-title">Artistas</div>
            {data.universes.length === 0 ? (
              <Empty
                title="Todavia no hay ningun artista"
                hint="Cada artista vive en su propio Universe: identidad, personaje, canciones y videoclips."
                action={
                  <button className="btn primary" onClick={() => setCreating(true)}>
                    Crear el primero
                  </button>
                }
              />
            ) : (
              <div className="list">
                {data.universes.map((universe) => (
                  <div key={universe.id} className="card fila-borrable">
                    <Link to={`/u/${universe.id}`} className="grow">
                      <strong>{universe.name}</strong>
                      {universe.tagline && <div className="sub">{universe.tagline}</div>}
                    </Link>
                    {/* Borrar un artista se lleva por delante sus canciones,
                        sus videoclips y todo lo aprobado. La confirmación lo
                        dice: "¿Seguro?" no basta cuando lo que se va es todo. */}
                    <DeleteButton
                      confirmLabel="¿Borrar todo?"
                      busy={action.busy}
                      onDelete={async () => {
                        await action.run(() => api.del(`/api/universes/${universe.id}`))
                        await reload()
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {creating && (
        <Sheet title="Nuevo artista" onClose={() => setCreating(false)}>
          <Field
            label="Nombre artistico"
            value={name}
            onChange={setName}
            placeholder="Nova"
          />
          <ErrorNote error={action.error} onDismiss={action.clearError} />
          <button
            className="btn primary block"
            disabled={!name.trim() || action.busy}
            onClick={create}
          >
            {action.busy ? 'Creando…' : 'Crear Universe'}
          </button>
          <p className="muted" style={{ margin: 0 }}>
            Se crea vacio: identidad, personaje, vestuario y locaciones se construyen despues, cada
            uno con su aprobacion.
          </p>
        </Sheet>
      )}
    </>
  )
}

function describeTarget(kind: string, targetType: string): string {
  const kinds: Record<string, string> = {
    text: 'Propuesta del Director',
    image: 'Imagen',
    video: 'Clip de video',
    music: 'Cancion',
    speech: 'Voz hablada',
    assembly: 'Ensamblaje',
  }
  const targets: Record<string, string> = {
    song: 'cancion',
    scene: 'escena',
    character: 'personaje',
    wardrobe: 'vestuario',
    location: 'locacion',
    video_project: 'videoclip',
    content: 'contenido',
    artist_bible: 'Artist Bible',
  }
  const base = kinds[kind] ?? kind
  const target = targets[targetType]
  // "Cancion · cancion" reads badly: skip the target when the kind names it.
  if (!target || base.toLowerCase().includes(target.toLowerCase())) return base
  return `${base} · ${target}`
}
