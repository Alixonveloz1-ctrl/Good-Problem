import { ESTILOS_VISUALES, GENEROS_MUSICALES, MAX_GENEROS } from '../lib/catalogo'

/** Elegir el estilo visual del artista: uno solo, y queda fijo. */
export function ElegirEstilo({
  valor,
  alCambiar,
}: {
  valor: string
  alCambiar: (key: string) => void
}) {
  return (
    <div className="chips">
      {ESTILOS_VISUALES.map((estilo) => (
        <button
          key={estilo.key}
          type="button"
          className={valor === estilo.key ? 'chip active' : 'chip'}
          onClick={() => alCambiar(estilo.key)}
        >
          {estilo.label}
        </button>
      ))}
    </div>
  )
}

/** Elegir la combinacion de generos: hasta tres principales, tocando para
 *  sumar o quitar. La mezcla propia escrita va en su propio campo. */
export function ElegirGeneros({
  valor,
  alCambiar,
}: {
  valor: string[]
  alCambiar: (keys: string[]) => void
}) {
  const tocar = (key: string) => {
    if (valor.includes(key)) {
      alCambiar(valor.filter((g) => g !== key))
    } else if (valor.length < MAX_GENEROS) {
      alCambiar([...valor, key])
    }
  }
  return (
    <div>
      <div className="chips">
        {GENEROS_MUSICALES.map((genero) => (
          <button
            key={genero.key}
            type="button"
            className={valor.includes(genero.key) ? 'chip active' : 'chip'}
            onClick={() => tocar(genero.key)}
          >
            {genero.label}
          </button>
        ))}
      </div>
      <p className="hint">
        {valor.length}/{MAX_GENEROS} generos principales. Toca para combinar: la mezcla es lo
        que oye Lyria.
      </p>
    </div>
  )
}
