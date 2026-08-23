import { useEffect, useRef, useState } from 'react'
import { api, money } from '../api/client'
import type { Job } from '../api/types'
import { JobBadge } from './ui'

/**
 * A job runs in Google Cloud whether or not this page stays open (PRD 6, 37).
 * This only polls for its state; closing Safari does not stop anything.
 */
export function JobWatcher({
  universeId,
  jobId,
  onReady,
}: {
  universeId: string
  jobId: string
  onReady?: (job: Job) => void
}) {
  const [job, setJob] = useState<Job | null>(null)

  // Parents pass an inline arrow here, so keeping it in the effect's
  // dependencies would restart the poll on every render of the parent.
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady

  useEffect(() => {
    let alive = true
    let timer = 0

    const poll = async () => {
      try {
        const next = await api.get<Job>(`/api/universes/${universeId}/jobs/${jobId}`)
        if (!alive) return
        setJob(next)
        if (next.state === 'QUEUED' || next.state === 'PROCESSING') {
          timer = window.setTimeout(poll, 2500)
        } else if (next.state === 'READY') {
          onReadyRef.current?.(next)
        }
      } catch {
        if (alive) timer = window.setTimeout(poll, 5000)
      }
    }

    void poll()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [universeId, jobId])

  if (!job) {
    return (
      <div className="notice row">
        <div className="spinner" /> <span>Enviando a la cola…</span>
      </div>
    )
  }

  return (
    <div className="notice">
      <div className="row between">
        <span className="mono">{job.kind}</span>
        <JobBadge state={job.state} />
      </div>
      <div className="row between">
        <span className="mono">{job.model}{job.variant ? ` · ${job.variant}` : ''}</span>
        <span>
          {job.state === 'READY' || job.state === 'APPROVED'
            ? money(job.actual_cost_usd)
            : `est. ${money(job.estimated_cost_usd)}`}
        </span>
      </div>
      {job.error && <div className="error" style={{ marginTop: 8 }}>{job.error}</div>}
    </div>
  )
}
