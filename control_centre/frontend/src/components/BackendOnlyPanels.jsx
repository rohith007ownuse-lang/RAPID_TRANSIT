import { api, usePoll } from '../api.js'

/* Shared panels for backend-live but previously UI-orphaned endpoints.
   All rule-based/SIMULATION data — polling only, never auto-acting. */

export function BusCapacityPressureCard({ busId }) {
  const { data: cap } = usePoll(() => api.busCapacity(busId), 15000, [busId])
  const { data: press } = usePoll(() => api.busPressure(busId), 15000, [busId])
  const { data: occ } = usePoll(() => api.busOccupancy(busId), 15000, [busId])
  const { data: expo } = usePoll(() => api.busRoadExposure(busId), 20000, [busId])
  const { data: trend } = usePoll(() => api.busRiskTrend(busId), 20000, [busId])
  if (!cap && !press && !occ && !expo && !trend) return null
  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #8b5cf6' }}>
      <div className="card-header">
        <h3 className="card-title">⚖️ Capacity · Pressure · Road Exposure · Risk Trend</h3>
        {trend?.trend && <span className="badge badge-blue" style={{ fontSize: 10 }}>TREND {trend.trend}</span>}
      </div>
      <div className="flex wrap gap-8" style={{ fontSize: 12 }}>
        {cap && <span className="chip">Capacity {cap.current_occupancy}/{cap.capacity} ({cap.utilization_pct?.toFixed?.(0)}%) · {cap.load_state}</span>}
        {press && <span className="chip">Pressure {press.pressure_pct?.toFixed?.(0)}% · {press.pressure_level}</span>}
        {occ && <span className="chip">Crowd {occ.crowd_level} · {occ.pct}%</span>}
      </div>
      {expo?.exposure && (
        <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
          Road exposure: {expo.exposure.exposure_state || 'CLEAR'} — {String(expo.exposure.evidence || '').slice(0, 220)}
        </div>
      )}
    </div>
  )
}

export function RiskEventsPanel() {
  const { data } = usePoll(() => api.riskEvents({ limit: 8 }), 20000)
  const events = data?.events || []
  return (
    <div className="card mb-16">
      <div className="card-header">
        <h3 className="card-title">📉 Risk Events</h3>
        <span className="badge badge-blue" style={{ fontSize: 10 }}>{data?.count ?? events.length} RECORDED</span>
      </div>
      {events.length === 0
        ? <div className="muted" style={{ fontSize: 12 }}>No risk transitions recorded yet — engine is running, history accumulates as risk is computed.</div>
        : events.slice(0, 8).map((e, i) => (
          <div key={i} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
            <strong>{e.bus_id}</strong> <span className="muted">{e.from_level} → {e.to_level} · {e.reason || ''}</span>
          </div>
        ))}
    </div>
  )
}

export function EtaSummaryPanel() {
  const { data } = usePoll(api.etaSummary, 15000)
  if (!data?.delay_distribution) return null
  const d = data.delay_distribution
  return (
    <div className="card mb-16">
      <div className="card-header"><h3 className="card-title">🐢 Fleet Delay Summary</h3></div>
      <div className="flex wrap gap-8" style={{ fontSize: 12 }}>
        {Object.entries(d).map(([k, v]) => (
          <span key={k} className="chip">{k}: <strong>{v}</strong></span>
        ))}
      </div>
    </div>
  )
}

export function DemandIntelPanel() {
  const { data: intel } = usePoll(api.demandIntelligence, 20000)
  const { data: routes } = usePoll(api.routeDemand, 20000)
  if (!intel && !routes) return null
  const topRoutes = Object.values(routes?.routes || {}).sort((a, b) => (b.avg_utilization_pct || 0) - (a.avg_utilization_pct || 0)).slice(0, 5)
  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #8b5cf6' }}>
      <div className="card-header">
        <h3 className="card-title">📊 Demand Intelligence · Route Demand</h3>
        {intel?.high_utilization_percentage != null && <span className="badge badge-amber" style={{ fontSize: 10 }}>{intel.high_utilization_percentage.toFixed(0)}% HIGH USE</span>}
      </div>
      {intel?.crowding_distribution && (
        <div className="flex wrap gap-8" style={{ fontSize: 12, marginBottom: 8 }}>
          {Object.entries(intel.crowding_distribution).map(([k, v]) => (
            <span key={k} className="chip">{k}: <strong>{v}</strong></span>
          ))}
        </div>
      )}
      {topRoutes.map((r) => (
        <div key={r.route_code} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
          <strong>Route {r.route_code}</strong> <span className="muted">· {r.bus_count} buses · {r.avg_utilization_pct?.toFixed?.(0)}% util · {r.daily_boardings} boardings · {r.demand_level}</span>
        </div>
      ))}
    </div>
  )
}

export function TrafficAnalyticsPanel() {
  const { data } = usePoll(api.trafficAnalytics, 20000)
  if (!data) return null
  const spots = data.active_hotspots || []
  return (
    <div className="card mb-16">
      <div className="card-header">
        <h3 className="card-title">🚦 Traffic Analytics</h3>
        <span className="badge badge-amber" style={{ fontSize: 10 }}>{data.active_count ?? spots.length} ACTIVE HOTSPOTS</span>
      </div>
      {spots.slice(0, 5).map((h) => (
        <div key={h.id} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
          <strong>{h.id}</strong> <span className="muted">· {h.level} · {h.bus_count} buses · {h.latitude?.toFixed?.(3)}, {h.longitude?.toFixed?.(3)}</span>
        </div>
      ))}
      {spots.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No active congestion hotspots.</div>}
    </div>
  )
}

export function HistoricalHotspotsPatternsPanel({ window = '7d' }) {
  const { data: hot } = usePoll(() => api.historicalHotspots(window), 60000)
  const { data: pat } = usePoll(() => api.historicalPatterns(window), 60000)
  const hotspots = hot?.recurring_hotspots || []
  return (
    <div className="card mb-16">
      <div className="card-header">
        <h3 className="card-title">📅 Hotspots & Patterns ({window})</h3>
        <span className="badge badge-blue" style={{ fontSize: 10 }}>{hot?.recurring_count ?? hotspots.length} RECURRING · {pat?.total_events ?? 0} EVENTS</span>
      </div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
        Trend: {pat?.daily_trend || '—'} · Peak hours: {(pat?.peak_hours || []).slice(0, 3).map((h) => `${h.hour}:00 (${h.count})`).join(', ') || '—'}
      </div>
      {hotspots.slice(0, 4).map((h, i) => (
        <div key={i} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
          <strong>{h.incident_count} incidents</strong> <span className="muted">@ {h.location?.lat?.toFixed?.(3)}, {h.location?.lon?.toFixed?.(3)} · {h.pattern} · buses {(h.affected_buses || []).slice(0, 3).join(', ')}</span>
        </div>
      ))}
      {hotspots.length === 0 && <div className="muted" style={{ fontSize: 12 }}>No recurring hotspots in this window.</div>}
    </div>
  )
}

export function IncidentSlaPanel() {
  const { data } = usePoll(api.incidentSla, 20000)
  if (!data) return null
  return (
    <div className="card mb-16">
      <div className="card-header"><h3 className="card-title">⏱️ Response SLA</h3></div>
      <div className="flex wrap gap-8" style={{ fontSize: 12 }}>
        <span className="chip">Total: <strong>{data.total}</strong></span>
        <span className="chip">Within SLA: <strong>{data.within_sla}</strong></span>
        <span className="chip">Exceeded: <strong>{data.exceeded_sla}</strong></span>
        <span className="chip">Avg response: <strong>{data.avg_response_time}</strong></span>
        <span className="chip">Avg resolution: <strong>{data.avg_resolution_time}</strong></span>
      </div>
    </div>
  )
}
