import { useCallback, useEffect, useState } from 'react'
import { getEvents, deleteEvent, getHistory, refreshStats, fmtTime, fmtOffset } from '../api.js'

export default function Violations() {
  const [violations, setViolations] = useState([])
  const [plates, setPlates] = useState([])
  const [sessions, setSessions] = useState([])
  const [sessionFilter, setSessionFilter] = useState('')
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    const params = sessionFilter ? { session_id: sessionFilter } : {}
    try {
      const [v, p, s] = await Promise.all([
        getEvents({ ...params, type: 'no_helmet', limit: 300 }),
        getEvents({ ...params, type: 'plate', limit: 300 }),
        getHistory(),
      ])
      setViolations(v)
      setPlates(p)
      setSessions(s)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [sessionFilter])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    window.addEventListener('stats-refresh', load)
    return () => window.removeEventListener('stats-refresh', load)
  }, [load])

  const remove = async (ev) => {
    if (!window.confirm('Delete this image from the database and disk?')) return
    try {
      await deleteEvent(ev.id)
      load()
      refreshStats()
    } catch (e) { setError(e.message) }
  }

  return (
    <section className="card">
      <div className="history-head">
        <div>
          <h2 className="card-title">Helmet violations &amp; number plates</h2>
          <p className="card-sub">
            Cropped images saved by the helmet and license-plate detectors —
            every image can be downloaded.
          </p>
        </div>
        <div className="btn-row">
          <select className="select" value={sessionFilter} onChange={(e) => setSessionFilter(e.target.value)}>
            <option value="">All sessions</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>Session #{s.id} · {s.mode}</option>
            ))}
          </select>
          <button className="btn btn-small btn-ghost" onClick={load}>Refresh</button>
        </div>
      </div>

      {error && <div className="badge badge-red">✗ {error}</div>}

      <div className="violation-grid-wrap">
        <EventColumn
          title="Riders without helmet"
          subtitle={`${violations.length} image(s)`}
          events={violations}
          empty="No helmet violations detected yet."
          onRemove={remove}
        />
        <EventColumn
          title="Number plates"
          subtitle={`${plates.length} image(s)`}
          events={plates}
          empty="No number plates detected yet."
          onRemove={remove}
        />
      </div>
    </section>
  )
}

function EventColumn({ title, subtitle, events, empty, onRemove }) {
  return (
    <div className="event-column">
      <div className="event-column-head">
        <h3>{title}</h3>
        <span className="badge badge-green">{subtitle}</span>
      </div>
      {events.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <div className="event-grid">
          {events.map((ev) => (
            <div className="event-card" key={ev.id}>
              <a href={ev.image_path} target="_blank" rel="noreferrer" title="Open full size">
                <img className="event-image" src={ev.image_path} alt={ev.type} />
              </a>
              <div className="event-meta">
                <span>Session #{ev.session_id}</span>
                <span>Frame {ev.frame_index} · {fmtOffset(ev.time_offset)}</span>
                <span>Confidence {(ev.confidence * 100).toFixed(0)}%</span>
                <span className="muted">{fmtTime(ev.created_at)}</span>
              </div>
              <div className="event-actions">
                <a className="btn btn-small btn-primary" href={ev.image_path} download>
                  Download
                </a>
                <button className="btn btn-small btn-danger" onClick={() => onRemove(ev)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
