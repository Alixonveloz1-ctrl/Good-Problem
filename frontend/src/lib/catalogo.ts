/** Lo fijo del artista, tal y como lo conoce el servidor: los estilos
 *  visuales entre los que se elige uno, y los generos musicales que se pueden
 *  combinar (hasta tres principales). Las claves son las del servidor; las
 *  etiquetas son lo que se lee en el telefono. */

export interface EstiloVisual {
  key: string
  label: string
}

export const ESTILOS_VISUALES: EstiloVisual[] = [
  { key: 'realista', label: 'Realista fotográfico' },
  { key: 'anime_cinematografico', label: 'Anime cinematográfico' },
  { key: 'anime_clasico', label: 'Anime clásico años 90' },
  { key: 'anime_suave', label: 'Anime suave romántico' },
  { key: 'oleo', label: 'Óleo, pintura clásica' },
  { key: 'ilustracion', label: 'Ilustración digital pintada' },
  { key: 'tres_d', label: '3D tipo película animada' },
  { key: 'photo', label: 'El estilo de mi foto' },
]

export interface GeneroMusical {
  key: string
  label: string
}

export const GENEROS_MUSICALES: GeneroMusical[] = [
  { key: 'pop', label: 'Pop' },
  { key: 'rock', label: 'Rock' },
  { key: 'balada', label: 'Balada' },
  { key: 'bachata', label: 'Bachata' },
  { key: 'salsa', label: 'Salsa' },
  { key: 'merengue', label: 'Merengue' },
  { key: 'regueton', label: 'Reguetón' },
  { key: 'trap', label: 'Trap' },
  { key: 'rap', label: 'Rap / hip-hop' },
  { key: 'rnb', label: 'R&B' },
  { key: 'corridos', label: 'Corridos' },
  { key: 'regional', label: 'Ranchera / regional mexicano' },
  { key: 'cumbia', label: 'Cumbia' },
  { key: 'vallenato', label: 'Vallenato' },
  { key: 'electronica', label: 'Electrónica / EDM' },
  { key: 'synthwave', label: 'Synthwave' },
  { key: 'jazz', label: 'Jazz' },
  { key: 'blues', label: 'Blues' },
  { key: 'country', label: 'Country' },
  { key: 'metal', label: 'Metal' },
  { key: 'punk', label: 'Punk' },
  { key: 'indie', label: 'Indie' },
  { key: 'folk', label: 'Folk' },
  { key: 'flamenco', label: 'Flamenco' },
]

export const MAX_GENEROS = 3

export function etiquetaGenero(key: string): string {
  return GENEROS_MUSICALES.find((g) => g.key === key)?.label ?? key
}

export function textoGeneros(keys: string[], libre: string): string {
  const partes = keys.map(etiquetaGenero)
  if (libre.trim()) partes.push(libre.trim())
  return partes.join(' + ')
}
