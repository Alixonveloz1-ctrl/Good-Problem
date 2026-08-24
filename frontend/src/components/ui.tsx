import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CanonStatus, JobState } from '../api/types'
import { StudioError } from '../api/client'

export function TopBar({ title, back, action }: { title: string; back?: boolean; action?: ReactNode }) {
  const navigate = useNavigate()
  return (
    <header className="topbar">
      {back && (
        <button className="back" onClick={() => navigate(-1)} aria-label="Volver">
          ‹
        </button>
      )}
      <h1>{title}</h1>
      {action}
    </header>
  )
}

export function Card({
  children,
  className = '',
  onClick,
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
}) {
  if (onClick) {
    return (
      <button className={`card tappable ${className}`} onClick={onClick} type="button">
        {children}
      </button>
    )
  }
  return <div className={`card ${className}`}>{children}</div>
}

export function StatusBadge({ status }: { status: CanonStatus | string | undefined }) {
  const map: Record<string, { className: string; label: string }> = {
    APPROVED: { className: 'approved', label: 'Aprobado' },
    DRAFT: { className: 'draft', label: 'Borrador' },
    REJECTED: { className: 'rejected', label: 'Rechazado' },
    ARCHIVED: { className: '', label: 'Archivado' },
  }
  const entry = map[status ?? 'DRAFT'] ?? { className: '', label: status ?? '—' }
  return <span className={`badge ${entry.className}`}>{entry.label}</span>
}

export function JobBadge({ state }: { state: JobState | string }) {
  const map: Record<string, { className: string; label: string }> = {
    QUEUED: { className: 'busy', label: 'En cola' },
    PROCESSING: { className: 'busy', label: 'Generando' },
    READY: { className: 'accent', label: 'Listo para revisar' },
    APPROVED: { className: 'approved', label: 'Aprobado' },
    REJECTED: { className: 'rejected', label: 'Rechazado' },
    FAILED: { className: 'rejected', label: 'Fallo' },
    CANCELLED: { className: '', label: 'Cancelado' },
  }
  const entry = map[state] ?? { className: '', label: state }
  return <span className={`badge ${entry.className}`}>{entry.label}</span>
}

export function ErrorNote({ error, onDismiss }: { error: StudioError | Error | null; onDismiss?: () => void }) {
  if (!error) return null
  const isApproval = error instanceof StudioError && error.code === 'approval_required'
  return (
    <div className="error" role="alert">
      <div className="row between">
        <strong>{isApproval ? 'Falta aprobar algo' : 'No se pudo hacer'}</strong>
        {onDismiss && (
          <button className="btn small ghost" onClick={onDismiss}>
            Cerrar
          </button>
        )}
      </div>
      <div>{error.message}</div>
    </div>
  )
}

export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="center-state">
      <div className="spinner" />
      <div>{label}</div>
    </div>
  )
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="center-state">
      <div style={{ fontSize: 15, color: 'var(--text)' }}>{title}</div>
      {hint && <div style={{ maxWidth: 280 }}>{hint}</div>}
      {action}
    </div>
  )
}

export function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  multiline?: boolean
  type?: string
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {multiline ? (
        <textarea
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          type={type}
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  )
}

export function Sheet({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  return (
    <div
      className="sheet-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <div className="grabber" />
        <div className="row between">
          <h2>{title}</h2>
          <button className="btn small ghost" onClick={onClose}>
            Cerrar
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

/** Borrar algo, con una confirmación que no se puede tocar por accidente.
 *
 * En un teléfono, un botón de borrar al lado de uno de abrir se pulsa sin
 * querer constantemente. Aquí hay que tocar dos veces: la primera cambia el
 * botón a "¿Seguro?" y arranca una cuenta atrás que lo devuelve a su sitio.
 * Sin esa vuelta atrás, un "¿Seguro?" olvidado en pantalla es una trampa que
 * espera al siguiente dedo.
 */
export function DeleteButton({
  onDelete,
  label = 'Borrar',
  confirmLabel = '¿Seguro?',
  busy = false,
}: {
  onDelete: () => void | Promise<void>
  label?: string
  confirmLabel?: string
  busy?: boolean
}) {
  const [armado, setArmado] = useState(false)

  useEffect(() => {
    if (!armado) return
    const reloj = setTimeout(() => setArmado(false), 4000)
    return () => clearTimeout(reloj)
  }, [armado])

  return (
    <button
      type="button"
      className={`btn small ${armado ? 'peligro' : 'ghost'}`}
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation()
        e.preventDefault()
        if (armado) {
          setArmado(false)
          void onDelete()
        } else {
          setArmado(true)
        }
      }}
    >
      {busy ? '…' : armado ? confirmLabel : label}
    </button>
  )
}
