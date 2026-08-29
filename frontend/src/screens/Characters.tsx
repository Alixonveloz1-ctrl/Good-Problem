import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Character } from '../api/types'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import { JobWatcher } from '../components/JobWatcher'
import { Empty, ErrorNote, Field, Loading, Sheet, StatusBadge, TopBar, DeleteButton } from '../components/ui'
import { Proponer } from '../components/Proponer'
import { ElegirGenero } from '../components/Genero'
import { Rasgos } from '../components/Rasgos'

export function CharactersScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Character[]>(
    `/api/universes/${universeId}/characters`,
  )
  const borrado = useAction()
  const [creating, setCreating] = useState(false)
  const [abiertoId, setAbiertoId] = useState<string | null>(null)
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

  // Si el personaje se borro mientras estaba abierto, la ficha desaparece sola.
  const abierto = (data ?? []).find((c) => c.id === abiertoId) ?? null

  // El artista es SOLO el protagonista. Antes iban todos revueltos en la misma
  // lista, asi que un acompañante inventado parecia estar al mismo nivel que el
  // artista, y de ahi el "no se de donde salen estos personajes".
  const artista = (data ?? []).find((c) => c.role === 'lead') ?? null
  const secundarios = (data ?? []).filter((c) => c.role !== 'lead')

  const fila = (character: Character) => (
    <div key={character.id} className="card fila-borrable">
      <button
        type="button"
        className="grow destapado"
        onClick={() => setAbiertoId(character.id)}
      >
        <div className="row between">
          <strong>{character.name || 'Sin nombre'}</strong>
          <StatusBadge status={character.status} />
        </div>
        <div className="sub">{character.appearance || 'Todavía sin descripción'}</div>
        <div className="row between muted">
          <span>{character.gender || 'sin decir quién es'}</span>
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
  )

  return (
    <>
      <TopBar title="Personajes" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        <div className="section-title">El artista</div>
        {artista ? (
          <div className="list">{fila(artista)}</div>
        ) : (
          <Empty
            title="Todavía no hay artista"
            hint="Vuelve a su pantalla: ahí hay un botón para crearlo con el nombre que le pusiste."
          />
        )}

        {/* Los acompañantes se proponen a partir de quién es el artista, así
            que sin artista no hay de dónde sacarlos: era eso lo que llenaba la
            lista de gente inventada que no venía de ninguna parte. */}
        {artista && (
          <>
            <div className="section-title">Quien le acompaña</div>
            <p className="muted" style={{ margin: 0 }}>
              Los que salen con {artista.name || 'él'} en los videos. Su cara
              aprobada viaja como referencia en todo lo que se genere después:
              es lo que hace que sea siempre la misma persona.
            </p>

            <Proponer
              universeId={universeId}
              ruta="characters"
              cuantos={3}
              etiqueta={
                secundarios.length > 0
                  ? 'Que el estudio proponga más'
                  : 'Que el estudio proponga quién le acompaña'
              }
              onListo={reload}
            />

            {secundarios.length === 0 && (
              <Empty
                title="Todavía va solo"
                hint="El Director de casting los escribe a partir de quién es el artista."
              />
            )}
          </>
        )}

        <div className="list">{secundarios.map(fila)}</div>
      </main>

      <button className="btn small ghost block a-mano" onClick={() => setCreating(true)}>
        …o escribir uno a mano
      </button>

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

      {abierto && (
        <CharacterSheet
          universeId={universeId}
          character={abierto}
          onClose={() => setAbiertoId(null)}
          onChanged={reload}
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
  // Lo que no cabe en un boton: una cicatriz, un tatuaje, unas gafas.
  const [extra, setExtra] = useState('')

  const design = async () => {
    const job = await action.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/characters/${character.id}/design`, {
        brief: [character.appearance, extra].filter(Boolean).join('\n'),
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

  // Como es, decidido aqui. Lo que se elija manda sobre el Director; lo que se
  // deje en blanco lo decide el, que para eso esta.
  const guardar = async (patch: Record<string, unknown>) => {
    await action.run(() =>
      api.patch(`/api/universes/${universeId}/characters/${character.id}`, patch),
    )
    await onChanged()
  }

  const rasgos = character.rasgos ?? {}
  const elegidos = Object.values(rasgos).filter(Boolean).length

  return (
    <Sheet title={character.name || 'Personaje'} onClose={onClose}>
      <ErrorNote error={action.error} onDismiss={action.clearError} />

      <ElegirGenero
        value={character.gender ?? ''}
        onChange={(valor) => guardar({ gender: valor })}
      />
      {!character.gender && (
        <p className="muted" style={{ margin: 0 }}>
          Dilo antes de pedir el diseño. Si se queda en blanco lo decide el
          Director, y no acierta: de un nombre de mujer puede sacar un hombre.
        </p>
      )}

      <div className="section-title">Cómo es</div>
      <p className="muted" style={{ margin: 0 }}>
        Elige lo que tengas claro. Lo que dejes en blanco lo decide el Director
        de casting; lo que elijas no te lo cambia. Toca otra vez para quitarlo.
      </p>
      <Rasgos
        value={rasgos}
        ocupado={action.busy}
        onChange={(clave, valor) => guardar({ rasgos: { ...rasgos, [clave]: valor } })}
      />

      <Field
        label="Algo más"
        value={extra}
        onChange={setExtra}
        multiline
        placeholder="Un tatuaje en el cuello, cicatriz en la ceja, siempre con gafas de sol…"
      />

      <button
        className="btn block"
        onClick={design}
        disabled={action.busy || !character.gender}
      >
        {elegidos > 0
          ? `Que el Director lo termine (${elegidos} elegidos)`
          : 'Que lo diseñe entero el Director'}
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
