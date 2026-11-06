import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { ExportPackage, Registry, Song } from '../api/types'
import { Card, Empty, ErrorNote, Loading, StatusBadge, TopBar } from '../components/ui'

export function CanonScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error } = useResource<
    { id: string; entity_type: string; label: string; note: string; status: string }[]
  >(`/api/universes/${universeId}/canon`)
  return (
    <>
      <TopBar title="Aprobado" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        <p className="muted" style={{ margin: 0 }}>
          Lo que apruebas queda fijado, y a partir de ahí viaja como referencia en todo lo que se
          genere después. Es lo que hace que el artista sea siempre el mismo.
        </p>
        {data && data.length === 0 && <Empty title="Todavía no has aprobado nada" />}
        <div className="list">
          {(data ?? []).map((entry) => (
            <Card key={entry.id}>
              <div className="row between">
                <strong>{entry.label || entry.entity_type}</strong>
                <StatusBadge status={entry.status} />
              </div>
              <div className="muted">{entry.entity_type}</div>
              {entry.note && <div className="sub">{entry.note}</div>}
            </Card>
          ))}
        </div>
      </main>
    </>
  )
}

export function ExportsScreen() {
  const { universeId = '' } = useParams()
  const exports = useResource<ExportPackage[]>(`/api/universes/${universeId}/exports`)
  const songs = useResource<Song[]>(`/api/universes/${universeId}/songs`)
  const action = useAction()

  const approvedSongs = (songs.data ?? []).filter((song) => song.status === 'APPROVED')

  return (
    <>
      <TopBar title="Descargas" back />
      <main className="screen">
        {exports.loading && !exports.data && <Loading />}
        <ErrorNote error={exports.error ?? action.error} onDismiss={action.clearError} />
        <p className="muted" style={{ margin: 0 }}>
          Todo se descarga desde el iPhone, listo para subir a mano.
        </p>

        {approvedSongs.length === 0 && (
          <Empty title="Nada que exportar" hint="Solo se exportan canciones aprobadas." />
        )}

        <div className="list">
          {approvedSongs.map((song) => (
            <Card key={song.id}>
              <strong>{song.title}</strong>
              <button
                className="btn primary block"
                disabled={action.busy}
                onClick={async () => {
                  await action.run(() =>
                    api.post(`/api/universes/${universeId}/exports/songs/${song.id}`),
                  )
                  await exports.reload()
                }}
              >
                Generar paquete
              </button>
            </Card>
          ))}
        </div>

        {(exports.data ?? []).map((pkg) => (
          <Card key={pkg.id}>
            <div className="row between">
              <strong>{pkg.root_path}</strong>
              <span className="muted">{pkg.files.length} archivos</span>
            </div>
            {pkg.tree && <pre className="block">{pkg.tree}</pre>}
            {pkg.archive_url && (
              <a className="btn primary block" href={pkg.archive_url} download>
                Descargar .zip a Files
              </a>
            )}
            <div className="list">
              {pkg.files.map((file) => (
                <a key={file.package_path} className="btn small block" href={file.url} download>
                  {file.folder}/{file.name}
                </a>
              ))}
            </div>
          </Card>
        ))}
      </main>
    </>
  )
}

/**
 * La comprobacion del paso 27 del PRD: que ninguna llamada a Veo haya pedido
 * audio. Generarlo costaria el doble por segundo para producir una pista que el
 * montaje tira, asi que conviene poder mirarlo sin fiarse de nadie.
 */
function ComprobacionAudio() {
  const [abierto, setAbierto] = useState(false)
  const [resultado, setResultado] = useState<{ count: number; audio: number } | null>(null)
  const action = useAction()

  const comprobar = async () => {
    const datos = await action.run(() =>
      api.get<{ count: number; calls_requesting_audio: number }>(
        '/api/diagnostics/vertex-calls?prefix=veo',
      ),
    )
    if (datos) setResultado({ count: datos.count, audio: datos.calls_requesting_audio })
  }

  if (!abierto) {
    return (
      <button className="btn small block ghost" onClick={() => setAbierto(true)}>
        Comprobar el audio del video
      </button>
    )
  }

  return (
    <Card>
      <div className="row between">
        <h3 style={{ margin: 0 }}>Comprobar el audio del video</h3>
        <button className="btn small ghost" onClick={() => setAbierto(false)}>
          Cerrar
        </button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        La musica sale de Lyria, asi que Veo se llama siempre
        con el audio apagado y el montaje lo tiraria igual. Aqui se comprueba
        que asi ha sido.
      </p>
      <button className="btn block" onClick={comprobar} disabled={action.busy}>
        {action.busy ? 'Mirando…' : 'Comprobar'}
      </button>
      {resultado && (
        <div
          className={resultado.audio === 0 ? 'notice' : 'error'}
          style={resultado.audio === 0 ? { borderColor: 'var(--ok)', color: 'var(--ok)' } : {}}
        >
          {resultado.count === 0
            ? 'Todavia no se ha llamado a Veo en esta sesion.'
            : resultado.audio === 0
              ? `${resultado.count} llamadas a Veo, ninguna pidio audio.`
              : `Atencion: ${resultado.audio} de ${resultado.count} llamadas pidieron audio.`}
        </div>
      )}
    </Card>
  )
}

export function SettingsScreen() {
  const health = useResource<{ dry_run: boolean; project: string | null; storage: string }>(
    '/api/health',
  )
  const action = useAction()

  return (
    <>
      <TopBar title="Ajustes" />
      <main className="screen">
        <ErrorNote error={action.error} onDismiss={action.clearError} />

        <RegistroDeModelos />

        <ComprobacionAudio />

        {health.data && (
          <Card>
            <h3>Entorno</h3>
            <div className="row between">
              <span className="muted">Proyecto</span>
              <span className="mono">{health.data.project ?? 'local'}</span>
            </div>
            <div className="row between">
              <span className="muted">Almacenamiento</span>
              <span className="mono">{health.data.storage}</span>
            </div>
            <div className="row between">
              <span className="muted">Modo</span>
              <span className={`badge ${health.data.dry_run ? 'draft' : 'approved'}`}>
                {health.data.dry_run ? 'Dry run, no se gasta' : 'En produccion'}
              </span>
            </div>
          </Card>
        )}

        <Cuenta />
      </main>
    </>
  )
}

/** El registro de modelos, plegado.
 *
 * Es un panel de mantenimiento: se abre el dia que Google apaga o anade un
 * modelo, y ese dia no es hoy. Desplegado ocupaba la pantalla entera de
 * Ajustes con una lista que no se toca nunca.
 */
function RegistroDeModelos() {
  const [abierto, setAbierto] = useState(false)
  const registro = useResource<Registry>(abierto ? '/api/registry/models' : null)
  const accion = useAction()

  if (!abierto) {
    return (
      <button className="btn small block ghost" onClick={() => setAbierto(true)}>
        Modelos de IA
      </button>
    )
  }

  return (
    <Card>
      <div className="row between">
        <h3 style={{ margin: 0 }}>Modelos de IA</h3>
        <button className="btn small ghost" onClick={() => setAbierto(false)}>
          Cerrar
        </button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        No son constantes del codigo: viven en un documento de Firestore. Cuando
        Google apague o anada uno, se edita ese documento sin desplegar nada.
      </p>
      {(registro.data?.models ?? []).map((model) => (
        <div key={model.id} className="row between">
          <span className="mono">{model.id}</span>
          <span className="muted">{model.variants.map((v) => v.key).join(' · ')}</span>
        </div>
      ))}
      <button
        className="btn small block"
        onClick={async () => {
          await accion.run(() => api.post('/api/registry/reload'))
          await registro.reload()
        }}
      >
        Recargar desde Firestore
      </button>
      {(registro.data?.excluded ?? []).map((entry) => (
        <div key={entry.id} className="notice">
          <strong className="mono">{entry.id}</strong>
          <div>{entry.reason}</div>
        </div>
      ))}
    </Card>
  )
}

/** Quien esta dentro, y como salir.
 *
 * Salir importa mas de lo que parece en un telefono: es lo que se hace cuando
 * se presta el movil, y sin un boton la unica forma seria esperar treinta dias
 * a que caduque la sesion.
 */
function Cuenta() {
  const yo = useResource<{ login_required: boolean; email: string | null }>(
    '/api/auth/config',
  )
  if (!yo.data?.login_required) return null
  return (
    <Card>
      <h3>Cuenta</h3>
      <div className="row between">
        <span className="muted">Entraste como</span>
        <span className="mono">{yo.data.email ?? '—'}</span>
      </div>
      <button
        className="btn small block"
        onClick={async () => {
          await api.post('/api/auth/logout')
          window.location.reload()
        }}
      >
        Salir
      </button>
    </Card>
  )
}
