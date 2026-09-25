import React from 'react'

const BASE = '/api'
const TOKEN_KEY = 'aiuc_token'

const AUTH_ROLES = ['operator', 'supervisor', 'admin']

function tokenHeader(tokenOpt) {
  const token = tokenOpt !== undefined ? tokenOpt : localStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Global listeners so auth can be torn down (redirect to login) when the
// backend invalidates a session (401). Registered by AuthProvider.
const unauthorizedHandlers = new Set()
export function onUnauthorized(fn) {
  unauthorizedHandlers.add(fn)
  return () => unauthorizedHandlers.delete(fn)
}
function _notifyUnauthorized() {
  localStorage.removeItem(TOKEN_KEY)
  unauthorizedHandlers.forEach((fn) => fn())
}

async function _handle(res, path) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const err = new Error(body.error || `API ${path} -> ${res.status}`)
    err.status = res.status
    if (res.status === 401) _notifyUnauthorized()
    throw err
  }
  return res.json()
}

async function get(path, tokenOpt) {
  const res = await fetch(`${BASE}${path}`, { headers: tokenHeader(tokenOpt) })
  return _handle(res, path)
}

async function postJson(path, body, tokenOpt) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...tokenHeader(tokenOpt) },
    body: JSON.stringify(body || {}),
  })
  return _handle(res, path)
}

export const api = {
  // ---- Authentication (Phase 5) ----
  login: (body) => postJson('/auth/login', body, null),
  me: (tokenOpt) => get('/auth/me', tokenOpt),
  logout: (tokenOpt) => postJson('/auth/logout', {}, tokenOpt),
  changeOwnPassword: (body) => postJson('/auth/me/password', body),
  listUsers: () => get('/auth/users'),
  createUser: (body) => postJson('/auth/users', body),
  changeRole: (id, role) => postJson(`/auth/users/${id}/role`, { role }),
  setUserActive: (id, active) => postJson(`/auth/users/${id}/active`, { active }),
  resetUserPassword: (id, password) => postJson(`/auth/users/${id}/password`, { password }),

  // ---- Read-only telemetry (no auth required) ----
  overview: () => get('/overview'),
  fleetSummary: () => get('/fleet/summary'),
  buses: () => get('/buses'),
  bus: (id) => get(`/buses/${id}`),
  events: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/events${qs ? `?${qs}` : ''}`)
  },
  roadDefects: () => get('/road-defects'),
  analytics: () => get('/analytics'),
  risk: () => get('/risk'),
  busRisk: (id) => get(`/buses/${encodeURIComponent(id)}/risk`),
  busRiskHistory: (id, limit = 20) => get(`/buses/${encodeURIComponent(id)}/risk/history?limit=${limit}`),
  busRiskTrend: (id) => get(`/buses/${encodeURIComponent(id)}/risk/trend`),
  riskEvents: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/risk/events${qs ? `?${qs}` : ''}`)
  },
  actions: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/actions${qs ? `?${qs}` : ''}`)
  },
  busTimeline: (id) => get(`/buses/${encodeURIComponent(id)}/timeline`),
  predictiveHealth: () => get('/health/predictive'),
  fleetHealth: () => get('/health/fleet'),
  eta: () => get('/eta'),
  etaSummary: () => get('/eta/summary'),
  busEta: (id) => get(`/buses/${encodeURIComponent(id)}/eta`),
  demandIntelligence: () => get('/demand/intelligence'),
  routeDemand: () => get('/demand/routes'),
  busCapacity: (id) => get(`/buses/${encodeURIComponent(id)}/capacity`),
  busOccupancy: (id) => get(`/buses/${encodeURIComponent(id)}/occupancy`),
  busPressure: (id) => get(`/buses/${encodeURIComponent(id)}/pressure`),
  demand: () => get('/demand'),
  busDemand: (id) => get(`/buses/${encodeURIComponent(id)}/demand`),
  roadRisk: () => get('/roads/risk'),
  roadSummary: () => get('/roads/summary'),
  busRoadThreats: (id) => get(`/buses/${encodeURIComponent(id)}/road-threats`),
  busRoadExposure: (id) => get(`/buses/${encodeURIComponent(id)}/road-exposure`),
  roadsExposures: () => get('/roads/exposures'),
  settings: () => get('/settings'),
  getMode: () => get('/mode'),
  liveStatus: () => get('/live/status'),
  cameraStatus: () => get('/camera/status'),
  cameraStream: (slot) => get(`/camera/stream/${slot}`),
  cameraDetections: (slot) => get(`/camera/detections/${slot}`),
  cabinOccupancy: () => get('/cabin/occupancy'),
  aiStatus: () => get('/ai/status'),
  potholeStats: () => get('/ai/pothole/stats'),
  driverState: () => get('/ai/driver/state'),
  ddsStatus: () => get('/dds/status'),
  ddsSubprocess: () => get('/dds/subprocess/status'),
  ddsLogs: () => get('/dds/logs'),

  // ---- Incident Intelligence (Phase 16) ----
  incidents: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/incidents${qs ? `?${qs}` : ''}`)
  },
  activeIncidents: () => get('/incidents/active'),
  incidentSummary: () => get('/incidents/summary'),
  incident: (id) => get(`/incidents/${id}`),
  busIncidents: (busId, limit = 20) => get(`/incidents/by-bus/${encodeURIComponent(busId)}?limit=${limit}`),
  incidentByEvent: (eventId) => get(`/incidents/by-event/${eventId}`),
  acknowledgeIncident: (id, opts = {}) => postJson(`/incidents/${id}/acknowledge`, opts),
  investigateIncident: (id, opts = {}) => postJson(`/incidents/${id}/investigate`, opts),
  resolveIncident: (id, opts = {}) => postJson(`/incidents/${id}/resolve`, opts),
  closeIncident: (id, opts = {}) => postJson(`/incidents/${id}/close`, opts),

  // ---- WebSocket Status (Phase 18) ----
  websocketStatus: () => get('/websocket/status'),
  websocketMetrics: () => get('/websocket/metrics'),

  // ---- Historical Analytics Intelligence (Phase 17) ----
  analyticsHistorical: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/historical${qs ? `?${qs}` : ''}`)
  },
  analyticsKpis: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/kpis${qs ? `?${qs}` : ''}`)
  },
  analyticsEvents: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/events${qs ? `?${qs}` : ''}`)
  },
  analyticsIncidents: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/incidents${qs ? `?${qs}` : ''}`)
  },
  analyticsRisk: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/risk${qs ? `?${qs}` : ''}`)
  },
  analyticsEta: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/eta${qs ? `?${qs}` : ''}`)
  },
  analyticsLoad: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/load${qs ? `?${qs}` : ''}`)
  },
  analyticsRoad: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/road${qs ? `?${qs}` : ''}`)
  },
  analyticsDriverSafety: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/driver-safety${qs ? `?${qs}` : ''}`)
  },
  analyticsRoutes: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/routes${qs ? `?${qs}` : ''}`)
  },
  analyticsBuses: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/buses${qs ? `?${qs}` : ''}`)
  },
  analyticsInsights: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return get(`/analytics/insights${qs ? `?${qs}` : ''}`)
  },

  // ---- Privileged POST actions (autorized by backend; token attached) ----
  acknowledge: (id, opts = {}) => postJson(`/events/${id}/acknowledge`, opts),
  review: (id, opts = {}) => postJson(`/events/${id}/review`, opts),
  resolve: (id, opts = {}) => postJson(`/events/${id}/resolve`, opts),
  setStatus: (id, body = {}) => postJson(`/events/${id}/status`, body),
  setStatusMany: (body = {}) => postJson('/events/status', body),
  ackAction: (id, opts = {}) => postJson(`/actions/${id}/ack`, opts),
  resolveAction: (id, opts = {}) => postJson(`/actions/${id}/resolve`, opts),
  evaluateActions: () => postJson('/actions/evaluate', {}),
  updateSettings: (body) => postJson('/settings', body),
  switchMode: (mode) => postJson('/mode/switch', { mode }),
  setTestMode: (slot) => postJson('/camera/test-mode', { slot }),
  setMultiCamera: () => postJson('/camera/multi-camera', {}),
  startCamera: (slot = 'driver') => postJson('/camera/start', { slot }),
  stopCamera: () => postJson('/camera/stop', {}),
  ddsCalibrate: () => postJson('/dds/calibrate', {}),
  ddsStart: () => postJson('/dds/start', {}),
  ddsStop: () => postJson('/dds/stop', {}),
  ddsReset: () => postJson('/dds/reset', {}),
  ddsSubprocessStart: () => postJson('/dds/subprocess/start', {}),
  ddsSubprocessStop: () => postJson('/dds/subprocess/stop', {}),
}

export function usePoll(fn, intervalMs = 3000, deps = []) {
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState(null)
  React.useEffect(() => {
    let alive = true
    const tick = () =>
      fn()
        .then((d) => alive && setData(d))
        .catch((e) => alive && setError(e))
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      alive = false
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error }
}
