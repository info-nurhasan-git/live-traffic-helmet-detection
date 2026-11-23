import { classColor } from '../api.js'

export default function ClassBars({ counts, compact = false }) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return <div className="muted">No detections</div>
  const max = Math.max(...entries.map(([, v]) => v), 1)
  return (
    <div className={`class-bars ${compact ? 'class-bars-compact' : ''}`}>
      {entries.map(([name, value]) => (
        <div className="class-bar-row" key={name}>
          <span className="class-bar-name">
            <span className="class-dot" style={{ background: classColor(name) }} />
            {name}
          </span>
          <div className="class-bar-track">
            <div
              className="class-bar-fill"
              style={{ width: `${(value / max) * 100}%`, background: classColor(name) }}
            />
          </div>
          <span className="class-bar-value">{value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  )
}
