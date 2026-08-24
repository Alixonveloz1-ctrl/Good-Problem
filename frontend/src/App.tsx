import { useEffect } from 'react'
import { NavLink, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { recordarUniverso, ultimoUniverso } from './lib/ultimoUniverso'
import { HomeScreen } from './screens/Home'
import { UniverseScreen } from './screens/Universe'
import { BibleScreen } from './screens/Bible'
import { CharactersScreen } from './screens/Characters'
import { LocationsScreen, WardrobeScreen } from './screens/Library'
import { SongScreen, SongsScreen } from './screens/Songs'
import { ProjectScreen, ProjectsScreen } from './screens/Projects'
import { SceneScreen } from './screens/Scene'
import { ContentScreen } from './screens/Content'
import { VoiceCloneScreen } from './screens/VoiceClone'
import { JobsScreen } from './screens/Jobs'
import { CanonScreen, ExportsScreen, SettingsScreen } from './screens/Misc'

function TabBar() {
  const { universeId } = useParams()

  // El artista de la ruta manda; si no hay -en Inicio o en Ajustes- vale el
  // último que se abrió. Sin ese recuerdo, Música y Video no llevan a ningún
  // sitio desde la primera pantalla.
  useEffect(() => {
    if (universeId) recordarUniverso(universeId)
  }, [universeId])

  const activo = universeId ?? ultimoUniverso()
  const prefix = activo ? `/u/${activo}` : ''
  // Sin iconos. Los emoji de teclado son de otra aplicacion: aqui manda la
  // tipografia, y cuatro palabras en versalitas se leen igual de rapido.
  const tabs = [
    { to: '/', label: 'Inicio', end: true },
    { to: activo ? `${prefix}/songs` : '/', label: 'Musica', end: false },
    { to: activo ? `${prefix}/projects` : '/', label: 'Video', end: false },
    { to: '/settings', label: 'Ajustes', end: false },
  ]
  return (
    <nav className="tabbar">
      {tabs.map((tab) => (
        <NavLink
          key={tab.label}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => (isActive ? 'active' : '')}
        >
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

export default function App() {
  return (
    <div className="app">
      <Routes>
        <Route path="/" element={<HomeScreen />} />
        <Route path="/settings" element={<SettingsScreen />} />
        <Route path="/u/:universeId" element={<UniverseScreen />} />
        <Route path="/u/:universeId/bible" element={<BibleScreen />} />
        <Route path="/u/:universeId/characters" element={<CharactersScreen />} />
        <Route path="/u/:universeId/wardrobe" element={<WardrobeScreen />} />
        <Route path="/u/:universeId/locations" element={<LocationsScreen />} />
        <Route path="/u/:universeId/songs" element={<SongsScreen />} />
        <Route path="/u/:universeId/songs/:songId" element={<SongScreen />} />
        <Route path="/u/:universeId/projects" element={<ProjectsScreen />} />
        <Route path="/u/:universeId/projects/:projectId" element={<ProjectScreen />} />
        <Route path="/u/:universeId/scenes/:sceneId" element={<SceneScreen />} />
        <Route path="/u/:universeId/content" element={<ContentScreen />} />
        <Route path="/u/:universeId/voz" element={<VoiceCloneScreen />} />
        <Route path="/u/:universeId/canon" element={<CanonScreen />} />
        <Route path="/u/:universeId/jobs" element={<JobsScreen />} />
        <Route path="/u/:universeId/exports" element={<ExportsScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* La portada no lleva barra de pestanas: alli el nombre grande y las
          caras son toda la navegacion que hace falta, y lo que sobraba
          -Ajustes y Salir- esta en el boton redondo de su esquina. */}
      <Routes>
        <Route path="/" element={null} />
        <Route path="/u/:universeId/*" element={<TabBar />} />
        <Route path="*" element={<TabBar />} />
      </Routes>
    </div>
  )
}
