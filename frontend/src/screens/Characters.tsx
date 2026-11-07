import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Character } from '../api/types'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import { JobWatcher } from '../components/JobWatcher'
import { Empty, ErrorNote, Field, Loading, Sheet, TopBar, DeleteButton } from '../components/ui'
import { ElegirGenero } from '../components/Genero'
import { Rasgos, cuantosElegidos } from '../components/Rasgos'

/**
 * La ficha del artista. Solo hay uno por universo: no hay reparto ni lista de
 * acompañantes, porque cada universo ES un artista. Aqui se decide como es
 * y se genera o se sube su cara (el Master); esa cara, tal cual se genera,
 * queda en uso y es la referencia que viaja en cada plano de cada videoclip.
 * No hay nada que aprobar en ningun sitio de esta ficha.
 */
export function CharactersScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Character[]>(
    `/api/universes/${universeId}/characters`,
  )
  const [abiertoId, setAbiertoId] = useState<string | null>(null)

  const abierto = (data ?? []).find((c) => c.id === abiertoId) ?? null
  const artista = (data ?? []).find((c) => c.role === 'lead') ?? null

  // Su foto en la tarjeta es el retrato vigente, con su marca de version:
  // regenerar guarda en la misma ruta, y sin la marca el telefono seguiria
  // ensenando la foto anterior. Si ninguna toma tiene imagen todavia, la
  // tarjeta es solo el nombre: ni imagen rota ni hueco.
  const tomaConFoto =
    artista?.master_shots.find((toma) => toma.key === 'portrait' && toma.storage_path) ??
    artista?.master_shots.find((toma) => toma.storage_path)
  const fotoArtista = tomaConFoto
    ? mediaUrl(tomaConFoto.storage_path, tomaConFoto.version)
    : null

  return (
    <>
      <TopBar title="El artista" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        {artista ? (
          <div className="list">
            {/* Solo su foto y su nombre. La descripcion, el sexo y el conteo
                de tomas ya viven dentro de su ficha, y repetirlos aqui era
                ruido en una tarjeta que solo tiene que abrirla. Borrar
                tambien vive dentro, al final de la ficha. */}
            <button
              type="button"
              className="card tappable"
              onClick={() => setAbiertoId(artista.id)}
            >
              {fotoArtista && (
                <img
                  className="media square"
                  src={fotoArtista}
                  alt={artista.name || 'El artista'}
                />
              )}
              <strong>{artista.name || 'Sin nombre'}</strong>
            </button>
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
  // Su nombre se escribe aqui: esta ficha es su casa, y la identidad y
  // todo lo demas lo toman de aqui solos. Se guarda al salir del campo,
  // como el resto de esta ficha, que no tiene boton de guardar.
  const [nombre, setNombre] = useState(character.name ?? '')
  useEffect(() => setNombre(character.name ?? ''), [character.id])
  const [jobId, setJobId] = useState<string | null>(null)
  const [shotKey, setShotKey] = useState('portrait')
  // Lo que no cabe en un boton: una cicatriz, un tatuaje, unas gafas.
  const [extra, setExtra] = useState('')
  const [modoFoto, setModoFoto] = useState('use_as_master')
  const entradaFoto = useRef<HTMLInputElement>(null)
  // La foto que se esta mirando grande. Ver y generar son dos toques
  // distintos: mirar no debe lanzar (ni cobrar) ninguna generacion.
  const [visor, setVisor] = useState<{ url: string; label: string } | null>(null)

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

      <div
        onBlur={() => {
          const limpio = nombre.trim()
          if (limpio && limpio !== character.name) void guardar({ name: limpio })
        }}
      >
        <Field
          label="Su nombre"
          value={nombre}
          onChange={setNombre}
          placeholder="El nombre de tu artista"
        />
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Su nombre vive en esta ficha: la identidad y todo lo demás lo toman de
        aquí solos, sin que tengas que tocarlo en ningún otro sitio.
      </p>

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
          // La version va en la direccion: la imagen nueva se guarda en la
          // misma ruta que la vieja, y sin esta marca el telefono sigue
          // ensenando la copia anterior aunque el trabajo ya termino.
          const url = mediaUrl(shot.storage_path, shot.version)
          return (
            <div key={shot.key} className="variant shot-card">
              {url ? (
                <button
                  type="button"
                  className="shot-view"
                  onClick={() => setVisor({ url, label: shot.label })}
                  aria-label={`Ver grande: ${shot.label}`}
                >
                  <img className="media square" src={url} alt={shot.label} />
                </button>
              ) : (
                <div className="placeholder" style={{ minHeight: 96, border: 0 }}>
                  {shot.label}
                </div>
              )}
              <button
                type="button"
                className="btn small block"
                onClick={() => generateShot(shot.key)}
                disabled={action.busy}
              >
                {shot.storage_path ? 'Regenerar' : 'Generar'}
              </button>
            </div>
          )
        })}
      </div>

      {visor && (
        <div
          className="visor-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) setVisor(null)
          }}
        >
          <img className="visor-img" src={visor.url} alt={visor.label} />
          <div className="row between visor-bar">
            <span>{visor.label}</span>
            <button className="btn small" onClick={() => setVisor(null)}>
              Cerrar
            </button>
          </div>
        </div>
      )}

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

      {/* Borrar vive aqui, al final de la ficha: es el unico sitio donde se
          decide sobre el artista entero. En la tarjeta de la lista ya no
          esta. La misma confirmacion de dos toques de siempre: el primer
          toque arma el boton («¿Seguro?») y el segundo borra. */}
      <div className="row between">
        <span className="muted">Borrar a este artista</span>
        <DeleteButton
          busy={action.busy}
          onDelete={async () => {
            const hecho = await action.run(() =>
              api.del(`/api/universes/${universeId}/characters/${character.id}`),
            )
            if (hecho !== null) {
              onClose()
              await onChanged()
            }
          }}
        />
      </div>
    </Sheet>
  )
}
