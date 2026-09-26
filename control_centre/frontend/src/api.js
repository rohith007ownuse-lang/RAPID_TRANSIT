import React from 'react'

// Same-origin by default (dev proxy or a reverse proxy in front of both).
// Set VITE_API_BASE to an absolute origin when the API is hosted separately,
// e.g. VITE_API_BASE=https://api.example.com — the backend must then list
// this frontend's origin in FLEETIQ_CORS_ORIGINS.
const BASE = (import.meta.env && import.meta.env.VITE_API_BASE) || '/api'
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
  demoCredentials: () => get('/auth/demo-credentials', null),
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
  analyticsDrilldown: () => get('/analytics/incidents-drilldown'),
  risk: () => get('/risk'),
  busRisk: (id) => get(`/buses/${encodeURIComponent(id)}/risk`),
  busRiskHistory: (id, limit = 20) => get(`/buses/${encodeURIComponent(id)}/risk/history?limit=${limit}`),
  busRiskTrend: (id) => get(`/buses/${encodeURIComponent(id)}/risk/trend`),
  busRiskPrediction: (id, minutes = 30) => get(`/risk/predict/${encodeURIComponent(id)}?minutes=${minutes}`),
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

  // Traffic heat-map + maintenance (Rapid Transit upgrades)
  trafficHotspots: () => get('/traffic/hotspots'),
  trafficAnalytics: () => get('/traffic/analytics'),
  trafficHeatmap: () => get('/traffic/heatmap'),
  trafficStats: () => get('/traffic/stats'),
  pedestrianStats: () => get('/pedestrian/stats'),
  odAnalytics: () => get('/od/analytics'),
  operationsAnalytics: () => get('/analytics/operations'),
  busHealth: (id) => get(`/buses/${encodeURIComponent(id)}/health`),
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
  aiInsights: () => get('/ai/insights'),
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
  assignIncident: (id, opts = {}) => postJson(`/incidents/${id}/assign`, opts),
  respondIncident: (id, opts = {}) => postJson(`/incidents/${id}/respond`, opts),
  rejectIncident: (id, opts = {}) => postJson(`/incidents/${id}/reject`, opts),
  assignedIncidents: () => get('/incidents/assigned'),
  resolveIncident: (id, opts = {}) => postJson(`/incidents/${id}/resolve`, opts),
  closeIncident: (id, opts = {}) => postJson(`/incidents/${id}/close`, opts),

  // ---- WebSocket Status (Phase 18) ----
  websocketStatus: () => get('/websocket/status'),
  websocketMetrics: () => get('/websocket/metrics'),

  // ---- System Health (Phase 19) ----
  systemHealth: () => get('/system/health'),
  subsystemHealth: (name) => get(`/system/health/${name}`),

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

  // GTFS / MTC Transit Data
  gtfsSummary: () => get('/gtfs/summary'),
  gtfsRoutes: () => get('/gtfs/routes'),
  gtfsRouteDetail: (routeId) => get(`/gtfs/routes/${routeId}`),
  gtfsStops: () => get('/gtfs/stops'),
  gtfsStopDetail: (stopId) => get(`/gtfs/stops/${stopId}`),
  gtfsSearch: (q) => get(`/gtfs/search?q=${encodeURIComponent(q)}`),
  gtfsRoutePolylines: (q, limit = 60) => get(`/gtfs/routes/polylines?q=${encodeURIComponent(q || '')}&limit=${limit}`),

  // Emergency / Public Safety Intelligence
  emergencySummary: () => get('/emergency/summary'),
  emergencyFacilities: (type) => get(`/emergency/facilities${type ? `?type=${type}` : ''}`),
  emergencyFacilityDetail: (id) => get(`/emergency/facilities/${id}`),
  emergencyNearby: (lat, lon, type, maxResults = 5) => {
    let url = `/emergency/nearby?lat=${lat}&lon=${lon}&max_results=${maxResults}`
    if (type) url += `&type=${type}`
    return get(url)
  },
  emergencyIncidentResponse: (data) => postJson('/emergency/incident-response', data),
  emergencyIncidentResponseById: (id) => postJson(`/emergency/incident-response/${id}`, {}),
  emergencyTransportImpact: (lat, lon, radius = 3) =>
    get(`/emergency/transport-impact?lat=${lat}&lon=${lon}&radius=${radius}`),
  emergencySearch: (q) => get(`/emergency/search?q=${encodeURIComponent(q)}`),
  emergencyContacts: () => get('/emergency/contacts'),

  // ---- Feature Toggles ----
  getFeatures: () => get('/features'),
  toggleFeature: (key, enabled) => postJson('/features', { key, enabled }),
  updateFeatures: (features) => postJson('/features', { features }),

  // ---- V2 Intelligence APIs ----
  // Predictive Incident Intelligence
  v2IncidentPredictionBus: (busId) => get(`/v2/incident-prediction/bus/${encodeURIComponent(busId)}`),
  v2IncidentPredictionFleet: () => get('/v2/incident-prediction/fleet'),

  // Fleet Decision Intelligence
  v2FleetDecisions: () => get('/v2/fleet/decisions'),

  // Decision Intelligence (per-event)
  v2DecisionEvent: (eventId) => get(`/v2/decision/${eventId}`),
  v2DecisionBus: (busId) => get(`/v2/decision/bus/${encodeURIComponent(busId)}`),

  // Road Corridor Intelligence
  v2RoadCorridors: () => get('/v2/roads/corridors'),
  v2RoadCorridor: (id) => get(`/v2/roads/corridor/${id}`),

  // Explainability
  v2ExplainRisk: (busId) => get(`/v2/explain/risk/${encodeURIComponent(busId)}`),
  v2ExplainIncidentPrediction: (busId) => get(`/v2/explain/incident-prediction/${encodeURIComponent(busId)}`),
  v2ExplainDecision: (eventId) => get(`/v2/explain/decision/${eventId}`),

  // Incident Timeline & Replay
  v2IncidentTimeline: (busId, minutes = 60) => get(`/v2/incident-replay/timeline/${encodeURIComponent(busId)}?minutes=${minutes}`),
  v2IncidentReplay: (incidentId) => get(`/v2/incident-replay/${incidentId}`),

  // Demand Prediction
  v2DemandPredict: (minutes = 30) => get(`/v2/demand/predict?minutes=${minutes}`),
  v2DemandOvercrowding: () => get('/v2/demand/overcrowding'),

  // AI Copilot
  v2CopilotQuery: (question, context = {}) => postJson('/v2/copilot/query', { question, context }),
  v2CopilotSuggestions: () => get('/v2/copilot/suggestions'),

  // Phase B: Multi-Source Fusion Engine
  fusionEvents: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return get(`/fusion/events${q ? '?' + q : ''}`)
  },
  fusionStats: () => get('/fusion/stats'),
  fusionEvaluate: (busId) => postJson('/fusion/evaluate', { bus_id: busId }),

  // Phase D: Route-Level Intelligence
  routesIntelligence: () => get('/routes/intelligence'),
  routeIntelligence: (routeCode) => get(`/routes/intelligence/${encodeURIComponent(routeCode)}`),
  cityOverview: () => get('/routes/city-overview'),
  routeRecommendations: () => get('/routes/recommendations'),

  // Phase E: Historical Intelligence
  historicalHotspots: (window = '7d') => get(`/historical/hotspots?window=${window}`),
  historicalPatterns: (window = '7d') => get(`/historical/patterns?window=${window}`),
  historicalRoutes: (window = '7d') => get(`/historical/routes?window=${window}`),
  historicalVehicles: (window = '30d') => get(`/historical/vehicles?window=${window}`),
  historicalComprehensive: (window = '7d') => get(`/historical/comprehensive?window=${window}`),

  // Vehicle Health: review-to-clear a maintenance entry
  reviewMaintenance: (bus_id, opts = {}) => postJson('/health/maintenance/review', { bus_id, ...opts }),

  // Phase F: AI Explainability for Events
  v2ExplainEvent: (eventId) => get(`/v2/explain/event/${encodeURIComponent(eventId)}`),

  // Phase C: Extended Incident Lifecycle
  confirmIncident: (id, opts = {}) => postJson(`/incidents/${id}/confirm`, opts),
  assignIncident: (id, assignee, opts = {}) => postJson(`/incidents/${id}/assign`, { assignee }, opts),
  respondIncident: (id, opts = {}) => postJson(`/incidents/${id}/respond`, {}, opts),
  incidentSla: () => get('/incidents/sla'),
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
