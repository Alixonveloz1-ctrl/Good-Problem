import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, mediaUrl } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { Character, Universe } from '../api/types'
import { DeleteButton, ErrorNote, Loading, StatusBadge, TopBar } from '../components/ui'

/**
 * La pantalla del artista.
 *
 * Antes era una lista de once filas iguales con nombres de manual —Artist
 * Bible, Canon, Jobs, Export— y ningún orden entre ellas. Al crear un artista
 * se aterrizaba ahí sin saber por dónde empezar, y sin ver al artista por
 * ninguna parte.
 *
 * Ahora manda la cara. Lo primero que hay que decidir es quién es, y eso se ve:
 * mientras no haya un retrato aprobado, la pantalla tiene una sola cosa que
 * hacer. Con retrato, la cara preside y debajo va el trabajo en el orden en que
 * ocurre: música, videoclips, contenido. Lo de mantener —el vestuario, las
 * locaciones, la voz— queda debajo, y lo técnico al final y en pequeño.
 */

type Seccion = { to: string; label: string; hint: string }

const PRODUCCION: Seccion[] = [
  { to: 'songs', label: 'Música', hint: 'Concepto, letra y canción' },
  { to: 'projects', label: 'Videoclips', hint: 'Historia, planos y montaje' },
  { to: 'content', label: 'Contenido', hint: 'Shorts, detrás de cámara, entrevistas' },
]

const BIBLIOTECA: Seccion[] = [
  { to: 'characters', label: 'Personajes', hint: 'El artista y quien le acompaña' },
  { to: 'wardrobe', label: 'Vestuario', hint: 'Cómo va vestido en cada cosa' },
  { to: 'locations', label: 'Locaciones', hint: 'Dónde ocurre' },
  { to: 'voz', label: 'Su voz', hint: 'Grabar la voz con la que habla' },
  { to: 'bible', label: 'Identidad', hint: 'Cómo es, cómo suena, de qué habla' },
]

const TECNICO: Seccion[] = [
  { to: 'jobs', label: 'En marcha', hint: '' },
  { to: 'canon', label: 'Aprobado', hint: '' },
  { to: 'exports', label: 'Descargas', hint: '' },
]

function Fila({ base, seccion }: { base: string; seccion: Seccion }) {
  return (
    <Link to={`${base}/${seccion.to}`} className="card tappable">
      <div className="row">
        <div className="grow">
          <strong>{seccion.label}</strong>
          {seccion.hint && <div className="sub">{seccion.hint}</div>}
        </div>
        <span className="muted">›</span>
      </div>
    </Link>
  )
}

/** El retrato del artista, o la única cosa que hacer si todavía no hay. */
function Retrato({ base, artista }: { base: string; artista: Character | null }) {
  const foto = artista?.master_shots.find((toma) => toma.storage_path)

  if (!artista) {
    return (
      <div className="card presenta">
        <h2>¿Quién es tu artista?</h2>
        <p className="muted">
          Es lo primero. Su cara manda en todo lo demás: las canciones se le
          escriben a alguien, y en los videos sale él.
        </p>
        <Link to={`${base}/characters`} className="btn primary block">
          Crear a tu artista
        </Link>
      </div>
    )
  }

  return (
    <Link to={`${base}/characters`} className="card presenta tappable">
      {foto ? (
        <img className="presenta-foto" src={mediaUrl(foto.storage_path) ?? ''} alt={artista.name} />
      ) : (
        // Sin retrato, la inicial del nombre. Un dibujo de persona generico
        // seria un adorno donde tiene que haber una cara.
        <div className="presenta-hueco">{(artista.name.trim()[0] ?? '·').toUpperCase()}</div>
      )}
      <div className="row between" style={{ width: '100%' }}>
        <h2 style={{ margin: 0 }}>{artista.name || 'Sin nombre'}</h2>
        <StatusBadge status={artista.status} />
      </div>
      {!foto && (
        <p className="muted" style={{ margin: 0 }}>
          Todavía no tiene cara. Tócalo y genérale el retrato: sin eso, los
          videos no saben a quién están grabando.
        </p>
      )}
    </Link>
  )
}

export function UniverseScreen() {
  const { universeId = '' } = useParams()
  const base = `/u/${universeId}`
  const navegar = useNavigate()
  const universo = useResource<Universe>(`/api/universes/${universeId}`)
  const personajes = useResource<Character[]>(`/api/universes/${universeId}/characters`)
  const accion = useAction()

  const lista = personajes.data ?? []
  // El protagonista si lo hay; si no, el primero que exista. Un universo con
  // personajes pero sin protagonista marcado no puede quedarse sin cara.
  const artista = lista.find((p) => p.role === 'lead') ?? lista[0] ?? null
  const listo = Boolean(artista?.master_shots.some((toma) => toma.storage_path))

  return (
    <>
      <TopBar title={universo.data?.name ?? 'Artista'} back />
      <main className="screen">
        {universo.loading && !universo.data && <Loading />}
        <ErrorNote error={universo.error} />
        <ErrorNote error={personajes.error} />
        <ErrorNote error={accion.error} onDismiss={accion.clearError} />

        {universo.data && (
          <>
            {universo.data.tagline && <p className="muted lema">{universo.data.tagline}</p>}

            <Retrato base={base} artista={artista} />

            {/* Sin cara aprobada, producir no lleva a ningún sitio: cada video
                necesita una imagen del artista de la que partir. Se enseña,
                pero apagado, para que se vea que existe y por qué no toca. */}
            <div className={listo ? '' : 'apagado'}>
              <div className="section-title">Producir</div>
              <div className="list">
                {PRODUCCION.map((s) => (
                  <Fila key={s.to} base={base} seccion={s} />
                ))}
              </div>
            </div>

            <div className="section-title">Su mundo</div>
            <div className="list">
              {BIBLIOTECA.map((s) => (
                <Fila key={s.to} base={base} seccion={s} />
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
                sus videoclips y todo lo aprobado— y donde no se roza sin
                querer al buscar en la lista. */}
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
