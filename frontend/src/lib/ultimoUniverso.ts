/** El último artista abierto, recordado entre visitas.
 *
 * Sin esto, dos de las cuatro pestañas de abajo no llevan a ningún sitio
 * mientras estás en Inicio: Música y Video necesitan saber de qué artista, y
 * desde Inicio nadie se lo ha dicho todavía. Dos botones muertos de cuatro, en
 * la primera pantalla que se ve.
 */
const CLAVE = 'aaus_ultimo_universo'

export function recordarUniverso(id: string): void {
  if (!id) return
  try {
    localStorage.setItem(CLAVE, id)
  } catch {
    // Navegación privada, o almacenamiento lleno. Se pierde la comodidad, no
    // la aplicación.
  }
}

export function ultimoUniverso(): string | null {
  try {
    return localStorage.getItem(CLAVE)
  } catch {
    return null
  }
}
