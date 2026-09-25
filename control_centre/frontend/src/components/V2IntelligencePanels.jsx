import { useState, useEffect } from 'react'
import { api, usePoll } from '../api.js'

/* ─── Incident Prediction Card ─── */
function IncidentPredictionCard() {
  const { data: predictions } = usePoll(api.v2IncidentPredictionFleet, 15000)

  if (!predictions?.fleet_summary) return null

  const { fleet_summary, predictions: preds } = predictions
  const highRisk = (preds || []).filter(
    (p) => p.probability_level === 'HIGH' || p.probability_level === 'CRITICAL'
  )

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #f59e0b' }}>
      <div className="card-header">
        <h3 className="card-title">🔮 Predictive Incident Intelligence</h3>
        <div style={{ display: 'flex', gap: 6 }}>
          {fleet_summary.high_risk_count > 0 && (
            <span className="badge badge-red" style={{ fontSize: 10 }}>
              {fleet_summary.high_risk_count} HIGH RISK
            </span>
          )}
          {fleet_summary.elevated_count > 0 && (
            <span className="badge badge-amber" style={{ fontSize: 10 }}>
              {fleet_summary.elevated_count} ELEVATED
            </span>
          )}
          <span className="badge badge-blue" style={{ fontSize: 10 }}>
            AVG {fleet_summary.avg_incident_probability?.toFixed(0)}%
          </span>
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 8 }}>
        Multi-signal correlation: driver + vehicle + road + load + traffic + history
      </div>
      {highRisk.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {highRisk.slice(0, 4).map((p) => (
            <div
              key={p.bus_id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 10px',
                background: p.probability_level === 'CRITICAL' ? '#fef2f2' : '#fffbeb',
                borderLeft: `3px solid ${p.probability_level === 'CRITICAL' ? '#dc2626' : '#f59e0b'}`,
                borderRadius: 4,
                fontSize: 12,
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 70 }}>Bus {p.bus_id}</span>
              <span style={{
                fontSize: 11,
                padding: '2px 6px',
                borderRadius: 4,
                background: p.probability_level === 'CRITICAL' ? '#dc2626' : '#f59e0b',
                color: '#fff',
              }}>
                {p.incident_probability?.toFixed(0)}%
              </span>
              <span style={{ fontSize: 11, color: '#6b7280', flex: 1 }}>
                {p.degraded_signal_count} signal(s) degraded
              </span>
              <span style={{ fontSize: 10, color: '#9ca3af' }}>
                {p.lead_time?.estimated_minutes || '?'} min lead
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#16a34a', padding: '8px 0' }}>
          No buses with elevated incident probability detected.
        </div>
      )}
    </div>
  )
}

/* ─── Fleet Decision Card ─── */
function FleetDecisionCard() {
  const { data: decisions } = usePoll(api.v2FleetDecisions, 20000)

  if (!decisions?.summary) return null

  const { summary, priority_actions } = decisions

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #3b82f6' }}>
      <div className="card-header">
        <h3 className="card-title">🧠 Fleet Decision Intelligence</h3>
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="badge badge-blue" style={{ fontSize: 10 }}>
            HEALTH {summary.fleet_health_score}/100
          </span>
          {summary.high_priority_actions > 0 && (
            <span className="badge badge-red" style={{ fontSize: 10 }}>
              {summary.high_priority_actions} HIGH PRIORITY
            </span>
          )}
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 8 }}>
        Rebalancing, deployment, route adjustments, bus spacing
      </div>
      {priority_actions?.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {priority_actions.slice(0, 5).map((action, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '5px 8px',
                background: action.priority === 'HIGH' ? '#fef2f2' : '#f8fafc',
                borderLeft: `3px solid ${action.priority === 'HIGH' ? '#dc2626' : '#94a3b8'}`,
                borderRadius: 4,
                fontSize: 11,
              }}
            >
              <span style={{
                fontSize: 9,
                padding: '1px 4px',
                borderRadius: 3,
                background: action.priority === 'HIGH' ? '#dc2626' : '#6b7280',
                color: '#fff',
                fontWeight: 600,
              }}>
                {action.priority}
              </span>
              <span style={{ flex: 1 }}>{action.action || action.reason || action.type}</span>
              {action.route && (
                <span className="muted" style={{ fontSize: 10 }}>{action.route}</span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#16a34a', padding: '8px 0' }}>
          Fleet operating within normal parameters.
        </div>
      )}
    </div>
  )
}

/* ─── Road Corridor Card ─── */
function RoadCorridorCard() {
  const { data: corridors } = usePoll(api.v2RoadCorridors, 20000)

  if (!corridors?.summary) return null

  const { summary, corridors: rawCorridorList } = corridors
  // Backend returns corridors as a dict keyed by corridor_id ({} while risk
  // zones are still seeding after a restart); tolerate array shapes too.
  const corridorList = Array.isArray(rawCorridorList)
    ? rawCorridorList
    : Object.values(rawCorridorList || {})
  const sorted = [...corridorList].sort((a, b) => (b.computed_score || 0) - (a.computed_score || 0))

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #10b981' }}>
      <div className="card-header">
        <h3 className="card-title">🛣️ Road Risk Corridors</h3>
        <div style={{ display: 'flex', gap: 6 }}>
          {summary.needs_attention && (
            <span className="badge badge-red" style={{ fontSize: 10 }}>
              NEEDS ATTENTION
            </span>
          )}
          {summary.critical > 0 && (
            <span className="badge badge-red" style={{ fontSize: 10 }}>
              {summary.critical} CRITICAL
            </span>
          )}
          {summary.high > 0 && (
            <span className="badge badge-amber" style={{ fontSize: 10 }}>
              {summary.high} HIGH
            </span>
          )}
          <span className="badge badge-blue" style={{ fontSize: 10 }}>
            {summary.total_corridors} CORRIDORS · {summary.overall_status}
          </span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
        {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((level) => (
          <div key={level} style={{ textAlign: 'center' }}>
            <div style={{
              fontSize: 18,
              fontWeight: 700,
              color: level === 'CRITICAL' ? '#dc2626' : level === 'HIGH' ? '#f59e0b' : level === 'MEDIUM' ? '#2563eb' : '#16a34a',
            }}>
              {summary[level.toLowerCase()] || 0}
            </div>
            <div style={{ fontSize: 9, color: '#6b7280', textTransform: 'uppercase' }}>{level}</div>
          </div>
        ))}
      </div>
      {sorted.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {sorted.slice(0, 5).map((c) => (
            <div
              key={c.corridor_id}
              style={{
                padding: '5px 8px',
                background: c.computed_level === 'CRITICAL' ? '#fef2f2' : c.computed_level === 'HIGH' ? '#fffbeb' : '#f8fafc',
                borderLeft: `3px solid ${c.computed_level === 'CRITICAL' ? '#dc2626' : c.computed_level === 'HIGH' ? '#f59e0b' : c.computed_level === 'MEDIUM' ? '#2563eb' : '#16a34a'}`,
                borderRadius: 4,
                fontSize: 11,
              }}
            >
              <span style={{ fontWeight: 600 }}>{c.corridor_id}</span>
              <span style={{ marginLeft: 8, color: '#6b7280' }}>
                {c.computed_level} {c.computed_score?.toFixed(0)}/100 · {c.defect_count} defects · {c.detection_count} detections
              </span>
              <div style={{ color: '#6b7280', marginTop: 2 }}>{c.explanation}</div>
              <div style={{ color: '#9ca3af' }}>
                Routes: {(c.affected_routes || []).join(', ') || '—'} · {c.signal_sources?.join(', ')} · {(c.recommended_actions || []).join(' · ')}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#6b7280', padding: '8px 0' }}>
          No corridors yet — risk zones are still seeding (engine polls every 20s; corridors appear once defects cluster).
        </div>
      )}
    </div>
  )
}

/* ─── Demand Prediction Card ─── */
function DemandPredictionCard() {
  const { data: demand } = usePoll(() => api.v2DemandPredict(30), 20000)

  if (!demand?.fleet_summary) return null

  const { fleet_summary, predictions } = demand
  const highRiskRoutes = (predictions || []).filter(
    (p) => p.overcrowding_risk === 'HIGH' || p.overcrowding_risk === 'CRITICAL'
  )

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #8b5cf6' }}>
      <div className="card-header">
        <h3 className="card-title">📊 Demand Prediction</h3>
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="badge badge-blue" style={{ fontSize: 10 }}>
            {fleet_summary.minutes_ahead} MIN FORECAST
          </span>
          <span className="badge" style={{
            fontSize: 10,
            background: fleet_summary.demand_trend === 'INCREASING' ? '#fee2e2' : fleet_summary.demand_trend === 'DECREASING' ? '#dcfce7' : '#e0e7ff',
            color: fleet_summary.demand_trend === 'INCREASING' ? '#dc2626' : fleet_summary.demand_trend === 'DECREASING' ? '#16a34a' : '#2563eb',
          }}>
            {fleet_summary.demand_trend}
          </span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 24, marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase' }}>Current Avg</div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{fleet_summary.current_avg_occupancy?.toFixed(0)}%</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase' }}>Predicted Avg</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: fleet_summary.predicted_avg_occupancy > fleet_summary.current_avg_occupancy ? '#dc2626' : '#16a34a' }}>
            {fleet_summary.predicted_avg_occupancy?.toFixed(0)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase' }}>High Risk Routes</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: fleet_summary.high_risk_routes > 0 ? '#dc2626' : '#16a34a' }}>
            {fleet_summary.high_risk_routes}
          </div>
        </div>
      </div>
      {highRiskRoutes.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {highRiskRoutes.slice(0, 3).map((r) => (
            <div
              key={r.route_code}
              style={{
                padding: '5px 8px',
                background: r.overcrowding_risk === 'CRITICAL' ? '#fef2f2' : '#fffbeb',
                borderLeft: `3px solid ${r.overcrowding_risk === 'CRITICAL' ? '#dc2626' : '#f59e0b'}`,
                borderRadius: 4,
                fontSize: 11,
              }}
            >
              <span style={{ fontWeight: 600 }}>Route {r.route_code}</span>
              <span style={{ marginLeft: 8 }}>
                Current: {r.current_avg_occupancy?.toFixed(0)}% → Predicted: {r.predicted_avg_occupancy?.toFixed(0)}%
              </span>
              <span style={{ marginLeft: 8, color: '#dc2626' }}>{r.overcrowding_risk}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ─── Export all panels ─── */
export { IncidentPredictionCard, FleetDecisionCard, RoadCorridorCard, DemandPredictionCard }

export default function V2IntelligencePanels() {
  return (
    <>
      <IncidentPredictionCard />
      <FleetDecisionCard />
      <RoadCorridorCard />
      <DemandPredictionCard />
    </>
  )
}
