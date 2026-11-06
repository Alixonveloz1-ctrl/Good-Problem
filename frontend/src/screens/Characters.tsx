import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Character } from '../api/types'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import { JobWatcher } from '../components/JobWatcher'
import { Empty, ErrorNote, Field, Loading, Sheet, StatusBadge, TopBar, DeleteButton } from '../components/ui'
import { ElegirGenero } from '../components/Genero'
import { Rasgos, cuantosElegidos } from '../components/Rasgos'

/**
 * La ficha del artista. Solo hay uno por universo: no hay reparto ni lista de
 * acompañantes, porque cada universo ES un artista. Aqui se decide como es,
 * se genera o se sube su cara (el Master) y se aprueba; esa cara aprobada es
 * la referencia que viaja en cada plano de cada videoclip.
 */
export function CharactersScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Character[]>(
    `/api/universes/${universeId}/characters`,
  )
  const borrado = useAction()
  const [abiertoId, setAbiertoId] = useState<string | null>(null)

  const abierto = (data ?? []).find((c) => c.id === abiertoId) ?? null
  const artista = (data ?? []).find((c) => c.role === 'lead') ?? null

  return (
    <>
      <TopBar title="El artista" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        {artista ? (
          <div className="list">
            <div className="card fila-borrable">
              <button
                type="button"
                className="grow destapado"
                onClick={() => setAbiertoId(artista.id)}
              >
                <div className="row between">
                  <strong>{artista.name || 'Sin nombre'}</strong>
                  <StatusBadge status={artista.status} />
                </div>
                <div className="sub">{artista.appearance || 'Todavía sin descripción'}</div>
                <div className="row between muted">
                  <span>{artista.gender || 'sin decir quién es'}</span>
                  <span>
                    {artista.master_shots.filter((shot) => shot.storage_path).length}/
                    {artista.master_shots.length} tomas
                  </span>
                </div>
                {artista.master_stale && (
                  <div className="error">
                    Su estilo visual cambio: esta cara esta desactualizada y hay que rehacerla.
                  </div>
                )}
              </button>
              <DeleteButton
                busy={borrado.busy}
                onDelete={async () => {
                  await borrado.run(() =>
                    api.del(`/api/universes/${universeId}/characters/${artista.id}`),
                  )
                  await reload()
                }}
              />
            </div>
          </div>
        ) : (
          <Empty
            title="Todavía no hay artista"
            hint="Vuelve a su pantalla: ahí hay un botón para crearlo con el nombre que le pusiste."
          />
        )}
      </main>

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
  const [modoFoto, setModoFoto] = useState('use_as_master')
  const entradaFoto = useRef<HTMLInputElement>(null)

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

  const subirFoto = async (archivo: File) => {
    const form = new FormData()
    form.append('file', archivo)
    form.append('mode', modoFoto)
    if (choice?.model) form.append('model', choice.model)
    const resultado = await action.run(() =>
      api.upload<{ job?: { id: string } }>(
        `/api/universes/${universeId}/characters/${character.id}/photo`,
        form,
      ),
    )
    if (resultado?.job) setJobId(resultado.job.id)
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
  const elegidos = cuantosElegidos(rasgos)

  return (
    <Sheet title={character.name || 'El artista'} onClose={onClose}>
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

      <div className="section-title">Su foto</div>
      <p className="muted" style={{ margin: 0 }}>
        Si ya tienes una imagen suya, subela y elige que hacer con ella. Ojo: si la foto parece
        una persona real fotografiada, el filtro de Google a veces bloquea los clips de video;
        en ese caso, generar el retrato desde la foto es la salida.
      </p>
      <div className="field">
        <label>Qué hacer con la foto</label>
        <select value={modoFoto} onChange={(event) => setModoFoto(event.target.value)}>
          <option value="use_as_master">Usarla tal cual como su cara</option>
          <option value="base_for_master">Generar su cara desde la foto, en su estilo</option>
          <option value="copy_style">Copiar el estilo de la foto como su estilo visual</option>
        </select>
      </div>
      <input
        ref={entradaFoto}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={(event) => {
          const archivo = event.target.files?.[0]
          if (archivo) void subirFoto(archivo)
          event.target.value = ''
        }}
      />
      <button
        className="btn block"
        onClick={() => entradaFoto.current?.click()}
        disabled={action.busy}
      >
        {action.busy ? 'Subiendo…' : 'Subir una foto'}
      </button>
      {character.source_photo_path && (
        <img
          className="media square"
          src={mediaUrl(character.source_photo_path) ?? ''}
          alt="Foto subida"
        />
      )}

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
