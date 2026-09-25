import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge, riskTone } from '../components/UI.jsx'

function healthStateColor(state) {
  switch (state) {
    case 'HEALTHY': return 'var(--green)'
    case 'WATCH': return 'var(--blue)'
    case 'WARNING': return 'var(--amber)'
    case 'CRITICAL': return 'var(--red)'
    case 'UNKNOWN': return 'var(--muted)'
    default: return 'var(--muted)'
  }
}

function healthStateIcon(state) {
  switch (state) {
    case 'HEALTHY': return '✓'
    case 'WATCH': return '⚠'
    case 'WARNING': return '⚠'
    case 'CRITICAL': return '✗'
    case 'UNKNOWN': return '?'
    default: return '?'
  }
}

function dataSourceBadge(source) {
  const colors = {
    'SIMULATION': 'var(--blue)',
    'LIVE': 'var(--green)',
    'HEURISTIC': 'var(--amber)',
    'MODEL': 'var(--purple)',
    'UNKNOWN': 'var(--muted)',
  }
  return (
    <span className="chip" style={{ background: colors[source] || 'var(--muted)', color: '#fff', fontSize: 9, textTransform: 'uppercase' }}>
      {source}
    </span>
  )
}

function ComponentHealthRow({ name, comp }) {
  const state = comp.health_state || 'UNKNOWN'
  const color = healthStateColor(state)
  const icon = healthStateIcon(state)
  return (
    <div key={name} className="flex justify-between align-center" style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
      <div className="flex align-center" style={{ gap: 8 }}>
        <span style={{ color, fontWeight: 600 }}>{icon}</span>
        <span className="capitalize muted" style={{ textTransform: 'capitalize' }}>{name.replace(/_/g, ' ')}</span>
        <dataSourceBadge source={comp.data_source || 'UNKNOWN'} />
      </div>
      <div className="flex align-center" style={{ gap: 12 }}>
        <span className="mono" style={{ color }}>{comp.value}%</span>
        {comp.trend_per_tick !== undefined && (
          <span className="muted" style={{ fontSize: 10 }}>
            {comp.trend_per_tick > 0 ? '↑' : comp.trend_per_tick < 0 ? '↓' : '→'} {Math.abs(comp.trend_per_tick).toFixed(4)}/tick
          </span>
        )}
        {comp.rul_minutes !== null && comp.rul_minutes !== undefined && (
          <span className="chip" style={{ background: riskTone('WARNING'), color: '#fff', fontSize: 9 }}>
            ~{comp.rul_minutes}m RUL
          </span>
        )}
      </div>
    </div>
  )
}

function AnomalyChip({ anomaly }) {
  const color = anomaly.health_state === 'CRITICAL' ? 'var(--red)' : 'var(--amber)'
  return (
    <span key={anomaly.component} className="chip" style={{ background: color, color: '#fff', fontSize: 10, margin: '2px 4px 2px 0' }}>
      {anomaly.component}: {anomaly.value} ({anomaly.health_state})
    </span>
  )
}

function RecommendationChip({ rec }) {
  const severityColors = {
    'CRITICAL': 'var(--red)',
    'WARNING': 'var(--amber)',
    'INFO': 'var(--blue)',
  }
  const color = severityColors[rec.severity] || 'var(--muted)'
  return (
    <div key={`${rec.component}-${rec.action}`} style={{ fontSize: 11, padding: '6px 8', background: 'var(--bg-elevated)', borderRadius: 6, marginBottom: 4, borderLeft: `3px solid ${color}` }}>
      <div className="flex justify-between align-center">
        <span className="muted capitalize">{rec.component}</span>
        <span className="chip" style={{ background: color, color: '#fff', fontSize: 9 }}>{rec.severity}</span>
      </div>
      <div className="muted" style={{ marginTop: 2 }}>{rec.reason}</div>
      <div className="muted" style={{ fontSize: 10, marginTop: 2 }}>
        <dataSourceBadge source={rec.source || 'UNKNOWN'} />
        <span> {new Date(rec.timestamp).toLocaleTimeString()}</span>
      </div>
    </div>
  )
}

export default function VehicleHealth() {
  const { data } = usePoll(api.buses, 4000)
  const { data: ph } = usePoll(api.predictiveHealth, 6000)
  const { data: fleetHealth } = usePoll(api.fleetHealth, 10000)

  const buses = (data?.buses || []).slice().sort((a, b) => {
    const rank = (h) => (h === 'INSPECTION REQUIRED' ? 0 : h === 'WARNING' ? 1 : 2)
    return rank(a.vehicle.health) - rank(b.vehicle.health)
  })

  return (
    <>
      <PageHeader
        title="Vehicle Health Intelligence"
        sub="Component health, anomaly detection, maintenance recommendations (simulated demo)"
        right={<SimBadge />}
      />

      {/* Fleet Health Summary */}
      {fleetHealth?.fleet && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ borderTop: '4px solid var(--green)' }}>
            <div className="muted" style={{ fontSize: 11 }}>HEALTHY</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--green)' }}>{fleetHealth.fleet.healthy || 0}</div>
          </div>
          <div className="card" style={{ borderTop: '4px solid var(--blue)' }}>
            <div className="muted" style={{ fontSize: 11 }}>WATCH</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--blue)' }}>{fleetHealth.fleet.watch || 0}</div>
          </div>
          <div className="card" style={{ borderTop: '4px solid var(--amber)' }}>
            <div className="muted" style={{ fontSize: 11 }}>WARNING</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--amber)' }}>{fleetHealth.fleet.warning || 0}</div>
          </div>
          <div className="card" style={{ borderTop: '4px solid var(--red)' }}>
            <div className="muted" style={{ fontSize: 11 }}>CRITICAL</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--red)' }}>{fleetHealth.fleet.critical || 0}</div>
          </div>
          <div className="card" style={{ borderTop: '4px solid var(--muted)' }}>
            <div className="muted" style={{ fontSize: 11 }}>UNKNOWN</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--muted)' }}>{fleetHealth.fleet.unknown || 0}</div>
          </div>
        </div>
      )}

      {/* Bus Cards */}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 16 }}>
        {buses.map((b) => {
          const v = b.vehicle
          const tone = v.health === 'NORMAL' ? 'green' : v.health === 'WARNING' ? 'amber' : 'red'
          const toneColor = tone === 'green' ? 'var(--green)' : tone === 'amber' ? 'var(--amber)' : 'var(--red)'
          const pred = ph?.predictions?.[b.bus_id] || []
          const summary = ph?.summaries?.[b.bus_id] || {}
          const anomalies = ph?.anomalies?.[b.bus_id] || []
          const recommendations = ph?.recommendations?.[b.bus_id] || []

          return (
            <div className="card" key={b.bus_id} style={{ borderTop: `4px solid ${toneColor}` }}>
              <div className="flex justify-between align-center mb-8">
                <div>
                  <strong>{b.bus_id}</strong>
                  <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>{b.route_code || b.route}</span>
                </div>
                <div className="flex align-center" style={{ gap: 8 }}>
                  <StatusBadge status={v.health} />
                  <dataSourceBadge source={ph?.data_source || 'SIMULATION'} />
                </div>
              </div>

              {/* Current Vehicle State */}
              <div style={{ fontSize: 12, lineHeight: 1.9, marginBottom: 12 }}>
                <div className="flex justify-between">
                  <span className="muted">Health:</span>
                  <strong style={{ color: toneColor }}>{v.health}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="muted">Vibration:</span>
                  <span className="mono">{v.vibration?.toFixed(2) || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="muted">Maintenance:</span>
                  <span>{v.maintenance_priority || 'LOW'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="muted">Braking Events:</span>
                  <span>{v.braking_events || 0}</span>
                </div>
                <div className="flex justify-between">
                  <span className="muted">Anomaly:</span>
                  <span>{v.anomaly === 'none' ? 'None' : v.anomaly}</span>
                </div>
              </div>

              {/* Component Health */}
              {Object.keys(summary).length > 0 && (
                <div className="mt-8" style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                  <div className="flex justify-between align-center mb-4">
                    <div className="muted" style={{ fontSize: 11 }}>🔧 Component Health (Heuristic Rolling Counters)</div>
                    <dataSourceBadge source={summary.tyre_fl?.data_source || 'SIMULATION'} />
                  </div>
                  <div style={{ fontSize: 11 }}>
                    {Object.entries(summary).map(([name, comp]) => (
                      <ComponentHealthRow key={name} name={name} comp={comp} />
                    ))}
                  </div>
                </div>
              )}

              {/* Anomalies */}
              {anomalies.length > 0 && (
                <div className="mt-8" style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>⚠ Active Anomalies</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {anomalies.map((a, i) => <AnomalyChip key={i} anomaly={a} />)}
                  </div>
                </div>
              )}

              {/* Maintenance Recommendations */}
              {recommendations.length > 0 && (
                <div className="mt-8" style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>🔧 Maintenance Recommendations</div>
                  <div style={{ maxHeight: 200, overflow: 'auto' }}>
                    {recommendations.map((r, i) => <RecommendationChip key={i} rec={r} />)}
                  </div>
                </div>
              )}

              {/* Legacy Predictions (backward compat) */}
              {pred.length > 0 && Object.keys(summary).length === 0 && (
                <div className="mt-8" style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>🔮 Predictive Degradation</div>
                  <div className="grid" style={{ gap: 4, gridTemplateColumns: '1fr 1fr' }}>
                    {Object.entries(summary).map(([name, comp]) => (
                      <div key={name} className="flex justify-between" style={{ fontSize: 11 }}>
                        <span className="muted capitalize">{name.replace('_', ' ')}</span>
                        <span className="mono">
                          {comp.value}%
                          {comp.rul_ticks ? <span className="muted"> · ~{comp.rul_minutes}m RUL</span> : null}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-4">
                    {pred.map((p, i) => (
                      <span key={i} className="chip" style={{ background: riskTone(p.severity), color: '#fff', fontSize: 10.5 }}>
                        {p.type}: {p.component} ({p.rul_ticks} ticks)
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Scope / Methodology */}
      <div className="card mt-16">
        <div className="card-header"><h3 className="card-title">Methodology & Data Honesty</h3></div>
        <div className="muted" style={{ fontSize: 13, lineHeight: 1.8 }}>
          <strong>Data Source:</strong> All values are <strong>SIMULATION</strong> (heuristic rolling counters) unless a live bus node is streaming.
          <br/><br/>
          <strong>Components Tracked:</strong> Tyres (FL/FR/RL/RR wear), Vibration (RMS), Harsh Braking Rate, Energy/Battery Degradation.
          <br/><br/>
          <strong>Health States:</strong> HEALTHY → WATCH → WARNING → CRITICAL based on component-specific thresholds. UNKNOWN when sensor data unavailable.
          <br/><br/>
          <strong>RUL (Remaining Useful Life):</strong> Linear trend projection from last 10 samples — <strong>not a trained ML model</strong>.
          <br/><br/>
          <strong>Anomaly Detection:</strong> Rule-based thresholds on component health states. No statistical/ML anomaly detection implemented yet.
          <br/><br/>
          <strong>Maintenance Recommendations:</strong> Rule-based heuristics tied to component thresholds and evidence. Not automated mechanical diagnosis.
          <br/><br/>
          <strong>Persistence:</strong> Health events stored in SQLite; rolling counters are in-memory (reset on restart).
          <br/><br/>
          Future vehicle telemetry (real IMU, tyre pressure, battery BMS) will replace synthetic counters.
        </div>
      </div>
    </>
  )
}