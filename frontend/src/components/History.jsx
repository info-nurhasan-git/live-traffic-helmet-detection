import { useCallback, useEffect, useState } from 'react'
import {
  getHistory, getSession, deleteSession, refreshStats,
  classColor, fmtTime, fmtOffset,
} from '../api.js'
import ClassBars from './ClassBars.jsx'

const FILTERS = [
  { id: '', label: 'All' },
  { id: 'video', label: 'Video' },
  { id: 'live', label: 'Live' },
]

export default function History() {
  const [sessions, setSessions] = useState([])
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    getHistory(filter || undefined)
      .then(setSessions)
      .catch((e) => setError(e.message))
  }, [filter])

  useEffect(() => { load() }, [load])

  const toggle = async (id) => {
    if (expanded === id) {
      setExpanded(null)
      setDetail(null)
      return
    }
    setExpanded(id)
    setDetail(null)
    try { setDetail(await getSession(id)) } catch (e) { setError(e.message) }
  }

  const remove = async (id) => {
    if (!window.confirm(`Delete session #${id} and its detections from the database?`)) return
    try {
      await deleteSession(id)
      if (expanded === id) { setExpanded(null); setDetail(null) }
      load()
      refreshStats()
    } catch (e) { setError(e.message) }
  }

  return (
    <section className="card">
      <div className="history-head">
        <div>
          <h2 className="card-title">Detection history</h2>
          <p className="card-sub">Every video &amp; live session is stored in the SQLite database.</p>
        </div>
        <div className="btn-row">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              className={`btn btn-small ${filter === f.id ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
          <button className="btn btn-small btn-ghost" onClick={load}>Refresh</button>
        </div>
      </div>

      {error && <div className="badge badge-red">✗ {error}</div>}

      {sessions.length === 0 ? (
        <p className="muted">No sessions yet. Analyze a video or start the live camera.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>#</th><th>Mode</th><th>Source</th><th>Started</th>
                <th>Frames</th><th>Detections</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <SessionRow
                  key={s.id}
                  s={s}
                  expanded={expanded === s.id}
                  detail={expanded === s.id ? detail : null}
                  onToggle={() => toggle(s.id)}
                  onDelete={() => remove(s.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function SessionRow({ s, expanded, detail, onToggle, onDelete }) {
  const statusClass =
    s.status === 'completed' ? 'badge-green'
      : s.status === 'failed' ? 'badge-red'
      : 'badge-amber'
  return (
    <>
      <tr className={`row-click ${expanded ? 'row-expanded' : ''}`} onClick={onToggle}>
        <td>{s.id}</td>
        <td>{s.mode === 'video' ? 'Video' : 'Live'}</td>
        <td className="cell-ellipsis" title={s.source}>{s.source}</td>
        <td>{fmtTime(s.created_at)}</td>
        <td>{s.frames_processed.toLocaleString()}</td>
        <td>{s.detections_count.toLocaleString()}</td>
        <td><span className={`badge ${statusClass}`}>{s.status}</span></td>
        <td onClick={(e) => e.stopPropagation()}>
          <button className="btn btn-small btn-danger" onClick={onDelete}>Delete</button>
        </td>
      </tr>
      {expanded && (
        <tr className="row-detail">
          <td colSpan={8}>
            {!detail ? (
              <p className="muted">Loading…</p>
            ) : (
              <div className="detail-grid">
                <div>
                  <h3 className="card-subtitle">Class summary</h3>
                  <ClassBars counts={detail.summary} />
                  {detail.result_video && (
                    <>
                      <h3 className="card-subtitle">Annotated video</h3>
                      <video className="result-video" controls src={detail.result_video} />
                    </>
                  )}
                </div>
                <div>
                  <h3 className="card-subtitle">
                    Detections ({detail.detections.length}
                    {detail.detections.length >= 3000 ? ', first 3000 shown' : ''})
                  </h3>
                  <div className="table-wrap table-wrap-tall">
                    <table className="table">
                      <thead>
                        <tr><th>Frame</th><th>Time</th><th>Class</th><th>Conf.</th><th>Box</th></tr>
                      </thead>
                      <tbody>
                        {detail.detections.slice(0, 200).map((d) => (
                          <tr key={d.id}>
                            <td>{d.frame_index}</td>
                            <td>{fmtOffset(d.time_offset)}</td>
                            <td>
                              <span className="class-dot" style={{ background: classColor(d.class_name) }} />
                              {d.class_name}
                            </td>
                            <td>{(d.confidence * 100).toFixed(0)}%</td>
                            <td className="muted">
                              [{d.x1}, {d.y1}, {d.x2}, {d.y2}]
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}
