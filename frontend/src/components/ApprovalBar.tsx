import type { ReactNode } from 'react'

/** APPROVE / REGENERATE / EDIT / REJECT / SAVE TO CANON (PRD 36). */
export function ApprovalBar({
  status,
  busy,
  onApprove,
  onRegenerate,
  onEdit,
  onReject,
  extra,
}: {
  status?: string
  busy?: boolean
  onApprove?: () => void
  onRegenerate?: () => void
  onEdit?: () => void
  onReject?: () => void
  extra?: ReactNode
}) {
  if (!onApprove && !onRegenerate && !onEdit && !onReject && !extra) return null
  return (
    <div className="approval">
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
