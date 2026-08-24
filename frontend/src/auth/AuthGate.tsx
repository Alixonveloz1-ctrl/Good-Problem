import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, StudioError, onUnauthorized } from '../api/client'
import {
  entrarConGoogle,
  mensajeDeError,
  recogerRedireccion,
  type ConfigWeb,
} from './firebase'

type AuthConfig = {
  login_required: boolean
  firebase: Partial<ConfigWeb>
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
        <button
          className="primary"
          onClick={() => {
            setError(null)
            void preguntar()
          }}
        >
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

  return <Login firebase={config.firebase} onEntrar={preguntar} />
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

function Login({
  firebase,
  onEntrar,
}: {
  firebase: Partial<ConfigWeb>
  onEntrar: () => Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  const [entrando, setEntrando] = useState(false)
  const [comprobando, setComprobando] = useState(true)

  // Firebase Authentication sólo necesita estas tres. appId lo piden Analytics
  // e Installations, que esta app no lleva; exigirlo dejaría la entrada rota
  // esperando un dato que no hace falta.
  const listo = Boolean(firebase.apiKey && firebase.authDomain && firebase.projectId)

  const canjear = async (token: string) => {
    await api.post('/api/auth/session', { credential: token })
    await onEntrar()
  }

  // Al volver de Google por redirección, el token llega en esta carga y no en
  // una pulsación. Sin recogerlo aquí, la vuelta se pierde y la pantalla de
  // entrada aparece otra vez como si no hubiera pasado nada.
  useEffect(() => {
    if (!listo) {
      setComprobando(false)
      return
    }
    let vivo = true
    recogerRedireccion(firebase as ConfigWeb)
      .then(async (token) => {
        if (!vivo) return
        if (token) {
          setEntrando(true)
          await canjear(token)
        }
      })
      .catch((err) => {
        if (!vivo) return
        setError(err instanceof StudioError ? err.message : mensajeDeError(err))
      })
      .finally(() => {
        if (vivo) setComprobando(false)
      })
    return () => {
      vivo = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listo])

  const entrar = async () => {
    setEntrando(true)
    setError(null)
    try {
      const token = await entrarConGoogle(firebase as ConfigWeb)
      // null = se fue por redirección; la página está a punto de irse a Google.
      if (token) await canjear(token)
    } catch (err) {
      setError(err instanceof StudioError ? err.message : mensajeDeError(err))
      setEntrando(false)
    }
  }

  if (!listo) {
    return (
      <Portada>
        <p className="login-error" role="alert">
          Falta terminar la instalación: el estudio no tiene la configuración de
          Firebase. Vuelve a ejecutar ./setup.sh en Cloud Shell.
        </p>
      </Portada>
    )
  }

  return (
    <Portada>
      <p className="muted">Entra con la cuenta de Google del estudio.</p>
      <button
        className="primary block"
        disabled={entrando || comprobando}
        onClick={() => void entrar()}
      >
        {entrando ? 'Entrando…' : 'Entrar con Google'}
      </button>
      {error && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
    </Portada>
  )
}
