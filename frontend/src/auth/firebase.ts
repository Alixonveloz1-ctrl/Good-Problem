import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import {
  getAuth,
  getRedirectResult,
  GoogleAuthProvider,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type Auth,
} from 'firebase/auth'

/** Firebase en el navegador, configurado en caliente.
 *
 * La configuración no se incrusta al construir: cuando se construye la imagen,
 * el proyecto de Google puede no existir todavía, y llegarían valores vacíos al
 * navegador sin ningún error útil. Viene de /api/auth/config al abrir la app.
 */
export type ConfigWeb = {
  apiKey: string
  authDomain: string
  projectId: string
  appId?: string
  storageBucket?: string
  messagingSenderId?: string
}

let app: FirebaseApp | null = null

function arrancar(config: ConfigWeb): FirebaseApp {
  app ??= getApps().length > 0 ? getApps()[0]! : initializeApp(config)
  return app
}

function auth(config: ConfigWeb): Auth {
  return getAuth(arrancar(config))
}

function proveedor(): GoogleAuthProvider {
  const p = new GoogleAuthProvider()
  p.setCustomParameters({ prompt: 'select_account' })
  return p
}

/** Los fallos que significan "por aquí no, prueba por el otro camino". */
function hayQueRedirigir(error: unknown): boolean {
  const codigo =
    typeof error === 'object' && error !== null && 'code' in error
      ? String((error as { code: unknown }).code)
      : ''
  return (
    codigo === 'auth/popup-blocked' ||
    codigo === 'auth/operation-not-supported-in-this-environment' ||
    codigo === 'auth/cancelled-popup-request'
  )
}

/** Entra con Google y devuelve el token que el servidor va a comprobar.
 *
 * Primero por ventana emergente, que devuelve el token en el acto. Si el
 * navegador la bloquea se cae a la redirección: la página se va a Google y
 * vuelve. Safari en un iPhone bloquea las ventanas emergentes de serie, y
 * cuando la app está añadida a la pantalla de inicio directamente no existen,
 * así que este segundo camino no es un remedio raro: es el normal aquí.
 *
 * Devuelve null cuando se fue por redirección: no hay token todavía y la
 * página está a punto de irse. Lo recoge `recogerRedireccion` al volver.
 */
export async function entrarConGoogle(config: ConfigWeb): Promise<string | null> {
  const identidad = auth(config)
  try {
    const credencial = await signInWithPopup(identidad, proveedor())
    return await credencial.user.getIdToken()
  } catch (error) {
    if (!hayQueRedirigir(error)) throw error
    await signInWithRedirect(identidad, proveedor())
    return null
  }
}

/** Recoge la vuelta de Google cuando se entró por redirección.
 *
 * Devuelve el token, o null si esta carga no viene de una redirección, que es
 * lo normal.
 */
export async function recogerRedireccion(config: ConfigWeb): Promise<string | null> {
  try {
    const resultado = await getRedirectResult(auth(config))
    return resultado ? await resultado.user.getIdToken() : null
  } catch {
    // Una vuelta que no cuadra no es motivo para no pintar la pantalla de
    // entrada: se ignora y se ofrece entrar otra vez.
    return null
  }
}

export async function salir(config: ConfigWeb): Promise<void> {
  try {
    await signOut(auth(config))
  } catch {
    // Si Firebase no llegó a arrancar, no hay sesión que cerrar.
  }
}

/** Traduce los códigos de Firebase a algo que se entienda desde un teléfono. */
export function mensajeDeError(error: unknown): string {
  const codigo =
    typeof error === 'object' && error !== null && 'code' in error
      ? String((error as { code: unknown }).code)
      : ''

  switch (codigo) {
    case 'auth/popup-closed-by-user':
      return 'Cerraste la ventana antes de terminar. Toca otra vez.'
    case 'auth/unauthorized-domain':
      return 'Falta añadir esta dirección en Firebase → Authentication → Settings → Authorized domains.'
    case 'auth/operation-not-allowed':
      return 'Falta activar "Entrar con Google" en Firebase → Authentication → Sign-in method.'
    case 'auth/network-request-failed':
      return 'Sin conexión. Revisa la señal y vuelve a intentar.'
    default:
      return error instanceof Error ? error.message : 'No se pudo entrar. Vuelve a intentarlo.'
  }
}
