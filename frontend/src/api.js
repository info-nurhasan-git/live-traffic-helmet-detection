const json = async (res) => {
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

export const getConfig = () => fetch('/api/config').then(json)
export const getStats = () => fetch('/api/stats').then(json)
export const getHistory = (mode) =>
  fetch(`/api/history${mode ? `?mode=${mode}` : ''}`).then(json)
export const getSession = (id) => fetch(`/api/history/${id}`).then(json)
export const deleteSession = (id) =>
  fetch(`/api/history/${id}`, { method: 'DELETE' }).then(json)
export const getJob = (id) => fetch(`/api/video/jobs/${id}`).then(json)
export const cancelJob = (id) =>
  fetch(`/api/video/jobs/${id}/cancel`, { method: 'POST' }).then(json)

export const uploadVideo = (file) => {
  const form = new FormData()
  form.append('file', file)
  return fetch('/api/video/upload', { method: 'POST', body: form }).then(json)
}

export const wsUrl = (path) =>
  `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`

export const refreshStats = () => window.dispatchEvent(new Event('stats-refresh'))
export const getEvents = (params = {}) => {
  const q = new URLSearchParams(params)
  return fetch(`/api/events?${q}`).then(json)
}
export const deleteEvent = (id) =>
  fetch(`/api/events/${id}`, { method: 'DELETE' }).then(json)

export const CLASS_COLORS = {
  person: '#2563eb',
  bicycle: '#d97706',
  car: '#0891b2',
  motorcycle: '#dc2626',
  bus: '#059669',
  truck: '#7c3aed',
  helmet: '#16a34a',
  no_helmet: '#dc2626',
  license_plate: '#db2777',
}
export const classColor = (name) =>
  CLASS_COLORS[String(name).toLowerCase()] || '#64748b'

export const fmtTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString()
}

export const fmtOffset = (sec) => {
  const m = Math.floor(sec / 60)
  const s = (sec % 60).toFixed(1)
  return `${m}:${s.padStart(4, '0')}`
}
