import type { ReactNode } from 'react'
import { money } from '../api/client'

/**
 * APPROVE / REGENERATE / EDIT / REJECT / SAVE TO CANON (PRD 36).
 *
 * The accumulated cost sits on the same screen as the regenerate button, on
 * purpose (PRD 44).
 */
export function ApprovalBar({
  status,
  costUsd,
  busy,
  onApprove,
  onRegenerate,
  onEdit,
  onReject,
  extra,
}: {
  status?: string
  costUsd?: number
  busy?: boolean
  onApprove?: () => void
  onRegenerate?: () => void
  onEdit?: () => void
  onReject?: () => void
  extra?: ReactNode
}) {
  return (
    <div className="approval">
      <div className="row between">
        <span className="muted">Gastado aqui</span>
        <span className="cost">{money(costUsd ?? 0)}</span>
      </div>
      <div className="btn-grid">
        {onApprove && (
          <button className="btn ok" onClick={onApprove} disabled={busy || status === 'APPROVED'}>
            Aprobar
          </button>
        )}
        {onRegenerate && (
          <button className="btn" onClick={onRegenerate} disabled={busy}>
            Regenerar
          </button>
        )}
        {onEdit && (
          <button className="btn ghost" onClick={onEdit} disabled={busy}>
            Editar
          </button>
        )}
        {onReject && (
          <button className="btn danger" onClick={onReject} disabled={busy}>
            Rechazar
          </button>
        )}
      </div>
      {extra}
    </div>
  )
}
