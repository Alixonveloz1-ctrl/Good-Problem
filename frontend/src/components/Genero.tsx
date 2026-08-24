const OPCIONES = ['mujer', 'hombre', 'no binario']

/**
 * Quién es, en un toque.
 *
 * Es el único dato que el Director tiene prohibido cambiar, y hasta ahora no
 * había dónde decirlo: el nombre "Feri" entraba y salía como "Leo Castillo"
 * porque nadie le había dicho nunca que era una artista.
 *
 * El elegido va en negro sobre blanco a propósito. Estaba con un borde oscuro
 * sobre gris claro y en un teléfono no se distinguía del que no está elegido,
 * así que parecía que no se podía elegir nada.
 */
export function ElegirGenero({
  value,
  onChange,
  label = 'Es',
}: {
  value: string
  onChange: (valor: string) => void
  label?: string
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <div className="opciones">
        {OPCIONES.map((cual) => (
          <button
            key={cual}
            type="button"
            className={`chip ${value === cual ? 'active' : ''}`}
            aria-pressed={value === cual}
            onClick={() => onChange(cual)}
          >
            {cual}
          </button>
        ))}
      </div>
    </div>
  )
}
