import { useCallback, useEffect, useState } from 'react'
import { getConfig, getStats } from './api.js'
import VideoUpload from './components/VideoUpload.jsx'
import LiveCamera from './components/LiveCamera.jsx'
import History from './components/History.jsx'
import Violations from './components/Violations.jsx'
import ClassBars from './components/ClassBars.jsx'

const TABS = [
  { id: 'video', label: 'Video Upload' },
  { id: 'live', label: 'Live Camera' },
  { id: 'violations', label: 'Violations & Plates' },
  { id: 'history', label: 'History' },
]

export default function App() {
  const [tab, setTab] = useState('video')
  const [config, setConfig] = useState(null)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    let timer
    const poll = async () => {
      try {
        const cfg = await getConfig()
        setConfig(cfg)
        if (!cfg.ready && !cfg.error) timer = setTimeout(poll, 2000)
      } catch {
        timer = setTimeout(poll, 3000)
      }
    }
    poll()
    return () => clearTimeout(timer)
  }, [])

  const loadStats = useCallback(() => {
    getStats().then(setStats).catch(() => {})
  }, [])

  useEffect(() => {
    loadStats()
    window.addEventListener('stats-refresh', loadStats)
    return () => window.removeEventListener('stats-refresh', loadStats)
  }, [loadStats])

  useEffect(() => { loadStats() }, [tab, loadStats])

  const ready = config?.ready
  const topClasses = stats
    ? Object.entries(stats.class_totals).slice(0, 5)
    : []

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>Smart Traffic System</h1>
        </div>
      </header>

      <section className="stats-strip">
        <div className="stat-card">
          <span className="stat-value">{stats?.sessions ?? '—'}</span>
          <span className="stat-label">Sessions stored</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats?.frames?.toLocaleString() ?? '—'}</span>
          <span className="stat-label">Frames analyzed</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats?.detections?.toLocaleString() ?? '—'}</span>
          <span className="stat-label">Total detections</span>
        </div>
        <div className="stat-card stat-card-wide">
          {topClasses.length > 0 ? (
            <ClassBars counts={Object.fromEntries(topClasses)} compact />
          ) : (
            <span className="stat-label">No detections yet</span>
          )}
        </div>
      </section>

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? 'tab-active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === 'video' && <VideoUpload ready={ready} />}
        {tab === 'live' && <LiveCamera ready={ready} />}
        {tab === 'violations' && <Violations />}
        {tab === 'history' && <History />}
      </main>

      <footer className="footer">Smart Traffic System</footer>
    </div>
  )
}
