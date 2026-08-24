import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api, StudioError, onUnauthorized } from '../api/client'
import { loadGoogle } from './google'

type AuthConfig = {
  login_required: boolean
  client_id: string
  needs_setup: boolean
  signed_in: boolean
  email: string | null
}

/** La puerta, del lado del navegador.
 *
 * Envuelve la aplicación entera: mientras no se sepa quién entra no se pinta
 * nada de dentro. No es la seguridad —esa está en el servidor, que es el único
 * sitio donde vale— sino lo que evita que la aplicación arranque, pida datos y
 * llene la pantalla de errores rojos antes de que a nadie le hayan preguntado
 * quién es.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  const preguntar = useCallback(async () => {
    try {
      setConfig(await api.get<AuthConfig>('/api/auth/config'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo hablar con el estudio.')
    }
  }, [])

  useEffect(() => {
    void preguntar()
  }, [preguntar])

  // Una sesión de treinta días caduca alguna vez, y siempre a media faena. Al
  // primer 403 se vuelve a la puerta en lugar de dejar la pantalla llena de
  // errores que no explican nada.
  useEffect(
    () =>
      onUnauthorized(() => {
        setConfig((actual) => (actual ? { ...actual, signed_in: false } : actual))
      }),
    [],
  )

  if (error) {
    return (
      <Portada>
        <p className="muted">{error}</p>
        <button className="primary" onClick={() => { setError(null); void preguntar() }}>
          Reintentar
        </button>
      </Portada>
    )
  }

  if (!config) {
    return (
      <Portada>
        <p className="muted">Abriendo el estudio…</p>
      </Portada>
    )
  }

  if (!config.login_required || config.signed_in) return <>{children}</>
  if (config.needs_setup) return <Instalacion onListo={preguntar} />

  return <Login clientId={config.client_id} onEntrar={preguntar} />
}

/** El último paso de la instalación, hecho desde el propio teléfono.
 *
 * Google no publica ninguna API para crear un cliente OAuth de tipo web ni para
 * añadirle orígenes de JavaScript: hay que crearlo a mano en la consola. Lo que
 * sale de ahí son setenta caracteres, y Cloud Shell en un móvil no deja pegar.
 * Aquí sí, porque esto es una página normal.
 */
function Instalacion({
  onListo,
  corrigiendo = false,
}: {
  onListo: () => Promise<void>
  corrigiendo?: boolean
}) {
  const [clientId, setClientId] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  const guardar = async () => {
    setGuardando(true)
    setError(null)
    try {
      await api.post('/api/auth/setup', { client_id: clientId.trim(), code: code.trim() })
      await onListo()
    } catch (err) {
      setError(err instanceof StudioError ? err.message : 'No se pudo guardar.')
      setGuardando(false)
    }
  }

  return (
    <Portada>
      <p className="muted">
        {corrigiendo
          ? 'Pega otra vez el Client ID. Y comprueba que este origen esté en la lista de la consola:'
          : 'Último paso. Pega aquí el Client ID que creaste en Google Cloud.'}
      </p>
      <Origen />
      <input
        className="login-input"
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
        placeholder="…apps.googleusercontent.com"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        inputMode="url"
      />
      <input
        className="login-input"
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        placeholder="Código de Cloud Shell"
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        maxLength={12}
      />
      <button
        className="primary block"
        disabled={guardando || clientId.trim().length < 20 || code.trim().length < 6}
        onClick={() => void guardar()}
      >
        {guardando ? 'Guardando…' : corrigiendo ? 'Guardar' : 'Terminar instalación'}
      </button>
      {error && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
    </Portada>
  )
}

function Portada({ children }: { children: ReactNode }) {
  return (
    <div className="login">
      <div className="login-card">
        <div className="login-mark">🎬</div>
        <h1>Universe Studio</h1>
        {children}
      </div>
    </div>
  )
}

/** La dirección que Google pide como "origen autorizado".
 *
 * Escribirla a mano en la consola desde un teléfono es donde se falla: una
 * letra de más y el botón de Google no aparece nunca, sin decir por qué.
 */
function Origen() {
  const [copiado, setCopiado] = useState(false)
  const origen = window.location.origin
  return (
    <div className="login-origen">
      <code>{origen}</code>
      <button
        className="btn small"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(origen)
            setCopiado(true)
            setTimeout(() => setCopiado(false), 2000)
          } catch {
            // Safari sólo deja copiar desde un gesto y sobre https. Si no
            // puede, el texto sigue ahí para seleccionarlo a mano.
            setCopiado(false)
          }
        }}
      >
        {copiado ? 'Copiado' : 'Copiar'}
      </button>
    </div>
  )
}

function Login({ clientId, onEntrar }: { clientId: string; onEntrar: () => Promise<void> }) {
  const boton = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [entrando, setEntrando] = useState(false)
  const [mudo, setMudo] = useState(false)
  const [corrigiendo, setCorrigiendo] = useState(false)

  // Fuera de la carga del script a propósito: si la petición a Google se queda
  // colgada —una conexión mala en un móvil, un proxy de por medio— el .then()
  // no llega nunca y sin esto la tarjeta se queda muda para siempre.
  useEffect(() => {
    const reloj = setTimeout(() => {
      if (boton.current && boton.current.childElementCount === 0) setMudo(true)
    }, 8000)
    return () => clearTimeout(reloj)
  }, [])

  useEffect(() => {
    let vivo = true

    const canjear = async (credential: string) => {
      if (!vivo) return
      setEntrando(true)
      setError(null)
      try {
        await api.post('/api/auth/session', { credential })
        await onEntrar()
      } catch (err) {
        setError(
          err instanceof StudioError ? err.message : 'No se pudo entrar. Inténtalo otra vez.',
        )
        setEntrando(false)
      }
    }

    loadGoogle()
      .then(() => {
        if (!vivo || !boton.current || !window.google) return
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (respuesta) => void canjear(respuesta.credential),
          cancel_on_tap_outside: false,
        })
        window.google.accounts.id.renderButton(boton.current, {
          type: 'standard',
          theme: 'filled_black',
          size: 'large',
          text: 'continue_with',
          shape: 'pill',
          locale: 'es',
        })

      })
      .catch((err: Error) => vivo && setError(err.message))

    return () => {
      vivo = false
    }
  }, [clientId, onEntrar])

  if (corrigiendo) return <Instalacion onListo={onEntrar} corrigiendo />

  return (
    <Portada>
      <p className="muted">Entra con la cuenta de Google del estudio.</p>
      <div ref={boton} className="login-boton" />
      {entrando && <p className="muted">Entrando…</p>}
      {error && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
      {mudo && !error && (
        <>
          <p className="login-error" role="alert">
            El botón de Google no aparece. Puede ser la conexión, o que este
            origen no esté en la lista del cliente de OAuth.
          </p>
          <Origen />
        </>
      )}
      <button className="btn small" onClick={() => setCorrigiendo(true)}>
        Cambiar el Client ID
      </button>
    </Portada>
  )
}
