import { useCallback, useEffect, useRef, useState } from 'react'
import {
  uploadVideo, getJob, cancelJob, getSession, refreshStats,
  classColor, fmtOffset,
} from '../api.js'
import ClassBars from './ClassBars.jsx'

export default function VideoUpload({ ready }) {
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [phase, setPhase] = useState('select') // select | uploading | processing | done | error
  const [job, setJob] = useState(null)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  const pickFile = (f) => {
    if (!f) return
    if (!f.type.startsWith('video/') && !/\.(mp4|avi|mov|mkv|webm|m4v)$/i.test(f.name)) {
      setError('Please choose a video file (mp4, avi, mov, mkv, webm).')
      return
    }
    setFile(f)
    setError(null)
    setPhase('select')
    setJob(null)
    setDetail(null)
  }

  const start = async () => {
    if (!file) return
    setPhase('uploading')
    setError(null)
    try {
      const res = await uploadVideo(file)
      setPhase('processing')
      pollRef.current = setInterval(async () => {
        try {
          const j = await getJob(res.job_id)
          setJob(j)
          if (j.status === 'completed') {
            clearInterval(pollRef.current)
            setPhase('done')
            refreshStats()
            try { setDetail(await getSession(j.session_id)) } catch { /* ignore */ }
          } else if (j.status === 'failed' || j.status === 'cancelled') {
            clearInterval(pollRef.current)
            setPhase('error')
            setError(j.error || `Processing ${j.status}`)
            refreshStats()
          }
        } catch (e) {
          clearInterval(pollRef.current)
          setPhase('error')
          setError(e.message)
        }
      }, 1000)
    } catch (e) {
      setPhase('error')
      setError(e.message)
    }
  }

  const reset = useCallback(() => {
    clearInterval(pollRef.current)
    setFile(null)
    setJob(null)
    setDetail(null)
    setError(null)
    setPhase('select')
    if (inputRef.current) inputRef.current.value = ''
  }, [])

  const onDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    pickFile(e.dataTransfer.files?.[0])
  }

  const busy = phase === 'uploading' || phase === 'processing'

  return (
    <div className="panel-grid">
      <section className="card">
        <h2 className="card-title">Upload a traffic video</h2>
        <p className="card-sub">
          The video is analyzed frame-by-frame with YOLO. Detected objects get bounding
          boxes and every detection is stored in the database.
        </p>

        {phase === 'select' && (
          <>
            <div
              className={`dropzone ${dragging ? 'dropzone-active' : ''} ${!ready ? 'dropzone-disabled' : ''}`}
              onClick={() => ready && inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <div className="dropzone-file">
                {file ? file.name : 'Drop video here or click to browse'}
              </div>
              {file ? (
                <div className="muted">{(file.size / (1024 * 1024)).toFixed(1)} MB</div>
              ) : (
                <div className="muted">mp4 · avi · mov · mkv · webm (max 300 MB)</div>
              )}
              <input
                ref={inputRef}
                type="file"
                accept="video/*,.mkv"
                hidden
                onChange={(e) => pickFile(e.target.files?.[0])}
              />
            </div>
            <div className="btn-row">
              <button className="btn btn-primary" disabled={!file || !ready || busy} onClick={start}>
                Upload &amp; Detect
              </button>
              {file && <button className="btn btn-ghost" onClick={reset}>Clear</button>}
            </div>
            {!ready && <p className="muted">Waiting for the model to load…</p>}
          </>
        )}

        {busy && (
          <div className="progress-block">
            <div className="progress-head">
              <span>{phase === 'uploading' ? 'Uploading…' : 'Analyzing video…'}</span>
              <span>{job?.progress ?? 0}%</span>
            </div>
            <div className="progress-track">
              <div
                className={`progress-fill ${phase === 'uploading' ? 'progress-indeterminate' : ''}`}
                style={{ width: phase === 'uploading' ? '40%' : `${job?.progress ?? 0}%` }}
              />
            </div>
            {job && (
              <div className="progress-meta">
                <span>Frames: {job.frames_done} / {job.frames_total || '?'}</span>
                <span>Detections so far: {job.detections}</span>
              </div>
            )}
            {job?.job_id && phase === 'processing' && (
              <button className="btn btn-danger" onClick={() => cancelJob(job.job_id)}>
                Cancel
              </button>
            )}
          </div>
        )}

        {phase === 'done' && job && (
          <div className="result-block">
            <div className="badge badge-green">✓ Saved to database · session #{job.session_id}</div>
            <div className="badge badge-red">{job.violations ?? 0} helmet violations</div>
            <div className="badge badge-green">{job.plates ?? 0} number plates found</div>
            <video className="result-video" controls src={job.result_url} />
            <div className="btn-row">
              <a className="btn btn-ghost" href={job.result_url} download>Download result</a>
              <button className="btn btn-primary" onClick={reset}>Analyze another video</button>
            </div>
          </div>
        )}

        {phase === 'error' && (
          <div className="result-block">
            <div className="badge badge-red">✗ {error}</div>
            <button className="btn btn-primary" onClick={reset}>Try again</button>
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">Detection summary</h2>
        {detail ? (
          <>
            <ClassBars counts={detail.summary} />
            <div className="detail-meta">
              <span>{detail.frames_processed} frames</span>
              <span>{detail.detections_count} detections</span>
              {detail.meta?.processing_seconds && (
                <span>{detail.meta.processing_seconds}s processing</span>
              )}
            </div>
            <h3 className="card-subtitle">Recent detections</h3>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Time</th><th>Class</th><th>Confidence</th></tr>
                </thead>
                <tbody>
                  {detail.detections.slice(0, 60).map((d) => (
                    <tr key={d.id}>
                      <td>{fmtOffset(d.time_offset)}</td>
                      <td>
                        <span className="class-dot" style={{ background: classColor(d.class_name) }} />
                        {d.class_name}
                      </td>
                      <td>{(d.confidence * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="muted">
            Summary and per-object detections will appear here after processing,
            and are kept in the History tab.
          </p>
        )}
      </section>
    </div>
  )
}
