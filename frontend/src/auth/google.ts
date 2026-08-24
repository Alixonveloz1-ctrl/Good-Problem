/** El botón de Google, cargado sólo cuando hace falta.
 *
 * El script vive en los servidores de Google y no se puede empaquetar: es él
 * quien abre la ventana de Google, recoge la identidad y devuelve un token
 * firmado. Se carga aquí y no en el index.html para que quien ya tiene sesión
 * abierta no pague por descargarlo cada vez que abre la aplicación.
 */

const FUENTE = 'https://accounts.google.com/gsi/client'

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(options: {
            client_id: string
            callback: (respuesta: { credential: string }) => void
            auto_select?: boolean
            cancel_on_tap_outside?: boolean
          }): void
          renderButton(
            parent: HTMLElement,
            options: {
              type?: 'standard' | 'icon'
              theme?: 'outline' | 'filled_blue' | 'filled_black'
              size?: 'small' | 'medium' | 'large'
              text?: 'signin_with' | 'signup_with' | 'continue_with'
              shape?: 'rectangular' | 'pill'
              locale?: string
              width?: number
            },
          ): void
          disableAutoSelect(): void
        }
      }
    }
  }
}

let pendiente: Promise<void> | null = null

export function loadGoogle(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve()
  if (pendiente) return pendiente

  pendiente = new Promise<void>((resolve, reject) => {
    const existente = document.querySelector<HTMLScriptElement>(`script[src="${FUENTE}"]`)
    const script = existente ?? document.createElement('script')
    script.src = FUENTE
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      // Que se reintente en la siguiente pulsación: en un móvil con mala
      // cobertura el primer intento se cae y el segundo entra.
      pendiente = null
      script.remove()
      reject(new Error('No se pudo cargar el botón de Google. Revisa la conexión.'))
    }
    if (!existente) document.head.appendChild(script)
  })
  return pendiente
}
