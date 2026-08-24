import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Location, Outfit } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import {
  Card,
  DeleteButton,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Sheet,
  StatusBadge,
  TopBar,
} from '../components/ui'

const CATEGORIES = [
  'signature',
  'casual',
  'performance',
  'interview',
  'music_video',
  'night',
  'special',
]

export function WardrobeScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Outfit[]>(
    `/api/universes/${universeId}/wardrobe`,
  )
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('signature')
  const [choice, setChoice] = useState<ModelChoice | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const action = useAction()

  const create = async () => {
    const created = await action.run(() =>
      api.post<Outfit>(`/api/universes/${universeId}/wardrobe`, {
        name: name.trim(),
        description,
        category,
      }),
    )
    if (created) {
      setCreating(false)
      setName('')
      setDescription('')
      await reload()
    }
  }

  const generateImage = async (outfit: Outfit) => {
    const job = await action.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/wardrobe/${outfit.id}/image`, {
        model: choice?.model,
        variant: choice?.variant,
        aspect_ratio: '9:16',
        idempotency_key: newIdempotencyKey('fit'),
      }),
    )
    if (job) setJobId(job.id)
  }

  const approve = async (outfit: Outfit) => {
    await action.run(() => api.post(`/api/universes/${universeId}/wardrobe/${outfit.id}/approve`))
    await reload()
  }

  return (
    <>
      <TopBar
        title="Vestuario"
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
        <ModelPicker kind="image" value={choice} onChange={setChoice} label="Modelo de imagen" />

        {data && data.length === 0 && (
          <Empty title="Sin atuendos" hint="Signature, performance, interview, night…" />
        )}

        <div className="list">
          {(data ?? []).map((outfit) => (
            <Card key={outfit.id}>
              <div className="row between">
                <strong>{outfit.name}</strong>
                <div className="row">
                  <StatusBadge status={outfit.status} />
                  <DeleteButton
                    busy={action.busy}
                    onDelete={async () => {
                      await action.run(() =>
                        api.del(`/api/universes/${universeId}/wardrobe/${outfit.id}`),
                      )
                      await reload()
                    }}
                  />
                </div>
              </div>
              <div className="sub">{outfit.description}</div>
              <span className="badge">{outfit.category}</span>
              {outfit.image_path && (
                <img className="media" src={mediaUrl(outfit.image_path) ?? ''} alt={outfit.name} />
              )}
              <div className="btn-grid">
                <button className="btn small" onClick={() => generateImage(outfit)}>
                  {outfit.image_path ? 'Regenerar' : 'Generar imagen'}
                </button>
                <button className="btn small ok" onClick={() => approve(outfit)}>
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
        <Sheet title="Nuevo atuendo" onClose={() => setCreating(false)}>
          <Field label="Nombre" value={name} onChange={setName} />
          <Field label="Descripcion" value={description} onChange={setDescription} multiline />
          <div className="field">
            <label>Categoria</label>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
          <button className="btn primary block" disabled={!name.trim()} onClick={create}>
            Crear
          </button>
        </Sheet>
      )}
    </>
  )
}

export function LocationsScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Location[]>(
    `/api/universes/${universeId}/locations`,
  )
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [choice, setChoice] = useState<ModelChoice | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const action = useAction()

  const create = async () => {
    const created = await action.run(() =>
      api.post<Location>(`/api/universes/${universeId}/locations`, {
        name: name.trim(),
        description,
      }),
    )
    if (created) {
      setCreating(false)
      setName('')
      setDescription('')
      await reload()
    }
  }

  const generateImage = async (location: Location) => {
    const job = await action.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/locations/${location.id}/image`, {
        model: choice?.model,
        variant: choice?.variant,
        aspect_ratio: '16:9',
        idempotency_key: newIdempotencyKey('loc'),
      }),
    )
    if (job) setJobId(job.id)
  }

  const approve = async (location: Location) => {
    await action.run(() =>
      api.post(`/api/universes/${universeId}/locations/${location.id}/approve`),
    )
    await reload()
  }

  return (
    <>
      <TopBar
        title="Locaciones"
        back
        action={
          <button className="btn small primary" onClick={() => setCreating(true)}>
            Nueva
          </button>
        }
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />
        <ModelPicker kind="image" value={choice} onChange={setChoice} label="Modelo de imagen" />

        {data && data.length === 0 && (
          <Empty title="Sin locaciones" hint="Apartamento, estudio, azotea, calle, backstage…" />
        )}

        <div className="list">
          {(data ?? []).map((location) => (
            <Card key={location.id}>
              <div className="row between">
                <strong>{location.name}</strong>
                <div className="row">
                  <StatusBadge status={location.status} />
                  <DeleteButton
                    busy={action.busy}
                    onDelete={async () => {
                      await action.run(() =>
                        api.del(`/api/universes/${universeId}/locations/${location.id}`),
                      )
                      await reload()
                    }}
                  />
                </div>
              </div>
              <div className="sub">{location.description}</div>
              {location.reference_paths.length > 0 && (
                <div className="thumbs">
                  {location.reference_paths.map((path) => (
                    <img
                      key={path}
                      className="media square"
                      src={mediaUrl(path) ?? ''}
                      alt={location.name}
                    />
                  ))}
                </div>
              )}
              <div className="btn-grid">
                <button className="btn small" onClick={() => generateImage(location)}>
                  Generar referencia
                </button>
                <button className="btn small ok" onClick={() => approve(location)}>
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
        <Sheet title="Nueva locacion" onClose={() => setCreating(false)}>
          <Field label="Nombre" value={name} onChange={setName} placeholder="Rooftop" />
          <Field label="Descripcion" value={description} onChange={setDescription} multiline />
          <button className="btn primary block" disabled={!name.trim()} onClick={create}>
            Crear
          </button>
        </Sheet>
      )}
    </>
  )
}
