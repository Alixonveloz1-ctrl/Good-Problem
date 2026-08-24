import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Character } from '../api/types'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import { JobWatcher } from '../components/JobWatcher'
import { Empty, ErrorNote, Field, Loading, Sheet, StatusBadge, TopBar, DeleteButton } from '../components/ui'

export function CharactersScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Character[]>(
    `/api/universes/${universeId}/characters`,
  )
  const borrado = useAction()
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<Character | null>(null)
  const [name, setName] = useState('')
  const [appearance, setAppearance] = useState('')
  const action = useAction()

  const create = async () => {
    const created = await action.run(() =>
      api.post<Character>(`/api/universes/${universeId}/characters`, {
        name: name.trim(),
        appearance,
        role: (data ?? []).length === 0 ? 'lead' : 'supporting',
      }),
    )
    if (created) {
      setCreating(false)
      setName('')
      setAppearance('')
      await reload()
    }
  }

  return (
    <>
      <TopBar
        title="Personajes"
        back
        action={
          <button className="btn small primary" onClick={() => setCreating(true)}>
            Nuevo
          </button>
        }
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        <p className="muted" style={{ margin: 0 }}>
          El Character Master aprobado se adjunta como referencia en toda generacion posterior donde
          aparezca el personaje. Es lo que sostiene la consistencia visual.
        </p>

        {data && data.length === 0 && (
          <Empty
            title="Sin personajes"
            hint="Crea al menos el artista antes de las escenas."
            action={
              <button className="btn primary" onClick={() => setCreating(true)}>
                Crear personaje
              </button>
            }
          />
        )}

        <div className="list">
          {(data ?? []).map((character) => (
            <div key={character.id} className="card fila-borrable">
              <button type="button" className="grow destapado" onClick={() => setOpen(character)}>
                <div className="row between">
                  <strong>{character.name || 'Sin nombre'}</strong>
                  <StatusBadge status={character.status} />
                </div>
                <div className="sub">{character.appearance || 'Sin descripcion'}</div>
                <div className="row between muted">
                  <span>{character.role === 'lead' ? 'Protagonista' : 'Secundario'}</span>
                  <span>
                    {character.master_shots.filter((shot) => shot.storage_path).length}/
                    {character.master_shots.length} tomas
                  </span>
                </div>
              </button>
              <DeleteButton
                busy={borrado.busy}
                onDelete={async () => {
                  await borrado.run(() =>
                    api.del(`/api/universes/${universeId}/characters/${character.id}`),
                  )
                  await reload()
                }}
              />
            </div>
          ))}
        </div>
      </main>

      {creating && (
        <Sheet title="Nuevo personaje" onClose={() => setCreating(false)}>
          <Field label="Nombre" value={name} onChange={setName} placeholder="Nova" />
          <Field
            label="Apariencia"
            value={appearance}
            onChange={setAppearance}
            multiline
            placeholder="Pelo azul corto, ojos oscuros, complexion delgada…"
          />
          <ErrorNote error={action.error} onDismiss={action.clearError} />
          <button className="btn primary block" disabled={!name.trim()} onClick={create}>
            Crear
          </button>
        </Sheet>
      )}

      {open && (
        <CharacterSheet
          universeId={universeId}
          character={open}
          onClose={() => setOpen(null)}
          onChanged={async () => {
            await reload()
            setOpen(null)
          }}
        />
      )}
    </>
  )
}

function CharacterSheet({
  universeId,
  character,
  onClose,
  onChanged,
}: {
  universeId: string
  character: Character
  onClose: () => void
  onChanged: () => Promise<void>
}) {
  const action = useAction()
  const [choice, setChoice] = useState<ModelChoice | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [shotKey, setShotKey] = useState('portrait')

  const design = async () => {
    const job = await action.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/characters/${character.id}/design`, {
        brief: character.appearance,
        idempotency_key: newIdempotencyKey('design'),
      }),
    )
    if (job) setJobId(job.id)
  }

  const generateShot = async (key: string) => {
    setShotKey(key)
    const job = await action.run(() =>
      api.post<{ id: string }>(
        `/api/universes/${universeId}/characters/${character.id}/master/${key}`,
        {
          model: choice?.model,
          variant: choice?.variant,
          aspect_ratio: key === 'full_body' ? '9:16' : '1:1',
          idempotency_key: newIdempotencyKey('shot'),
        },
      ),
    )
    if (job) setJobId(job.id)
  }

  const approve = async () => {
    await action.run(() =>
      api.post(`/api/universes/${universeId}/characters/${character.id}/approve`),
    )
    await onChanged()
  }

  return (
    <Sheet title={character.name || 'Personaje'} onClose={onClose}>
      <ErrorNote error={action.error} onDismiss={action.clearError} />

      <button className="btn block" onClick={design} disabled={action.busy}>
        Pedir diseno al Director de casting
      </button>

      <ModelPicker kind="image" value={choice} onChange={setChoice} label="Modelo de imagen" />
      <p className="muted" style={{ margin: 0 }}>
        Conviene generar el Master con el modelo de mayor calidad: todo lo demas se apoya en el.
      </p>

      <div className="thumbs">
        {character.master_shots.map((shot) => {
          const url = mediaUrl(shot.storage_path)
          return (
            <button
              key={shot.key}
              type="button"
              className="variant"
              style={{ padding: 0, minHeight: 0, overflow: 'hidden' }}
              onClick={() => generateShot(shot.key)}
              disabled={action.busy}
            >
              {url ? (
                <img className="media square" src={url} alt={shot.label} />
              ) : (
                <div className="placeholder" style={{ minHeight: 96, border: 0 }}>
                  {shot.label}
                </div>
              )}
              <span className="price" style={{ padding: '4px 0' }}>
                {shot.storage_path ? 'Regenerar' : 'Generar'}
              </span>
            </button>
          )
        })}
      </div>

      {jobId && (
        <JobWatcher
          universeId={universeId}
          jobId={jobId}
          onReady={() => {
            setJobId(null)
            void onChanged()
          }}
        />
      )}

      <div className="muted">Ultima toma pedida: {shotKey}</div>

      <button className="btn ok block" onClick={approve} disabled={action.busy}>
        Aprobar Character Master
      </button>
    </Sheet>
  )
}
