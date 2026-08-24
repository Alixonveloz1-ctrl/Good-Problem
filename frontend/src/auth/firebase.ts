import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
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

/** Entra con Google y devuelve el token que el servidor va a comprobar.
 *
 * Ventana emergente y no redirección, a propósito: el dominio donde Google
 * pregunta (…firebaseapp.com) no es el de la app (…run.app), y los navegadores
 * que bloquean almacenamiento de terceros rompen el camino por redirección
 * justo en el móvil, que es donde se va a usar esto.
 */
export async function entrarConGoogle(config: ConfigWeb): Promise<string> {
  const proveedor = new GoogleAuthProvider()
  proveedor.setCustomParameters({ prompt: 'select_account' })
  const credencial = await signInWithPopup(auth(config), proveedor)
  return credencial.user.getIdToken()
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
    case 'auth/cancelled-popup-request':
      return 'Cerraste la ventana antes de terminar. Toca otra vez.'
    case 'auth/popup-blocked':
      return 'El navegador bloqueó la ventana. Permite ventanas emergentes para este sitio.'
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
