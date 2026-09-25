import React from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader } from '../components/Layout.jsx'
import { StatusBadge, riskTone } from '../components/UI.jsx'

function DataSourceBadge({ source }) {
  const colors = {
    'ESTIMATED': 'var(--blue)',
    'LIVE': 'var(--green)',
    'HEURISTIC': 'var(--amber)',
    'MODEL': 'var(--purple)',
    'UNKNOWN': 'var(--muted)',
  }
  const label = source === 'SIMULATION' ? 'ESTIMATED' : source
  return (
    <span className="chip" style={{ background: colors[label] || 'var(--muted)', color: '#fff', fontSize: 9, textTransform: 'uppercase' }}>
      {label}
    </span>
  )
}

function decisionColors(status) {
  if (status === 'SEND_TO_MAINTENANCE') return { bg: '#fecaca', fg: '#991b1b', border: '#fca5a5', bar: 'var(--red)' }
  if (status === 'PLAN_MAINTENANCE') return { bg: '#fed7aa', fg: '#9a3412', border: '#fdba74', bar: 'var(--amber)' }
  return { bg: '#dcfce7', fg: '#166534', border: '#86efac', bar: 'var(--green)' }
}

function shortStatus(status) {
  return (status || 'CAN_CONTINUE').replace(/_/g, ' ')
}

export default function VehicleHealth() {
  const { data } = usePoll(api.buses, 4000)
  const { data: ph } = usePoll(api.predictiveHealth, 6000)
  const { data: fleetHealth } = usePoll(api.fleetHealth, 10000)
  const { data: eventsData } = usePoll(api.events, 8000)
  const [filter, setFilter] = React.useState('all') // all | watch | critical | reviewed
  const [selected, setSelected] = React.useState(null) // bus_id for detail modal
  const [reviewing, setReviewing] = React.useState(null)

  const buses = data?.buses || []
  const busById = Object.fromEntries(buses.map((b) => [b.bus_id, b]))
  const summaries = ph?.summaries || {}
  const reviews = ph?.maintenance_reviews || {}
  const events = eventsData?.events || []

  async function markReviewed(busId) {
    setReviewing(busId)
    try {
      await api.reviewMaintenance(busId, {})
    } catch (e) { /* button resets; next poll retries */ }
    setReviewing(null)
    setSelected(null)
  }

  const rows = Object.entries(summaries).map(([busId, vh]) => {
    const decision = vh.maintenance_decision || {}
    const comps = Object.values(vh.components || {})
    const worstDay = comps.reduce((m, c) => (c.rul_days != null && (m == null || c.rul_days < m) ? c.rul_days : m), null)
    const bus = busById[busId] || {}
    return {
      bus_id: busId,
      route: bus?.route_code || bus?.route || '—',
      route_name: bus?.route || '—',
      reg_no: bus?.reg_no || '—',
      driver: bus?.driver?.name || '—',
      driver_state: bus?.driver?.state || '—',
      overall_state: vh.overall_state,
      overall_score: vh.overall_score,
      decision,
      days: decision.days_to_failure ?? worstDay,
      component: decision.component,
      comps,
      warnings: comps.filter((c) => c.health_state === 'WARNING' || c.health_state === 'CRITICAL'),
      sticky: !!vh.sticky,
      first_flagged_at: vh.first_flagged_at,
      review: reviews[busId],
    }
  })

  // Review-to-clear: reviewed buses leave the list; everything else stays,
  // sorted by soonest predicted failure (days-to-failure ascending).
  const needsAttention = rows
    .filter((r) => r.decision.status && r.decision.status !== 'CAN_CONTINUE' && !r.review)
    .sort((a, b) => (a.days ?? Infinity) - (b.days ?? Infinity))

  const reviewedRows = rows.filter((r) => r.review)
  const watchRows = needsAttention.filter((r) => r.decision.status === 'PLAN_MAINTENANCE')
  const criticalRows = needsAttention.filter((r) => r.decision.status === 'SEND_TO_MAINTENANCE')
  const visible = filter === 'watch' ? watchRows : filter === 'critical' ? criticalRows : filter === 'reviewed' ? reviewedRows : needsAttention

  const sendNow = criticalRows
  const planSoon = watchRows
  const healthy = rows.length - needsAttention.length - reviewedRows.length

  const selectedRow = selected ? rows.find((r) => r.bus_id === selected) : null
  const selectedEvents = selected ? events.filter((e) => e.bus_id === selected).slice(0, 10) : []

  return (
    <>
      <PageHeader
        title="Vehicle Health Intelligence"
        sub="Review-to-clear — a vehicle stays in the maintenance list until an operator reviews it"
      />

      {/* Fleet Health Summary — click WATCH / CRITICAL to filter the list below */}
      {fleetHealth?.fleet && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ borderTop: '4px solid var(--green)' }}>
            <div className="muted" style={{ fontSize: 11 }}>HEALTHY</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--green)' }}>{fleetHealth.fleet.healthy || 0}</div>
          </div>
          <div className="card" onClick={() => setFilter(filter === 'watch' ? 'all' : 'watch')} title="Show plan-maintenance (watch) vehicles" style={{ borderTop: '4px solid var(--blue)', cursor: 'pointer', outline: filter === 'watch' ? '2px solid var(--blue)' : 'none' }}>
            <div className="muted" style={{ fontSize: 11 }}>WATCH — click to list</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--blue)' }}>{fleetHealth.fleet.watch || 0}</div>
          </div>
          <div className="card" style={{ borderTop: '4px solid var(--amber)' }}>
            <div className="muted" style={{ fontSize: 11 }}>WARNING</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--amber)' }}>{fleetHealth.fleet.warning || 0}</div>
          </div>
          <div className="card" onClick={() => setFilter(filter === 'critical' ? 'all' : 'critical')} title="Show send-to-maintenance (critical) vehicles with full report" style={{ borderTop: '4px solid var(--red)', cursor: 'pointer', outline: filter === 'critical' ? '2px solid var(--red)' : 'none' }}>
            <div className="muted" style={{ fontSize: 11 }}>CRITICAL — click to list</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--red)' }}>{fleetHealth.fleet.critical || 0}</div>
          </div>
          <div className="card" style={{ borderTop: '4px solid var(--muted)' }}>
            <div className="muted" style={{ fontSize: 11 }}>UNKNOWN</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--muted)' }}>{fleetHealth.fleet.unknown || 0}</div>
          </div>
        </div>
      )}

      {/* Maintenance decision summary */}
      <div className="grid mb-16" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
        <div className="card" style={{ borderTop: '4px solid var(--red)' }}>
          <div className="muted" style={{ fontSize: 11 }}>SEND TO MAINTENANCE ≤1 DAY</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--red)' }}>{sendNow.length}</div>
        </div>
        <div className="card" style={{ borderTop: '4px solid var(--amber)' }}>
          <div className="muted" style={{ fontSize: 11 }}>PLAN MAINTENANCE ≤3 DAYS</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--amber)' }}>{planSoon.length}</div>
        </div>
        <div className="card" style={{ borderTop: '4px solid var(--green)' }}>
          <div className="muted" style={{ fontSize: 11 }}>CAN CONTINUE</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--green)' }}>{healthy}</div>
        </div>
      </div>

      {/* Priority: only vehicles that need maintenance (sticky until reviewed) */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">⚠ Vehicles Needing Maintenance</h3>
          <div className="flex align-center gap-8">
            <span className="muted" style={{ fontSize: 12 }}>sorted by soonest predicted failure · stays until reviewed</span>
            <DataSourceBadge source={ph?.data_source || 'ESTIMATED'} />
          </div>
        </div>
        <div className="flex gap-8 mb-8">
          {[['all', `All (${needsAttention.length})`], ['critical', `Critical (${criticalRows.length})`], ['watch', `Watch (${watchRows.length})`], ['reviewed', `Reviewed (${reviewedRows.length})`]].map(([k, label]) => (
            <button key={k} className={`seg ${filter === k ? 'active' : ''}`} onClick={() => setFilter(k)} style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid #d1d5db', background: filter === k ? '#111827' : '#fff', color: filter === k ? '#fff' : '#374151', fontSize: 12, cursor: 'pointer' }}>{label}</button>
          ))}
        </div>
        {!ph ? (
          <div className="empty">Computing vehicle health…</div>
        ) : visible.length === 0 ? (
          <div className="empty">{filter === 'reviewed' ? 'No reviewed vehicles yet.' : 'No vehicle currently needs maintenance — whole fleet can continue.'}</div>
        ) : (
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
            {visible.map((r) => {
              const c = decisionColors(r.decision.status)
              return (
                <div key={r.bus_id} className="card" onClick={() => setSelected(r.bus_id)} title="Open full vehicle report — cause, route, problem history" style={{ borderTop: `4px solid ${c.bar}`, cursor: 'pointer' }}>
                  <div className="flex justify-between align-start mb-8">
                    <div>
                      <strong>{r.bus_id}</strong>
                      <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>{r.route}</span>
                      <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                        health score {r.overall_score}/100 · {r.overall_state}
                        {r.sticky && <span className="chip" style={{ marginLeft: 6, fontSize: 9, background: '#fef3c7', color: '#92400e' }}>STICKY — awaiting review</span>}
                        {r.review && <span className="chip" style={{ marginLeft: 6, fontSize: 9, background: '#dcfce7', color: '#166534' }}>REVIEWED by {r.review.reviewed_by}</span>}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0, padding: '4px 10px', borderRadius: 6, background: c.bg, border: `1px solid ${c.border}` }}>
                      <div style={{ fontSize: 24, fontWeight: 800, lineHeight: 1, color: c.fg }}>{r.days != null ? r.days : '—'}</div>
                      <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, color: c.fg }}>days to failure</div>
                    </div>
                  </div>

                  <div className="chip" style={{ background: c.bg, color: c.fg, fontSize: 10, marginBottom: 8 }}>
                    {shortStatus(r.decision.status)}
                  </div>

                  {r.decision.reason && (
                    <div className="muted" style={{ fontSize: 11.5, marginBottom: 8 }}>{r.decision.reason}</div>
                  )}

                  <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                    AT-RISK COMPONENTS ({r.warnings.length})
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {r.warnings.length === 0 && <span className="muted" style={{ fontSize: 11 }}>—</span>}
                    {r.warnings.map((comp) => (
                      <span
                        key={comp.name}
                        className="chip"
                        style={{ background: riskTone(comp.health_state), color: '#fff', fontSize: 10 }}
                        title={`${comp.component_type}: value ${comp.value}`}
                      >
                        {comp.component_type} · {comp.health_state} · {comp.rul_days != null ? `${comp.rul_days}d` : 'no RUL'}
                      </span>
                    ))}
                  </div>

                  {!r.review && (
                    <button
                      className="btn btn-sm"
                      style={{ marginTop: 10, background: '#166534', color: '#fff', border: 'none', borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: 'pointer' }}
                      disabled={reviewing === r.bus_id}
                      onClick={(e) => { e.stopPropagation(); markReviewed(r.bus_id) }}
                    >
                      {reviewing === r.bus_id ? 'Reviewing…' : '✓ Mark reviewed — clear from list'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Vehicle detail modal — cause, usual route, problem history */}
      {selectedRow && (
        <div onMouseDown={(e) => { if (e.target === e.currentTarget) setSelected(null) }} style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(15,23,42,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <div style={{ background: '#fff', borderRadius: 12, width: 640, maxWidth: '100%', boxShadow: '0 20px 50px rgba(0,0,0,0.25)', padding: 18, maxHeight: '88vh', overflowY: 'auto' }}>
            <div className="flex justify-between align-center mb-8">
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>🔧 {selectedRow.bus_id} — full vehicle report</h3>
              <button className="btn btn-ghost" style={{ fontSize: 14, padding: '2px 8px' }} onClick={() => setSelected(null)}>✕</button>
            </div>
            <div className="muted" style={{ fontSize: 12, lineHeight: 1.8 }}>
              <div>🚌 Registration: <strong>{selectedRow.reg_no}</strong> · Usual route: <strong>{selectedRow.route}</strong> ({selectedRow.route_name})</div>
              <div>🧑‍✈️ Driver: <strong>{selectedRow.driver}</strong> ({selectedRow.driver_state})</div>
              <div>📅 Problem on record since: <strong>{selectedRow.first_flagged_at ? new Date(selectedRow.first_flagged_at).toLocaleString() : 'this session'}</strong>{selectedRow.sticky && ' (kept sticky — counters recovered but review pending)'}</div>
              <div>⏳ Predicted days to failure: <strong>{selectedRow.days ?? '—'}</strong> · Health score: <strong>{selectedRow.overall_score}/100</strong> ({selectedRow.overall_state})</div>
              <div>🔍 Likely cause: <strong>{selectedRow.decision.component || selectedRow.warnings[0]?.component_type || 'under observation'}</strong> — {selectedRow.decision.reason}</div>
              {selectedRow.review && <div>✅ Reviewed by <strong>{selectedRow.review.reviewed_by}</strong> at {new Date(selectedRow.review.reviewed_at).toLocaleString()}</div>}
            </div>
            <div className="muted" style={{ fontSize: 11, marginTop: 8, marginBottom: 4 }}>AT-RISK COMPONENTS</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
              {selectedRow.warnings.map((comp) => (
                <span key={comp.name} className="chip" style={{ background: riskTone(comp.health_state), color: '#fff', fontSize: 10 }}>
                  {comp.component_type} · {comp.health_state} · {comp.rul_days != null ? `${comp.rul_days}d RUL` : 'no RUL'} · value {comp.value}
                </span>
              ))}
              {selectedRow.warnings.length === 0 && <span className="muted" style={{ fontSize: 11 }}>—</span>}
            </div>
            <div className="muted" style={{ fontSize: 11, marginTop: 8, marginBottom: 4 }}>RECENT EVENTS FOR THIS BUS</div>
            {selectedEvents.length === 0 && <div className="empty">No recent events for this bus.</div>}
            {selectedEvents.map((e) => (
              <div key={e.event_id} style={{ border: '1px solid #e5e7eb', borderRadius: 6, padding: 8, marginBottom: 6, fontSize: 12 }}>
                <strong>{e.event_type}</strong> <span className="chip" style={{ fontSize: 10 }}>{e.severity}</span>
                <span className="muted" style={{ marginLeft: 8 }}>{e.timestamp ? new Date(e.timestamp).toLocaleString() : ''}</span>
                <div className="muted" style={{ fontSize: 11 }}>{e.additional_data?.note || e.note || ''}</div>
              </div>
            ))}
            {!selectedRow.review && (
              <button className="btn" style={{ marginTop: 10, background: '#166534', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', fontSize: 13, cursor: 'pointer' }} disabled={reviewing === selectedRow.bus_id} onClick={() => markReviewed(selectedRow.bus_id)}>
                {reviewing === selectedRow.bus_id ? 'Reviewing…' : '✓ Mark reviewed — clear from list'}
              </button>
            )}
            <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>Use this report to prepare Route Map &amp; Road Intelligence for upcoming maintenance (depot planning, relief-bus cover).</div>
          </div>
        </div>
      )}

      {/* Scope / Methodology */}
      <div className="card">
        <div className="card-header"><h3 className="card-title">Methodology &amp; Data Honesty</h3></div>
        <div className="muted" style={{ fontSize: 13, lineHeight: 1.8 }}>
          <strong>Data Source:</strong> Values are <strong>ESTIMATED</strong> (heuristic rolling counters) unless a live bus node is streaming.
          <br /><br />
          <strong>Decision rule (review-to-clear):</strong> shortest remaining useful life among degraded components — ≤1 day → SEND TO MAINTENANCE, ≤3 days → PLAN MAINTENANCE, otherwise CAN CONTINUE. A flagged vehicle stays in the list until an operator marks it reviewed. No action is dispatched automatically.
          <br /><br />
          <strong>Components Tracked:</strong> Tyres (FL/FR/RL/RR wear), Vibration (RMS), Harsh Braking Rate, Energy/Battery Degradation.
          <br /><br />
          <strong>RUL (Remaining Useful Life):</strong> Linear trend projection from recent samples — <strong>not a trained ML model</strong>. 1 tick ≈ 2 simulated minutes (720 ticks/day).
        </div>
      </div>
    </>
  )
}
