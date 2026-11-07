import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, mediaUrl, newIdempotencyKey } from '../api/client'
import { ClaveDeEnvio } from '../lib/claveEnvio'
import { useAction, useResource } from '../hooks/useApi'
import type { Home as HomeData, RecentProject, UniverseCard } from '../api/types'
import { ErrorNote, Field, Loading, Sheet } from '../components/ui'
import { ElegirGenero } from '../components/Genero'
import { ElegirEstilo, ElegirGeneros } from '../components/Seleccion'

/**
 * La portada de la aplicación.
 *
 * No es un panel de control: es la primera cosa que se ve al abrir el teléfono,
 * y lo que tiene que contestar es "¿quiénes son mis artistas y qué dejé a
 * medias?". Por eso mandan las caras y los títulos, y lo demás —cuántos
 * trabajos hay en marcha— cabe en la línea de estado de cada tarjeta en vez
 * de abrir secciones nuevas.
 *
 * Aquí no hay barra de pestañas. Ocupa sitio y en esta pantalla no lleva a
 * ningún sitio que no esté ya delante; lo que hace falta —ajustes y salir—
 * está en el botón redondo de la esquina.
 */

export function HomeScreen() {
  const { data, loading, error, reload } = useResource<HomeData>('/api/home', 8000)
  const [creando, setCreando] = useState(false)
  const [menu, setMenu] = useState(false)
  const [nombre, setNombre] = useState('')
  const [sexo, setSexo] = useState('')
  const [genero, setGenero] = useState('')
  const [generos, setGeneros] = useState<string[]>([])
  const [estilo, setEstilo] = useState('')
  const [enlaces, setEnlaces] = useState('')
  const [notas, setNotas] = useState('')
  const navegarA = useNavigate()
  const accion = useAction()
  // La clave de ESTA apertura del formulario: la misma entre toques
  // mientras el formulario siga abierto, nueva en cada apertura. Si la
  // respuesta se pierde por el camino y se vuelve a tocar «Crear
  // artista», el servidor reconoce la clave y devuelve EL MISMO
  // artista en vez de crear un duplicado (ver lib/claveEnvio).
  const [claveCreacion] = useState(() => new ClaveDeEnvio(() => newIdempotencyKey('creacion')))

  const abrirCreacion = () => {
    // Apertura nueva, clave nueva: lo que se cree desde aqui es otro
    // artista, no la repeticion del anterior.
    claveCreacion.conseguida()
    setCreando(true)
  }

  // Un solo formulario. Antes se creaba un universo con un nombre y dentro
  // habia que crear otra vez al artista con otro nombre, y el Director de
  // casting cambiaba el segundo por su cuenta.
  const crear = async () => {
    const creado = await accion.run(() =>
      api.post<{ id: string }>('/api/universes', {
        name: nombre.trim(),
        gender: sexo,
        genre: genero.trim(),
        notes: notas.trim(),
        visual_style: estilo,
        music_genres: generos,
        inspiration_urls: enlaces
          .split('\n')
          .map((linea) => linea.trim())
          .filter(Boolean),
        idempotency_key: claveCreacion.paraEnviar(),
      }),
    )
    if (creado) {
      // Creacion conseguida: la proxima apertura usa una clave nueva.
      claveCreacion.conseguida()
      setCreando(false)
      setNombre('')
      setSexo('')
      setGenero('')
      setGeneros([])
      setEstilo('')
      setEnlaces('')
      setNotas('')
      await reload()
      // Directo a su pantalla: el estudio ya esta diseñandolo.
      navegarA(`/u/${creado.id}`)
    }
  }

  const universos = data?.universes ?? []
  const proyectos = data?.recent_projects ?? []

  return (
    <>
      <main className="screen inicio">
        <header className="inicio-cabecera">
          <div>
            <h1 className="inicio-titulo">Good Problem</h1>
            <p className="inicio-lema">Tu música. Tus universos.</p>
          </div>
          <button className="menu-redondo" onClick={() => setMenu(true)} aria-label="Menú">
            <span />
            <span />
            <span />
          </button>
        </header>

        {loading && !data && <Loading />}
        <ErrorNote error={error} />

        {data && (
          <>
            <div className="epigrafe">
              <h2>Mis universos</h2>
              <button className="btn small primary" onClick={abrirCreacion}>
                + Nuevo universo
              </button>
            </div>

            {universos.length === 0 ? (
              <p className="inicio-vacio">
                Todavía no hay ninguno. Un universo es un artista: su cara, sus
                canciones y sus videoclips.
              </p>
            ) : (
              <div className="list">
                {universos.map((universo) => (
                  <TarjetaUniverso key={universo.id} universo={universo} datos={data} />
                ))}
              </div>
            )}

            {proyectos.length > 0 && (
              <>
                <div className="epigrafe">
                  <h2>Últimos proyectos</h2>
                  {universos.length > 0 && (
                    <Link className="ver-todos" to={`/u/${universos[0].id}/projects`}>
                      Ver todos
                    </Link>
                  )}
                </div>
                <div className="list apretada">
                  {proyectos.map((proyecto) => (
                    <FilaProyecto key={proyecto.id} proyecto={proyecto} />
                  ))}
                </div>
              </>
            )}

            <button className="crear-universo" onClick={abrirCreacion}>
              + Crear nuevo universo
            </button>
          </>
        )}
      </main>

      {menu && <MenuEsquina onClose={() => setMenu(false)} />}

      {creando && (
        <Sheet title="¿Quién es tu artista?" onClose={() => setCreando(false)}>
          <Field
            label="Nombre artístico"
            value={nombre}
            onChange={setNombre}
            placeholder="Feri"
          />
          <ElegirGenero value={sexo} onChange={setSexo} />
          <div className="field">
            <label>Su estilo visual (fijo)</label>
            <ElegirEstilo valor={estilo} alCambiar={setEstilo} />
          </div>
          <div className="field">
            <label>Sus generos (combinables)</label>
            <ElegirGeneros valor={generos} alCambiar={setGeneros} />
          </div>
          <Field
            label="O su estilo musical, en tus palabras"
            value={genero}
            onChange={setGenero}
            placeholder="Reggaetón triste"
          />
          <Field
            label="Canciones de referencia en YouTube (opcional, una por linea)"
            value={enlaces}
            onChange={setEnlaces}
            placeholder="https://www.youtube.com/watch?v=…"
            multiline
          />
          <Field
            label="Algo más (opcional)"
            value={notas}
            onChange={setNotas}
            placeholder="De Caracas, 24 años, canta a la gente que se fue"
            multiline
          />
          <ErrorNote error={accion.error} onDismiss={accion.clearError} />
          <button
            className="btn primary block"
            disabled={!nombre.trim() || !sexo || accion.busy}
            onClick={crear}
          >
            {accion.busy ? 'Creando…' : 'Crear artista'}
          </button>
          <p className="muted" style={{ margin: 0 }}>
            Con esto basta. El estudio le escribe la identidad y prepara sus
            retratos; el nombre y quién es no te los cambia nadie.
          </p>
        </Sheet>
      )}
    </>
  )
}

/** Una tarjeta de artista: la cara, el nombre y por dónde va. */
function TarjetaUniverso({ universo, datos }: { universo: UniverseCard; datos: HomeData }) {
  // El retrato vigente del artista, con su marca de version: la ruta no
  // cambia al regenerar, y sin la marca el telefono ensena la foto vieja.
  const foto = mediaUrl(universo.cover_path, universo.cover_version)
  const señal = estado(universo, datos)
  return (
    <Link to={`/u/${universo.id}`} className="universo">
      <div className="universo-foto">
        {foto ? <img src={foto} alt={universo.name} /> : <span>{inicial(universo.name)}</span>}
      </div>
      <div className="universo-texto">
        <div className="universo-nombre">{universo.name || universo.artist_name || 'Sin nombre'}</div>
        <div className="universo-genero">{universo.tagline || universo.artist_name || '—'}</div>
        <div className="universo-estado">
          <i className={`punto ${señal.tono}`} />
          {señal.texto}
        </div>
      </div>
    </Link>
  )
}

/** Una fila de videoclip: la portada de su canción, el título y por dónde va. */
function FilaProyecto({ proyecto }: { proyecto: RecentProject }) {
  const foto = mediaUrl(proyecto.cover_path)
  return (
    <Link to={`/u/${proyecto.universe_id}/projects/${proyecto.id}`} className="proyecto">
      <div className="proyecto-foto">{foto && <img src={foto} alt="" />}</div>
      <div className="proyecto-texto">
        <div className="proyecto-titulo">{proyecto.title}</div>
        <div className="proyecto-pie">
          <span className="proyecto-universo">{proyecto.universe_name}</span>
          {proyecto.stage && <span> · {proyecto.stage}</span>}
          {fecha(proyecto.updated_at) && <span> · {fecha(proyecto.updated_at)}</span>}
        </div>
      </div>
      <span className="proyecto-flecha">›</span>
    </Link>
  )
}

/** Lo que no cabe en la portada: los ajustes y la salida. */
function MenuEsquina({ onClose }: { onClose: () => void }) {
  const navegar = useNavigate()
  return (
    <Sheet title="Menú" onClose={onClose}>
      <button
        className="btn block"
        onClick={() => {
          onClose()
          navegar('/settings')
        }}
      >
        Ajustes
      </button>
      <button
        className="btn block"
        onClick={async () => {
          await api.post('/api/auth/logout')
          window.location.reload()
        }}
      >
        Salir de la cuenta
      </button>
    </Sheet>
  )
}

/** La línea de estado de una tarjeta.
 *
 * Es una sola línea, así que dice lo más urgente y se calla el resto: lo que
 * se está generando, y luego lo que hay a medias. Nada espera tu visto
 * bueno: lo que se genera queda en uso en el acto, así que no hay ninguna
 * decisión pendiente que anunciar aquí.
 */
function estado(universo: UniverseCard, datos: HomeData) {
  const generando = datos.active_jobs.filter((j) => j.universe_id === universo.id).length
  if (generando > 0) {
    return { tono: 'generando', texto: plural(generando, 'cosa generándose', 'cosas generándose') }
  }
  if (universo.projects_active > 0) {
    return {
      tono: 'proceso',
      texto: plural(universo.projects_active, 'proyecto en proceso', 'proyectos en proceso'),
    }
  }
  if (universo.projects_total > 0) return { tono: 'listo', texto: 'Todo terminado' }
  return { tono: 'quieto', texto: 'Sin proyectos todavía' }
}

function plural(n: number, uno: string, varios: string): string {
  return `${n} ${n === 1 ? uno : varios}`
}

function inicial(nombre: string): string {
  return (nombre.trim()[0] ?? '·').toUpperCase()
}

function fecha(iso: string): string {
  if (!iso) return ''
  const dia = new Date(iso)
  if (Number.isNaN(dia.getTime())) return ''
  return dia.toLocaleDateString('es', { day: 'numeric', month: 'short' }).replace('.', '')
}
