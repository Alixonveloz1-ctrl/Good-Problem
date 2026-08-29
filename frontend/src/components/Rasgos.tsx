/**
 * Cómo es el artista, elegido por quien lo crea.
 *
 * "Esas son muy poquitas opciones. Las edades tienen que ser exactas, yo elegir
 * la edad exacta. Estilos tiene que haber muchísimos. Cuerpos también, que esos
 * son prácticamente a puro hombre; aquí hay de una mujer hermosa con curvas."
 *
 * La primera versión tenía cuatro opciones por fila y tramos de edad de diez
 * años. Con eso no se diseña a nadie: se elige entre cuatro plantillas. Un
 * artista se reconoce por lo que tiene de particular, y lo particular no cabe
 * en cuatro casillas.
 *
 * Aquí está el catálogo entero. Lo que se deje en blanco lo decide el Director
 * de casting —para eso está—, pero lo que se elige no se discute: viaja como
 * dado hasta el prompt de cada imagen y no lo puede cambiar.
 */

export type Rasgo = {
  clave: string
  label: string
  ayuda?: string
  opciones: string[]
  /** Varias a la vez: pecas Y tatuajes Y gafas. */
  multiple?: boolean
}

export const RASGOS: Rasgo[] = [
  {
    clave: 'piel',
    label: 'Piel',
    opciones: [
      'porcelana',
      'muy clara',
      'clara',
      'clara rosada',
      'beige',
      'dorada',
      'oliva',
      'canela',
      'bronceada',
      'morena clara',
      'morena',
      'morena oscura',
      'caoba',
      'negra',
      'negra profunda',
    ],
  },
  {
    clave: 'pelo_color',
    label: 'Color de pelo',
    opciones: [
      'negro',
      'negro azulado',
      'castaño oscuro',
      'castaño',
      'castaño claro',
      'caramelo',
      'rubio oscuro',
      'rubio',
      'rubio ceniza',
      'rubio platino',
      'pelirrojo',
      'cobrizo',
      'caoba',
      'canoso',
      'blanco',
      'gris plata',
      'azul',
      'turquesa',
      'verde',
      'rosa',
      'morado',
      'rojo fuego',
      'naranja',
      'bicolor',
      'mechas de color',
      'raíz oscura y puntas claras',
    ],
  },
  {
    clave: 'pelo_corte',
    label: 'Corte',
    opciones: [
      'rapado al cero',
      'rapado con dibujo',
      'buzz cut',
      'corto degradado',
      'corto con flequillo',
      'undercut',
      'mullet',
      'pixie',
      'bob',
      'bob asimétrico',
      'media melena',
      'melena por los hombros',
      'melena larga',
      'larguísimo hasta la cintura',
      'capas largas',
      'coleta alta',
      'coleta baja',
      'moño alto',
      'dos moños',
      'trenza',
      'trenzas pegadas',
      'box braids',
      'rastas',
      'afro',
      'twists',
      'rizos definidos',
      'rizos sueltos',
      'ondas',
      'liso planchado',
      'con flequillo recto',
      'con flequillo cortina',
    ],
  },
  {
    clave: 'cuerpo',
    label: 'Cuerpo',
    opciones: [
      'menuda',
      'delgada',
      'esbelta',
      'estilizada',
      'curvilínea',
      'con curvas marcadas',
      'voluptuosa',
      'reloj de arena',
      'atlética',
      'tonificada',
      'fibrada',
      'alta y delgada',
      'bajita y compacta',
      'delgado',
      'normal',
      'atlético',
      'musculoso',
      'muy musculado',
      'fuerte',
      'fornido',
      'corpulento',
      'robusto',
      'alto y espigado',
      'bajo y ancho',
    ],
  },
  {
    clave: 'estatura',
    label: 'Estatura',
    opciones: ['muy baja', 'baja', 'media', 'alta', 'muy alta'],
  },
  {
    clave: 'rostro',
    label: 'Rostro',
    opciones: [
      'ovalado',
      'redondo',
      'corazón',
      'cuadrado',
      'alargado',
      'diamante',
      'triangular',
      'pómulos altos',
      'mandíbula marcada',
      'facciones suaves',
      'facciones angulosas',
      'aniñado',
      'de rasgos duros',
    ],
  },
  {
    clave: 'ojos',
    label: 'Ojos',
    opciones: [
      'negros',
      'marrones oscuros',
      'marrones',
      'avellana',
      'ámbar',
      'miel',
      'verdes',
      'verde claro',
      'azules',
      'azul hielo',
      'grises',
      'heterocromía',
      'rasgados',
      'grandes y redondos',
      'almendrados',
      'caídos',
      'hundidos',
    ],
  },
  {
    clave: 'cejas',
    label: 'Cejas',
    opciones: ['finas', 'naturales', 'pobladas', 'rectas', 'arqueadas', 'decoloradas', 'partidas'],
  },
  {
    clave: 'labios',
    label: 'Labios',
    opciones: ['finos', 'medios', 'gruesos', 'muy gruesos', 'arco de cupido marcado'],
  },
  {
    clave: 'vello_facial',
    label: 'Vello facial',
    opciones: [
      'sin nada',
      'barba de tres días',
      'barba corta',
      'barba cerrada',
      'barba larga',
      'perilla',
      'bigote',
      'bigote y perilla',
      'patillas largas',
    ],
  },
  {
    clave: 'estilo',
    label: 'Estilo',
    ayuda: 'Cómo se viste y de dónde viene su imagen.',
    opciones: [
      'urbano',
      'streetwear',
      'trap',
      'reggaetón',
      'hip hop clásico',
      'drill',
      'afrobeat',
      'dancehall',
      'salsero',
      'bachatero',
      'flamenco',
      'ranchero',
      'norteño',
      'country',
      'western',
      'rockero',
      'metalero',
      'punk',
      'grunge',
      'emo',
      'gótico',
      'dark academia',
      'y2k',
      'noventero',
      'ochentero retro',
      'setentero',
      'disco',
      'glam',
      'futurista',
      'cyberpunk',
      'techwear',
      'espacial',
      'minimalista',
      'elegante',
      'alta costura',
      'sastrería',
      'bohemio',
      'hippie',
      'romántico',
      'kawaii',
      'k-pop',
      'anime',
      'deportivo',
      'skater',
      'surfero',
      'motero',
      'militar',
      'vaquero',
      'playero',
      'clásico',
    ],
  },
  {
    clave: 'actitud',
    label: 'Actitud',
    ayuda: 'Cómo mira a cámara.',
    opciones: [
      'seria',
      'desafiante',
      'misteriosa',
      'melancólica',
      'dulce',
      'alegre',
      'sensual',
      'fría',
      'cercana',
      'arrogante',
      'soñadora',
      'salvaje',
      'elegante',
      'tímida',
      'imponente',
    ],
  },
  {
    clave: 'detalles',
    label: 'Detalles',
    ayuda: 'Todos los que quieras.',
    multiple: true,
    opciones: [
      'pecas',
      'lunar en la cara',
      'cicatriz',
      'hoyuelos',
      'tatuajes en los brazos',
      'tatuajes en el cuello',
      'tatuajes en la cara',
      'tatuajes en las manos',
      'piercing en la nariz',
      'piercing en el labio',
      'piercing en la ceja',
      'pendientes de aro',
      'muchos pendientes',
      'gafas',
      'gafas de sol siempre',
      'dientes de oro',
      'uñas largas',
      'anillos en todos los dedos',
      'cadenas de oro',
      'gorra',
      'sombrero',
      'pañuelo en la cabeza',
      'vitiligo',
      'heterocromía',
      'diastema',
      'maquillaje marcado',
      'delineado negro',
      'sin maquillaje',
    ],
  },
]

/** La edad exacta. Un tramo de diez años no es elegir la edad. */
function Edad({
  valor,
  onChange,
  ocupado,
}: {
  valor: string
  onChange: (valor: string) => void
  ocupado: boolean
}) {
  const numero = Number(valor) || 0
  const mover = (cuanto: number) => {
    const siguiente = Math.min(90, Math.max(14, (numero || 25) + cuanto))
    onChange(String(siguiente))
  }
  return (
    <div className="field">
      <label>Edad</label>
      <div className="edad">
        <button type="button" className="chip" disabled={ocupado} onClick={() => mover(-1)}>
          −
        </button>
        <input
          type="number"
          inputMode="numeric"
          min={14}
          max={90}
          value={valor}
          placeholder="—"
          disabled={ocupado}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, 2))}
        />
        <button type="button" className="chip" disabled={ocupado} onClick={() => mover(1)}>
          +
        </button>
        {valor && (
          <button type="button" className="btn small ghost" disabled={ocupado} onClick={() => onChange('')}>
            Que la elija él
          </button>
        )}
      </div>
    </div>
  )
}

export function Rasgos({
  value,
  onChange,
  ocupado = false,
}: {
  value: Record<string, string>
  onChange: (clave: string, valor: string) => void
  ocupado?: boolean
}) {
  // Los de varias a la vez se guardan separados por coma: el documento sigue
  // siendo texto plano y se lee igual de bien en el prompt del Director.
  const marcados = (clave: string) =>
    (value[clave] || '').split(',').map((t) => t.trim()).filter(Boolean)

  const alternar = (rasgo: Rasgo, cual: string) => {
    if (!rasgo.multiple) {
      onChange(rasgo.clave, value[rasgo.clave] === cual ? '' : cual)
      return
    }
    const puestos = marcados(rasgo.clave)
    const siguiente = puestos.includes(cual)
      ? puestos.filter((t) => t !== cual)
      : [...puestos, cual]
    onChange(rasgo.clave, siguiente.join(', '))
  }

  return (
    <>
      <Edad valor={value.edad || ''} onChange={(v) => onChange('edad', v)} ocupado={ocupado} />
      {RASGOS.map((rasgo) => {
        const puestos = marcados(rasgo.clave)
        return (
          <div key={rasgo.clave} className="field">
            <label>{rasgo.label}</label>
            {rasgo.ayuda && <div className="sub">{rasgo.ayuda}</div>}
            <div className="opciones">
              {rasgo.opciones.map((cual) => {
                const puesto = puestos.includes(cual)
                return (
                  <button
                    key={cual}
                    type="button"
                    className={`chip ${puesto ? 'active' : ''}`}
                    aria-pressed={puesto}
                    disabled={ocupado}
                    // Volver a tocar lo quita: sin esto, una vez elegido no
                    // habría forma de devolvérselo al Director.
                    onClick={() => alternar(rasgo, cual)}
                  >
                    {cual}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}
    </>
  )
}

/** Cuántas cosas ha decidido ya, para decirlo en el botón. */
export function cuantosElegidos(rasgos: Record<string, string>): number {
  return Object.entries(rasgos).reduce((total, [, valor]) => {
    if (!valor) return total
    return total + valor.split(',').filter((t) => t.trim()).length
  }, 0)
}
