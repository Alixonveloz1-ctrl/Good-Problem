import { useParams } from 'react-router-dom'
import { api, money } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Job } from '../api/types'
import { Card, Empty, ErrorNote, JobBadge, Loading, TopBar } from '../components/ui'

export function JobsScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<Job[]>(
    `/api/universes/${universeId}/jobs?limit=100`,
    6000,
  )
  const action = useAction()

  return (
    <>
      <TopBar title="Jobs" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />
        <p className="muted" style={{ margin: 0 }}>
          Los jobs continuan en Google Cloud aunque cierres el iPhone. Un reintento usa el mismo
          modelo que se pidio.
        </p>

        {data && data.length === 0 && <Empty title="Sin jobs todavia" />}

        <div className="list">
          {(data ?? []).map((job) => (
            <Card key={job.id}>
              <div className="row between">
                <strong>{job.kind}</strong>
                <JobBadge state={job.state} />
              </div>
              <div className="row between muted">
                <span className="mono">
                  {job.model}
                  {job.variant ? ` · ${job.variant}` : ''}
                </span>
                <span>
                  {job.actual_cost_usd > 0
                    ? money(job.actual_cost_usd)
                    : `est. ${money(job.estimated_cost_usd)}`}
                </span>
              </div>
              <div className="muted mono">
                {job.target_type}/{job.target_id}
              </div>
              {job.error && <div className="error">{job.error}</div>}
              <div className="btn-grid">
                {job.state === 'FAILED' && (
                  <button
                    className="btn small"
                    disabled={action.busy}
                    onClick={async () => {
                      await action.run(() =>
                        api.post(`/api/universes/${universeId}/jobs/${job.id}/retry`),
                      )
                      await reload()
                    }}
                  >
                    Reintentar con {job.model}
                  </button>
                )}
                {(job.state === 'QUEUED' || job.state === 'PROCESSING') && (
                  <button
                    className="btn small danger"
                    disabled={action.busy}
                    onClick={async () => {
                      await action.run(() =>
                        api.post(`/api/universes/${universeId}/jobs/${job.id}/cancel`),
                      )
                      await reload()
                    }}
                  >
                    Cancelar
                  </button>
                )}
              </div>
            </Card>
          ))}
        </div>
      </main>
    </>
  )
}
