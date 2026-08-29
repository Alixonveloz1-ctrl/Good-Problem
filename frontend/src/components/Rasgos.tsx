/**
 * Cómo es el artista, elegido por quien lo crea.
 *
 * "Dices que o decido yo o lo decide el director, pero yo no tengo la opción
 * para decidir. No puedo elegir entre unas opciones de características, pelo,
 * piel, cuerpo, nada."
 *
 * Tenía razón: la única decisión que quedaba era el nombre, y todo lo demás lo
 * inventaba el Director. Aquí se elige de verdad, con un toque por rasgo.
 *
 * Lo que se deja en blanco lo sigue decidiendo el Director —para eso está—,
 * pero lo que se elige no se discute: viaja como dado hasta el prompt de cada
 * imagen y no lo puede cambiar.
 */

export const RASGOS: { clave: string; label: string; opciones: string[] }[] = [
  { clave: 'edad', label: 'Edad', opciones: ['18-24', '25-34', '35-44', '45+'] },
  { clave: 'piel', label: 'Piel', opciones: ['muy clara', 'clara', 'morena', 'oscura'] },
  {
    clave: 'pelo',
    label: 'Pelo',
    opciones: ['negro', 'castaño', 'rubio', 'pelirrojo', 'teñido', 'canoso'],
  },
  { clave: 'corte', label: 'Corte', opciones: ['rapado', 'corto', 'media melena', 'largo'] },
  { clave: 'cuerpo', label: 'Cuerpo', opciones: ['delgado', 'atlético', 'fuerte', 'corpulento'] },
  {
    clave: 'estilo',
    label: 'Estilo',
    opciones: ['urbano', 'callejero', 'elegante', 'rockero', 'futurista', 'clásico'],
  },
]

export function Rasgos({
  value,
  onChange,
  ocupado = false,
}: {
  value: Record<string, string>
  onChange: (clave: string, valor: string) => void
  ocupado?: boolean
}) {
  return (
    <>
      {RASGOS.map((rasgo) => (
        <div key={rasgo.clave} className="field">
          <label>{rasgo.label}</label>
          <div className="opciones">
            {rasgo.opciones.map((cual) => {
              const puesto = value[rasgo.clave] === cual
              return (
                <button
                  key={cual}
                  type="button"
                  className={`chip ${puesto ? 'active' : ''}`}
                  aria-pressed={puesto}
                  disabled={ocupado}
                  // Volver a tocar el elegido lo quita: sin esto, una vez
                  // elegido no habria forma de devolvérselo al Director.
                  onClick={() => onChange(rasgo.clave, puesto ? '' : cual)}
                >
                  {cual}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </>
  )
}
