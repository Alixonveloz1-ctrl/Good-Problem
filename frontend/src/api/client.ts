import type { ApiError } from './types'

export class StudioError extends Error {
  code: string
  details: Record<string, unknown>
  status: number

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.status = status
    this.code = error.code
    this.details = error.details ?? {}
  }
}

/** A new key per user gesture: a dropped connection must not bill twice. */
export function newIdempotencyKey(prefix = 'ui'): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2)
  return `${prefix}-${Date.now()}-${random}`
}

/** Avisos de que la sesion caduco.
 *
 * Una sesion de treinta dias se acaba alguna vez, y siempre a media faena. Sin
 * esto, la pantalla se llena de errores rojos que no dicen que hay que volver a
 * entrar. Con esto, la aplicacion vuelve sola a la puerta.
 */
type Listener = () => void
const oyentes = new Set<Listener>()

export function onUnauthorized(listener: Listener): () => void {
  oyentes.add(listener)
  return () => oyentes.delete(listener)
}

const PUERTA = '/api/auth/'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  const text = await response.text()
  const payload = text ? JSON.parse(text) : null
  if (!response.ok) {
    // Solo "sin_sesion" devuelve a la pantalla de entrada. Un 403 cualquiera
    // puede ser una regla del estudio -algo que todavia no se puede hacer- y
    // sacar al usuario por eso seria perder lo que estaba haciendo sin motivo.
    if (payload?.error?.code === 'sin_sesion' && !path.startsWith(PUERTA)) {
      oyentes.forEach((oyente) => oyente())
    }
    const error: ApiError = payload?.error ?? {
      code: 'http_error',
      message: payload?.detail ? String(payload.detail) : `Error ${response.status}`,
      details: {},
    }
    throw new StudioError(response.status, error)
  }
  return payload as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null
  if (path.startsWith('http') || path.startsWith('/')) return path
  return `/media/${path}`
}

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString('es-ES', { style: 'currency', currency: 'USD' })
}
