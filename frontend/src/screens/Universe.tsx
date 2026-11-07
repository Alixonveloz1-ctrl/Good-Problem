import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, mediaUrl } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Character, Universe } from '../api/types'
import { DeleteButton, ErrorNote, Loading, TopBar } from '../components/ui'

/**
 * La pantalla del artista.
 *
 * "No sé ni por dónde empezar ni qué crear ni qué ver. No puedo hacer nada
 * porque no se entiende nada."
 *
 * Era un índice de once puertas sin ningún orden entre ellas. Un índice no
 * dice qué hacer: eso lo dice quien ya sabe el camino. En la versión
 * simplificada el estudio es solo esto: el artista, su identidad, su música
 * y sus videoclips.
 *
 * Ahora manda una sola cosa: qué toca AHORA, con su porqué y su botón. El
 * camino no cambia nunca —quién es, su cara, su música, su videoclip— y cada
 * paso necesita el anterior de verdad, así que enseñar los cuatro a la vez es
 * enseñar tres callejones sin salida.
 *
 * Lo demás sigue estando, debajo y en pequeño, para cuando ya se sabe adónde
 * se va.
 */

type Paso = {
  clave: string
  titulo: string
  porque: string
  ir_a: string
  accion: string
  boton: string
}

type UniverseConPaso = Universe & { siguiente?: Paso }

const MUNDO = [
  { to: 'characters', label: 'El artista', hint: 'Su cara, su foto y su ficha' },
  { to: 'bible', label: 'Identidad', hint: 'Su estilo, su voz cantada, sus géneros y sus referencias' },
]

const PRODUCCION = [
  { to: 'songs', label: 'Música', hint: 'Concepto, letra y canción' },
  { to: 'projects', label: 'Videoclips', hint: 'Historia, planos y montaje' },
]

const TECNICO = [
  { to: 'jobs', label: 'En marcha' },
  { to: 'canon', label: 'En uso' },
  { to: 'exports', label: 'Descargas' },
]

function Fila({ base, to, label, hint }: { base: string; to: string; label: string; hint: string }) {
  return (
    <Link to={`${base}/${to}`} className="card tappable">
      <div className="row">
        <div className="grow">
          <strong>{label}</strong>
          <div className="sub">{hint}</div>
        </div>
        <span className="muted">›</span>
      </div>
    </Link>
  )
}

/** El artista: su cara y su nombre. Nunca un secundario haciendo de artista. */
function Retrato({ artista, nombre }: { artista: Character | null; nombre: string }) {
  // Su cara es el RETRATO vigente, con su marca de version: regenerar
  // guarda en la misma ruta, y sin la marca el telefono seguiria
  // ensenando la foto anterior, que ya ni es la del artista.
  const tomas = artista?.master_shots ?? []
  const foto =
    tomas.find((toma) => toma.key === 'portrait' && toma.storage_path) ??
    tomas.find((toma) => toma.storage_path)
  return (
    <div className="card presenta">
      {foto ? (
        <img
          className="presenta-foto"
          src={mediaUrl(foto.storage_path, foto.version) ?? ''}
          alt={nombre}
        />
      ) : (
        <div className="presenta-hueco">{(nombre || '?').trim().charAt(0).toUpperCase()}</div>
      )}
      <div className="row between" style={{ width: '100%' }}>
        <h2 style={{ margin: 0 }}>{artista?.name || nombre}</h2>
      </div>
    </div>
  )
}

/** Qué toca ahora: una sola cosa, con su porqué y su botón. */
function AhoraToca({
  base,
  paso,
  onCrearArtista,
  ocupado,
}: {
  base: string
  paso: Paso
  onCrearArtista: () => void
  ocupado: boolean
}) {
  return (
    <div className="ahora">
      <div className="ahora-etiqueta">Ahora toca</div>
      <h3 className="ahora-titulo">{paso.titulo}</h3>
      <p className="ahora-porque">{paso.porque}</p>
      {paso.accion === 'crear_artista' ? (
        <button className="btn primary block" onClick={onCrearArtista} disabled={ocupado}>
          {ocupado ? 'Creando…' : paso.boton}
        </button>
      ) : (
        <Link to={`${base}/${paso.ir_a}`} className="btn primary block">
          {paso.boton}
        </Link>
      )}
    </div>
  )
}

export function UniverseScreen() {
  const { universeId = '' } = useParams()
  const base = `/u/${universeId}`
  const navegar = useNavigate()
  const universo = useResource<UniverseConPaso>(`/api/universes/${universeId}`)
  const personajes = useResource<Character[]>(`/api/universes/${universeId}/characters`)
  const accion = useAction()

  // Solo el protagonista es el artista. Antes, si no lo habia, se cogia el
  // primer personaje de la lista: por eso un acompañante inventado aparecia
  // presidiendo la pantalla como si fuera el artista.
  const artista = (personajes.data ?? []).find((p) => p.role === 'lead') ?? null
  const paso = universo.data?.siguiente
  const nombre = universo.data?.name ?? 'Artista'

  const crearArtista = async () => {
    const hecho = await accion.run(() => api.post(`/api/universes/${universeId}/artista`))
    if (hecho) {
      await universo.reload()
      await personajes.reload()
    }
  }

  return (
    <>
      <TopBar title={nombre} back />
      <main className="screen">
        {universo.loading && !universo.data && <Loading />}
        <ErrorNote error={universo.error} />
        <ErrorNote error={personajes.error} />
        <ErrorNote error={accion.error} onDismiss={accion.clearError} />

        {universo.data && (
          <>
            <Retrato artista={artista} nombre={nombre} />
            {universo.data.tagline && <p className="muted lema">{universo.data.tagline}</p>}

            {paso && (
              <AhoraToca
                base={base}
                paso={paso}
                onCrearArtista={crearArtista}
                ocupado={accion.busy}
              />
            )}

            <div className="section-title">Producir</div>
            <div className="list">
              {PRODUCCION.map((s) => (
                <Fila key={s.to} base={base} {...s} />
              ))}
            </div>

            <div className="section-title">Su mundo</div>
            <div className="list">
              {MUNDO.map((s) => (
                <Fila key={s.to} base={base} {...s} />
              ))}
            </div>

            <div className="tecnico">
              {TECNICO.map((s) => (
                <Link key={s.to} to={`${base}/${s.to}`} className="btn small ghost">
                  {s.label}
                </Link>
              ))}
            </div>

            {/* Borrar el artista se hace desde dentro del artista, no desde la
                portada: es donde se ve lo que se va por delante —sus canciones,
                sus videoclips y todo lo que tiene en uso— y donde no se roza
                sin querer al buscar en la lista. */}
            <div className="tecnico">
              <DeleteButton
                label="Borrar este artista"
                confirmLabel="¿Borrarlo todo?"
                busy={accion.busy}
                onDelete={async () => {
                  const hecho = await accion.run(() => api.del(`/api/universes/${universeId}`))
                  if (hecho !== null) navegar('/', { replace: true })
                }}
              />
            </div>
          </>
        )}
      </main>
    </>
  )
}
