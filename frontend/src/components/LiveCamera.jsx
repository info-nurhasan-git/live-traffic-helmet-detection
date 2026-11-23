import { useEffect, useRef, useState } from 'react'
import { wsUrl, refreshStats, classColor } from '../api.js'
import ClassBars from './ClassBars.jsx'

const SEND_WIDTH = 640

export default function LiveCamera({ ready }) {
  const videoRef = useRef(null)
  const overlayRef = useRef(null)
  const streamRef = useRef(null)
  const wsRef = useRef(null)
  const sendCanvasRef = useRef(document.createElement('canvas'))
  const busyRef = useRef(false)
  const runningRef = useRef(false)
  const lastSendRef = useRef(0)
  const fpsRef = useRef(0)

  const [status, setStatus] = useState('idle') // idle | starting | running | stopped | error
  const [sessionId, setSessionId] = useState(null)
  const [frameCounts, setFrameCounts] = useState({})
  const [counts, setCounts] = useState({})
  const [total, setTotal] = useState(0)
  const [frames, setFrames] = useState(0)
  const [ms, setMs] = useState(0)
  const [fps, setFps] = useState(0)
  const [error, setError] = useState(null)
  const [imgsz, setImgsz] = useState(320)
  const [eventTotals, setEventTotals] = useState({ no_helmet: 0, plate: 0 })

  const drawOverlay = (msg) => {
    const canvas = overlayRef.current
    if (!canvas) return
    if (canvas.width !== msg.w || canvas.height !== msg.h) {
      canvas.width = msg.w
      canvas.height = msg.h
    }
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    for (const b of msg.boxes) {
      const color = classColor(b.class_name)
      const x = b.x1, y = b.y1, w = b.x2 - b.x1, h = b.y2 - b.y1
      ctx.lineWidth = Math.max(2, canvas.width / 320)
      ctx.strokeStyle = color
      ctx.strokeRect(x, y, w, h)
      ctx.fillStyle = color + '22'
      ctx.fillRect(x, y, w, h)
      const label = `${b.class_name} ${(b.confidence * 100).toFixed(0)}%`
      const fs = Math.max(13, canvas.width / 42)
      ctx.font = `600 ${fs}px "Segoe UI", sans-serif`
      const tw = ctx.measureText(label).width
      const ty = y > fs + 8 ? y - 6 : y + h + fs + 6
      ctx.fillStyle = color
      ctx.fillRect(x - 1, ty - fs - 4, tw + 10, fs + 8)
      ctx.fillStyle = '#0b1220'
      ctx.fillText(label, x + 4, ty - 5)
    }
  }

  const pump = () => {
    if (!runningRef.current) return
    const ws = wsRef.current
    const video = videoRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN || busyRef.current ||
        ws.bufferedAmount > 2_000_000 || !video?.videoWidth) {
      setTimeout(pump, 40)
      return
    }
    const c = sendCanvasRef.current
    const scale = SEND_WIDTH / video.videoWidth
    c.width = SEND_WIDTH
    c.height = Math.round(video.videoHeight * scale)
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height)
    c.toBlob((blob) => {
      if (blob && ws.readyState === WebSocket.OPEN) {
        busyRef.current = true
        lastSendRef.current = performance.now()
        ws.send(blob)
      }
      if (runningRef.current) setTimeout(pump, 30)
    }, 'image/jpeg', 0.7)
  }

  const stop = () => {
    runningRef.current = false
    busyRef.current = false
    try { wsRef.current?.close() } catch { /* ignore */ }
    wsRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setStatus((s) => (s === 'running' || s === 'starting' ? 'stopped' : s))
    refreshStats()
  }

  const start = async () => {
    setError(null)
    setStatus('starting')
    setTotal(0); setFrames(0); setCounts({}); setFrameCounts({})
    setEventTotals({ no_helmet: 0, plate: 0 })
    fpsRef.current = 0
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      streamRef.current = stream
      const video = videoRef.current
      video.srcObject = stream
      await video.play()

      const ws = new WebSocket(wsUrl('/ws/live'))
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'ready') {
          setSessionId(msg.session_id)
          setStatus('running')
          runningRef.current = true
          pump()
        } else if (msg.type === 'detections') {
          busyRef.current = false
          drawOverlay(msg)
          const rtt = performance.now() - lastSendRef.current
          if (rtt > 0) {
            const inst = 1000 / rtt
            fpsRef.current = fpsRef.current ? fpsRef.current * 0.8 + inst * 0.2 : inst
          }
          setFrameCounts(msg.frame_counts)
          if (msg.event_totals) setEventTotals(msg.event_totals)
          setCounts(msg.counts)
          setTotal(msg.total)
          setFrames(msg.frames)
          setMs(msg.ms)
          setFps(Math.round(fpsRef.current * 10) / 10)
        } else if (msg.type === 'config') {
          setImgsz(msg.imgsz)
        } else if (msg.type === 'error') {
          setError(msg.message)
          stop()
          setStatus('error')
        }
      }
      ws.onclose = () => {
        if (runningRef.current) {
          runningRef.current = false
          streamRef.current?.getTracks().forEach((t) => t.stop())
          setStatus('stopped')
          refreshStats()
        }
      }
      ws.onerror = () => {
        setError('WebSocket connection failed — is the backend running on port 8000?')
      }
    } catch (e) {
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
      setError(
        e.name === 'NotAllowedError'
          ? 'Camera permission denied. Allow camera access in the browser and try again.'
          : e.message || 'Could not start the camera',
      )
      setStatus('error')
    }
  }

  const changeQuality = (value) => {
    const v = Number(value)
    setImgsz(v)
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'config', imgsz: v }))
    }
  }

  const snapshot = () => {
    const video = videoRef.current
    const overlay = overlayRef.current
    if (!video?.videoWidth) return
    const c = document.createElement('canvas')
    c.width = video.videoWidth
    c.height = video.videoHeight
    const ctx = c.getContext('2d')
    ctx.drawImage(video, 0, 0, c.width, c.height)
    if (overlay) ctx.drawImage(overlay, 0, 0, c.width, c.height)
    const a = document.createElement('a')
    a.href = c.toDataURL('image/png')
    a.download = `traffic_snapshot_${Date.now()}.png`
    a.click()
  }

  useEffect(() => () => {
    runningRef.current = false
    try { wsRef.current?.close() } catch { /* ignore */ }
    streamRef.current?.getTracks().forEach((t) => t.stop())
  }, [])

  const running = status === 'running'
  const liveChips = Object.entries(frameCounts)

  return (
    <div className="panel-grid">
      <section className="card">
        <h2 className="card-title">Live camera detection</h2>
        <p className="card-sub">
          Frames stream to the server over WebSocket; bounding boxes are drawn in
          real time (no segmentation). The session is saved to the database when you stop.
        </p>

        <div className="live-video-wrap">
          <video ref={videoRef} playsInline muted className="live-video" />
          <canvas ref={overlayRef} className="live-overlay" />
          {!running && (
            <div className="live-placeholder">
              {status === 'starting' ? 'Starting camera…'
                : status === 'stopped' ? `Session #${sessionId ?? '—'} saved to database`
                : status === 'error' ? 'Camera error'
                : 'Camera is off'}
            </div>
          )}
          {running && <div className="live-badge"><span className="dot dot-red" /> LIVE</div>}
        </div>

        <div className="btn-row">
          {!running ? (
            <button className="btn btn-primary" onClick={start} disabled={!ready || status === 'starting'}>
              Start Camera
            </button>
          ) : (
            <button className="btn btn-danger" onClick={stop}>Stop &amp; Save</button>
          )}
          <button className="btn btn-ghost" onClick={snapshot} disabled={!running}>
            Snapshot
          </button>
          <label className="quality-label">
            Quality
            <select className="select" value={imgsz} onChange={(e) => changeQuality(e.target.value)}>
              <option value={320}>Fast (320)</option>
              <option value={416}>Balanced (416)</option>
              <option value={640}>Accurate (640)</option>
            </select>
          </label>
        </div>
        {error && <div className="badge badge-red">✗ {error}</div>}
        {!ready && <p className="muted">Waiting for the model to load…</p>}

        {running && (
          <div className="live-metrics">
            <span>{fps} FPS</span>
            <span>{ms} ms / frame</span>
            <span>{frames} frames</span>
            {sessionId && <span>Session #{sessionId}</span>}
            <span className="event-metric-red">{eventTotals.no_helmet} no helmet</span>
            <span className="event-metric-green">{eventTotals.plate} plates</span>
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">Live statistics</h2>
        <div className="live-big">
          <div>
            <span className="stat-value">{total}</span>
            <span className="stat-label">Detections this session</span>
          </div>
        </div>
        <h3 className="card-subtitle">In current frame</h3>
        {liveChips.length > 0 ? (
          <div className="chip-row">
            {liveChips.map(([name, n]) => (
              <span key={name} className="chip" style={{ borderColor: classColor(name) }}>
                <span className="class-dot" style={{ background: classColor(name) }} />
                {name} × {n}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted">{running ? 'Nothing detected in this frame' : 'Start the camera to see live counts'}</p>
        )}
        <h3 className="card-subtitle">Session totals</h3>
        <ClassBars counts={counts} />
      </section>
    </div>
  )
}
