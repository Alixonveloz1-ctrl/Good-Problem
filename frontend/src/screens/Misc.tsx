import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, money } from '../api/client'
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
      <TopBar title="Canon" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        <p className="muted" style={{ margin: 0 }}>
          Lo aprobado se convierte en Canon y se usa como contexto preferente y como imagen de
          referencia en las generaciones posteriores.
        </p>
        {data && data.length === 0 && <Empty title="El Canon esta vacio" />}
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
      <TopBar title="Export" back />
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

  return (
    <Card>
      <h3>Comprobar que el video no lleva audio</h3>
      <p className="muted" style={{ margin: 0 }}>
        La musica sale de Lyria y la voz de Chirp, asi que Veo se llama siempre con el audio
        apagado. Generarlo costaria el doble por segundo para tirarlo en el montaje. Aqui puedes
        comprobar que asi ha sido.
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
  const registry = useResource<Registry>('/api/registry/models')
  const health = useResource<{ dry_run: boolean; project: string | null; storage: string }>(
    '/api/health',
  )
  const action = useAction()

  return (
    <>
      <TopBar title="Ajustes" />
      <main className="screen">
        <ErrorNote error={action.error} onDismiss={action.clearError} />

        <Card>
          <h3>Registro de modelos</h3>
          <p className="muted" style={{ margin: 0 }}>
            Los modelos no son constantes del codigo: viven en un documento de Firestore. Cuando
            Google apague o anada uno, se edita ese documento sin desplegar nada.
          </p>
          {(registry.data?.models ?? []).map((model) => (
            <div key={model.id} className="row between">
              <span className="mono">{model.id}</span>
              <span className="muted">
                {model.variants
                  .map((variant) =>
                    variant.price !== undefined ? `${variant.key} ${money(variant.price)}` : variant.key,
                  )
                  .join(' · ')}
              </span>
            </div>
          ))}
          <button
            className="btn small block"
            onClick={async () => {
              await action.run(() => api.post('/api/registry/reload'))
              await registry.reload()
            }}
          >
            Recargar desde Firestore
          </button>
          {(registry.data?.excluded ?? []).map((entry) => (
            <div key={entry.id} className="notice">
              <strong className="mono">{entry.id}</strong>
              <div>{entry.reason}</div>
            </div>
          ))}
        </Card>

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

        <ModelosDeVerdad />

        <Cuenta />
      </main>
    </>
  )
}

type FilaModelo = { id: string; label: string; kind: string; exists: boolean | null }

/** Comprueba que los modelos del registro existen de verdad en Google.
 *
 * Esta pantalla existe por un error concreto: los IDs venian del PRD, que traia
 * nombres comerciales ("Veo 3.1") y no los identificadores que Vertex quiere
 * ("veo-3.1-generate-001"). Con un ID que no existe, cada generacion muere en
 * un 404 y aqui solo se veria un trabajo fallido sin explicacion.
 *
 * Preguntarselo a Google desde tu propio proyecto es la unica respuesta fiable,
 * y no cuesta nada.
 */
function ModelosDeVerdad() {
  const [filas, setFilas] = useState<FilaModelo[] | null>(null)
  const [comprobado, setComprobado] = useState(true)
  const accion = useAction()

  const marca = (existe: boolean | null) =>
    existe === true ? 'approved' : existe === false ? 'rejected' : 'draft'
  const texto = (existe: boolean | null) =>
    existe === true ? 'Existe' : existe === false ? 'NO EXISTE' : 'Sin comprobar'

  return (
    <Card>
      <h3>Comprobar los modelos</h3>
      <p className="muted" style={{ margin: 0 }}>
        Le pregunta a Google si cada modelo del registro existe con ese nombre. Si
        alguno sale en rojo, sus generaciones fallarian sin decir por que.
      </p>
      <button
        className="btn small block"
        onClick={async () => {
          const datos = await accion.run(() =>
            api.get<{ checked: boolean; models: FilaModelo[] }>('/api/diagnostics/models'),
          )
          if (datos) {
            setFilas(datos.models)
            setComprobado(datos.checked)
          }
        }}
      >
        {accion.busy ? 'Preguntando a Google...' : 'Comprobar'}
      </button>
      {filas && !comprobado && (
        <p className="muted" style={{ margin: 0 }}>
          En dry run no se le pregunta a Google, asi que no se puede saber.
        </p>
      )}
      {filas?.map((fila) => (
        <div key={fila.id} className="row between">
          <span className="mono">{fila.id}</span>
          <span className={`badge ${marca(fila.exists)}`}>{texto(fila.exists)}</span>
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
