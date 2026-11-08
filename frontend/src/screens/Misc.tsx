import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { ExportPackage, Registry, Song } from '../api/types'
import { Card, Empty, ErrorNote, Field, Loading, TopBar } from '../components/ui'

export function CanonScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error } = useResource<
    { id: string; entity_type: string; label: string; note: string; status: string }[]
  >(`/api/universes/${universeId}/canon`)
  return (
    <>
      <TopBar title="En uso" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        <p className="muted" style={{ margin: 0 }}>
          Esto es lo que esta en uso ahora, y viaja como referencia en todo lo que se genere
          despues. Es lo que hace que el artista sea siempre el mismo. Nada entro aqui a mano:
          cada cosa entro sola, en el momento en que se genero.
        </p>
        {data && data.length === 0 && <Empty title="Todavia no hay material en uso" />}
        <div className="list">
          {(data ?? []).map((entry) => (
            <Card key={entry.id}>
              <div className="row between">
                <strong>{entry.label || entry.entity_type}</strong>
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

  // Se exporta lo que tiene audio generado: esa es la condicion, no un
  // estado de aprobacion.
  const cancionesConAudio = (songs.data ?? []).filter(
    (song) => song.approved_master_path || song.versions.length > 0,
  )

  return (
    <>
      <TopBar title="Descargas" back />
      <main className="screen">
        {exports.loading && !exports.data && <Loading />}
        <ErrorNote error={exports.error ?? action.error} onDismiss={action.clearError} />
        <p className="muted" style={{ margin: 0 }}>
          Todo se descarga desde el iPhone, listo para subir a mano.
        </p>

        {cancionesConAudio.length === 0 && (
          <Empty
            title="Nada que exportar"
            hint="Se exportan las canciones que ya tienen audio generado."
          />
        )}

        <div className="list">
          {cancionesConAudio.map((song) => (
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

        <ClaveGemini />

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
/** La clave de Gemini del dueño: la puerta de Lyria 3.5.
 *
 * La clave se escribe una vez y no se vuelve a ver: la pantalla solo
 * sabe si está puesta, nunca la muestra. Quitarla devuelve la música
 * a Lyria 3 Pro por la puerta de siempre.
 */
function ClaveGemini() {
  const ajustes = useResource<{ gemini_key_configured: boolean }>('/api/settings')
  const action = useAction()
  const [clave, setClave] = useState('')
  const puesta = ajustes.data?.gemini_key_configured ?? false

  const guardar = async () => {
    const hecho = await action.run(() =>
      api.put('/api/settings/gemini-key', { api_key: clave }),
    )
    if (hecho) {
      setClave('')
      await ajustes.reload()
    }
  }

  const quitar = async () => {
    const hecho = await action.run(() => api.del('/api/settings/gemini-key'))
    if (hecho) await ajustes.reload()
  }

  return (
    <Card>
      <h3>Clave de Gemini · Lyria 3.5</h3>
      <p className="muted" style={{ margin: 0 }}>
        Con tu clave de Gemini puesta, la música la canta <strong>Lyria 3.5</strong>, el
        modelo de la aplicación de Gemini. Sin clave, la canta Lyria 3 Pro, como hasta
        ahora. La clave la creas tú, gratis, en Google AI Studio (aistudio.google.com,
        botón «Get API key») y la pegas aquí: queda guardada en tu aplicación y no se
        vuelve a mostrar.
      </p>
      <p className="muted" style={{ margin: 0 }}>
        Estado:{' '}
        <strong>
          {puesta ? 'Clave puesta — canta Lyria 3.5' : 'Sin clave — canta Lyria 3 Pro'}
        </strong>
      </p>
      <Field
        label="Tu clave de Gemini"
        value={clave}
        onChange={setClave}
        placeholder="AIza…"
      />
      <ErrorNote error={action.error} onDismiss={action.clearError} />
      <div className="btn-grid">
        <button
          className="btn primary"
          onClick={guardar}
          disabled={action.busy || !clave.trim()}
        >
          Guardar la clave
        </button>
        {puesta && (
          <button className="btn" onClick={quitar} disabled={action.busy}>
            Quitar la clave
          </button>
        )}
      </div>
    </Card>
  )
}

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
