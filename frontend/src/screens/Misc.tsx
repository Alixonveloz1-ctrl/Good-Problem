import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, money } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Budget, ExportPackage, Registry, Song } from '../api/types'
import { CreditMeter } from '../components/CreditMeter'
import { Card, Empty, ErrorNote, Field, Loading, StatusBadge, TopBar } from '../components/ui'

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

export function SettingsScreen() {
  const budget = useResource<Budget>('/api/budget')
  const registry = useResource<Registry>('/api/registry/models')
  const health = useResource<{ dry_run: boolean; project: string | null; storage: string }>(
    '/api/health',
  )
  const action = useAction()
  const [total, setTotal] = useState('')
  const [started, setStarted] = useState('')

  return (
    <>
      <TopBar title="Ajustes" />
      <main className="screen">
        <ErrorNote error={action.error} onDismiss={action.clearError} />
        {budget.data && <CreditMeter budget={budget.data} />}

        <Card>
          <h3>Presupuesto</h3>
          <Field
            label="Techo total en USD"
            value={total}
            onChange={setTotal}
            type="number"
            placeholder={String(budget.data?.total_usd ?? 300)}
          />
          <Field
            label="Fecha de alta del credito (AAAA-MM-DD)"
            value={started}
            onChange={setStarted}
            placeholder={budget.data?.credit_started_on ?? '2026-08-23'}
          />
          <div className="muted">
            El credito de bienvenida caduca a los 90 dias del alta de la cuenta, se use o no. Pon
            aqui la fecha real para que la cuenta atras sirva.
          </div>
          <button
            className="btn block"
            disabled={action.busy}
            onClick={async () => {
              const patch: Record<string, unknown> = {}
              if (total) patch.total_usd = Number(total)
              if (started) patch.credit_started_on = started
              await action.run(() => api.patch('/api/budget', patch))
              await budget.reload()
            }}
          >
            Guardar
          </button>
          <div className="muted">
            Al alcanzar el techo, los trabajos nuevos se rechazan. No es solo un aviso.
          </div>
        </Card>

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
      </main>
    </>
  )
}
