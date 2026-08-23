import { NavLink, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { HomeScreen } from './screens/Home'
import { UniverseScreen } from './screens/Universe'
import { BibleScreen } from './screens/Bible'
import { CharactersScreen } from './screens/Characters'
import { LocationsScreen, WardrobeScreen } from './screens/Library'
import { SongScreen, SongsScreen } from './screens/Songs'
import { ProjectScreen, ProjectsScreen } from './screens/Projects'
import { SceneScreen } from './screens/Scene'
import { ContentScreen } from './screens/Content'
import { JobsScreen } from './screens/Jobs'
import { CanonScreen, ExportsScreen, SettingsScreen } from './screens/Misc'

function TabBar() {
  const { universeId } = useParams()
  const prefix = universeId ? `/u/${universeId}` : ''
  const tabs = [
    { to: '/', glyph: '🏠', label: 'Inicio', end: true },
    { to: universeId ? `${prefix}/songs` : '/', glyph: '🎵', label: 'Musica', end: false },
    { to: universeId ? `${prefix}/projects` : '/', glyph: '🎬', label: 'Video', end: false },
    { to: '/settings', glyph: '⚙️', label: 'Ajustes', end: false },
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
          <span className="glyph">{tab.glyph}</span>
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
        <Route path="/u/:universeId/canon" element={<CanonScreen />} />
        <Route path="/u/:universeId/jobs" element={<JobsScreen />} />
        <Route path="/u/:universeId/exports" element={<ExportsScreen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Routes>
        <Route path="/u/:universeId/*" element={<TabBar />} />
        <Route path="*" element={<TabBar />} />
      </Routes>
    </div>
  )
}
