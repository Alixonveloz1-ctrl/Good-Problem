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

/** Lo que se espera a una respuesta antes de darla por perdida.
 *
 * Sin esto, una peticion que no vuelve deja la pantalla girando para siempre:
 * sin datos, sin error y sin nada que hacer. Paso en la portada, y media hora
 * despues seguia diciendo "Cargando…". Un error se lee y se arregla; un giro
 * infinito solo se sufre. */
const ESPERA_MS = 45_000

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const corte = new AbortController()
  const reloj = setTimeout(() => corte.abort(), ESPERA_MS)
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal: corte.signal,
    })
  } catch (caught) {
    if ((caught as Error)?.name === 'AbortError') {
      throw new StudioError(504, {
        code: 'sin_respuesta',
        message: 'El estudio tardó demasiado en contestar. Vuelve a intentarlo.',
        details: {},
      })
    }
    throw caught
  } finally {
    clearTimeout(reloj)
  }
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

  /** Subir un archivo (la foto del artista). Mismo trato de errores que el
   *  resto: si el estudio contesta mal, se lee el mismo mensaje de siempre. */
  upload: async <T>(path: string, form: FormData): Promise<T> => {
    const response = await fetch(path, {
      method: 'POST',
      body: form,
      credentials: 'same-origin',
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
  },
}

export function mediaUrl(
  path: string | null | undefined,
  version?: number | null,
): string | null {
  if (!path) return null
  const base =
    path.startsWith('http') || path.startsWith('/') ? path : `/media/${path}`
  // Una imagen que se regenera se guarda en la misma ruta que la anterior.
  // Sin una marca distinta, el telefono pinta la copia que ya tiene guardada
  // y la nueva no se ve nunca: la version de la toma es esa marca.
  if (version == null || version <= 0) return base
  return `${base}${base.includes('?') ? '&' : '?'}v=${version}`
}
