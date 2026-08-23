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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  const payload = text ? JSON.parse(text) : null
  if (!response.ok) {
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
