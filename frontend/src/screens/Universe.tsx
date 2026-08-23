import { Link, useParams } from 'react-router-dom'
import { useResource } from '../hooks/useApi'
import type { Universe } from '../api/types'
import { Card, ErrorNote, Loading, TopBar } from '../components/ui'

const SECTIONS: { to: string; label: string; hint: string; glyph: string }[] = [
  { to: 'bible', label: 'Artist Bible', hint: 'Identidad, musica, visual, voz', glyph: '📖' },
  { to: 'characters', label: 'Personajes', hint: 'Character Master y secundarios', glyph: '🧍' },
  { to: 'wardrobe', label: 'Vestuario', hint: 'Atuendos por categoria', glyph: '🧥' },
  { to: 'locations', label: 'Locaciones', hint: 'Biblioteca de escenarios', glyph: '🏙️' },
  { to: 'songs', label: 'Musica', hint: 'Conceptos, letras y canciones', glyph: '🎵' },
  { to: 'projects', label: 'Videoclips', hint: 'Historia, storyboard, montaje', glyph: '🎬' },
  { to: 'content', label: 'Contenido', hint: 'Shorts, BTS, entrevistas', glyph: '📱' },
  { to: 'canon', label: 'Canon', hint: 'Lo aprobado, como referencia', glyph: '✅' },
  { to: 'jobs', label: 'Jobs', hint: 'Cola de generacion', glyph: '⚙️' },
  { to: 'exports', label: 'Export', hint: 'Paquetes descargables', glyph: '📦' },
]

export function UniverseScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error } = useResource<Universe>(`/api/universes/${universeId}`)

  return (
    <>
      <TopBar title={data?.name ?? 'Universe'} back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} />
        {data && (
          <>
            <Card>
              <div className="row between">
                <div>
                  <h2>{data.name}</h2>
                  {data.tagline && <div className="sub">{data.tagline}</div>}
                </div>
              </div>
            </Card>

            <div className="list">
              {SECTIONS.map((section) => (
                <Link
                  key={section.to}
                  to={`/u/${universeId}/${section.to}`}
                  className="card tappable"
                >
                  <div className="row">
                    <span style={{ fontSize: 22 }}>{section.glyph}</span>
                    <div className="grow">
                      <strong>{section.label}</strong>
                      <div className="sub">{section.hint}</div>
                    </div>
                    <span className="muted">›</span>
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </main>
    </>
  )
}
