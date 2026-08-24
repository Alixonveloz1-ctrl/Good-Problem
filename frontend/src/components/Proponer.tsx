import { useState } from 'react'
import { api } from '../api/client'
import { useAction } from '../hooks/useApi'
import { ErrorNote } from './ui'
import { JobWatcher } from './JobWatcher'

/**
 * Que lo proponga el estudio.
 *
 * Antes, para tener un atuendo había que crearlo a mano: escribir un nombre,
 * una descripción y elegir una categoría. Y otro. Y otro. Lo mismo con las
 * locaciones y con los personajes. Para eso no hacen falta directores.
 *
 * Aquí se les pide la tanda entera y ellos la escriben, a partir de quién es el
 * artista. Lo que sobre se borra de un toque, que es mucho menos trabajo que
 * escribirlo.
 */
export function Proponer({
  universeId,
  ruta,
  etiqueta,
  cuantos = 4,
  onListo,
}: {
  universeId: string
  ruta: 'wardrobe' | 'locations' | 'characters'
  etiqueta: string
  cuantos?: number
  onListo: () => void | Promise<void>
}) {
  const [jobId, setJobId] = useState<string | null>(null)
  const accion = useAction()

  const pedir = async () => {
    const trabajo = await accion.run(() =>
      api.post<{ id: string }>(`/api/universes/${universeId}/${ruta}/propose`, {
        count: cuantos,
      }),
    )
    if (trabajo) setJobId(trabajo.id)
  }

  return (
    <>
      <button className="btn primary block" onClick={pedir} disabled={accion.busy || !!jobId}>
        {accion.busy || jobId ? 'El estudio está en ello…' : etiqueta}
      </button>
      <ErrorNote error={accion.error} onDismiss={accion.clearError} />
      {jobId && (
        <JobWatcher
          universeId={universeId}
          jobId={jobId}
          onReady={() => {
            setJobId(null)
            void onListo()
          }}
        />
      )}
    </>
  )
}
