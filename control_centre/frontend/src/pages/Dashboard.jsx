import { useMemo, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatCard, StatusBadge } from '../components/UI.jsx'
import AlertFeed from '../components/AlertFeed.jsx'
import FleetMap from '../components/FleetMap.jsx'
import { subscribe, answerCall, declineCall, hangup } from '../lib/callCenter.js'
import { useMode } from '../lib/modeContext.jsx'

function timeAgo(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

/* ─── severity helpers (non-color-only: text is always shown) ─── */
const SEV_COLOR = {
  CRITICAL: 'var(--red)',
  HIGH: 'var(--amber)',
  WARNING: 'var(--amber)',
  OFFLINE: 'var(--accent)',
  INFO: 'var(--accent)',
}
function SevChip({ severity }) {
  const color = SEV_COLOR[severity] || 'var(--accent)'
  return (
    <span style={{ color, border: `1px solid ${color}`, borderRadius: 4, padding: '1px 6px', fontSize: 10, fontWeight: 700, fontFamily: 'monospace' }}>
      {severity}
    </span>
  )
}

/* ─── Level 1 · REQUIRES ATTENTION (prioritised, source-labelled) ─── */
function AttentionPanel({ summary, nav }) {
  const att = summary?.attention || []
  const [showAll, setShowAll] = useState(false)

  if (!summary) {
    return <div className="empty">Loading fleet summary…</div>
  }
  if (att.length === 0) {
    return <div className="empty" style={{ color: 'var(--green)' }}>✓ No attention items — fleet nominal.</div>
  }
  const list = showAll ? att : att.slice(0, 8)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {list.map((a) => (
        <button
          key={a.bus_id + a.severity}
          className="risk-row"
          onClick={() => nav(`/fleet/${encodeURIComponent(a.bus_id)}`)}
          title={`Open ${a.bus_id}`}
          style={{ textAlign: 'left', width: '100%' }}
        >
          <div style={{ minWidth: 84 }}>
            <SevChip severity={a.severity} />
          </div>
          <div className="risk-row-main">
            <div className="risk-row-title">
              <strong>{a.bus_id}</strong>
              <span className="muted" style={{ fontSize: 12 }}> · {a.route || '—'}</span>
              {a.offline && <span className="badge badge-blue" style={{ marginLeft: 6 }}>STALE</span>}
              {a.risk_score != null && (
                <span className="muted" style={{ fontSize: 12, marginLeft: 6 }}> · risk {a.risk_score}</span>
              )}
            </div>
            <div style={{ fontSize: 12, color: '#66727E', lineHeight: 1.5 }}>
              {a.reasons.map((r, i) => (
                <span key={i} style={{ display: 'block' }}>
                  <span className="muted" style={{ fontFamily: 'monospace', fontSize: 10, textTransform: 'uppercase' }}>{r.source}:</span>{' '}
                  {r.text}
                </span>
              ))}
            </div>
            {a.offline && a.staleness_seconds != null && (
              <div style={{ fontSize: 11, color: 'var(--accent)', marginTop: 2 }}>
                No telemetry for {a.staleness_seconds}s
              </div>
            )}
          </div>
          <div style={{ fontSize: 10, color: '#8A94A0', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
            {a.metrics?.speed_kmh != null ? `${a.metrics.speed_kmh} km/h` : '—'} ·{' '}
            {a.metrics?.load_pct != null ? `${a.metrics.load_pct}% load` : 'load —'}
          </div>
        </button>
      ))}
      {att.length > 8 && (
        <button className="btn btn-ghost" style={{ width: '100%', fontSize: 12 }} onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show less' : `+${att.length - 8} more`}
        </button>
      )}
    </div>
  )
}

/* ─── Level 1 · INCIDENT SUMMARY (overview + navigation, not a second system) ─── */
function IncidentSummary({ summary, nav }) {
  if (!summary) return <div className="empty">Loading incidents…</div>
  const inc = summary.incidents
  const sev = inc.severity || {}
  const rows = [
    ['Critical', sev.CRITICAL || 0, 'var(--red)'],
    ['High', sev.HIGH || 0, 'var(--amber)'],
    ['Medium', sev.MEDIUM || 0, 'var(--accent)'],
    ['Warning', sev.WARNING || 0, 'var(--accent)'],
    [`Open · ${inc.open}`, inc.open, 'var(--red)'],
    ['Acknowledged', inc.acknowledged, 'var(--amber)'],
    ['Resolved', inc.resolved, 'var(--green)'],
  ]
  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {rows.map(([label, value, color]) => (
          <div key={label} style={{ minWidth: 110 }}>
            <div className="muted" style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase' }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</div>
          </div>
        ))}
      </div>
      <button className="btn btn-ghost" style={{ fontSize: 12, marginTop: 8 }} onClick={() => nav('/incidents')}>
        View Incidents →
      </button>
    </>
  )
}

/* ─── Level 2 · distribution summary card (one subsystem per card) ─── */
function SummaryCard({ title, icon, rows }) {
  return (
    <div className="card">
      <div className="card-header">
        <h3 className="card-title">{icon} {title}</h3>
      </div>
      {rows.map(([label, value, color]) => (
        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
          <span className="muted" style={{ fontSize: 12 }}>{label}</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: color || '#17212B', fontFamily: 'monospace' }}>{value}</span>
        </div>
      ))}
    </div>
  )
}

/* ─── Quick navigation (reuses existing routes; privileged actions stay backend-guarded) ─── */
function QuickNav({ nav }) {
  const items = [
    ['🚨', 'Incidents', '/incidents'],
    ['🚌', 'Live Fleet', '/fleet'],
    ['👁️', 'Driver Safety', '/driver-safety'],
    ['🔧', 'Vehicle Health', '/health'],
    ['🛣️', 'Road Intelligence', '/roads'],
    ['⚖️', 'Load Management', '/load-management'],
  ]
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
      {items.map(([icon, label, to]) => (
        <button key={to} className="btn btn-sm" style={{ fontSize: 11 }} onClick={() => nav(to)}>
          {icon} {label}
        </button>
      ))}
    </div>
  )
}

const Num = ({ v }) => (v == null ? '—' : v)

export default function Dashboard() {
  const nav = useNavigate()
  const { isLive, liveStatus } = useMode()
  const { data: summary, error } = usePoll(api.fleetSummary, 4000)
  const { data: busData } = usePoll(api.buses, 4000)
  const { data: evData } = usePoll(api.events, 4000)
  const { data: actionsData } = usePoll(api.actions, 5000, [])

  const buses = busData?.buses || []
  const events = useMemo(() => (evData?.events || []).filter((e) => e.status === 'ACTIVE'), [evData])
  const actions = useMemo(() => (actionsData?.actions || []).filter((a) => !a.acknowledged), [actionsData])
  const criticalActions = useMemo(() => actions.filter((a) => a.severity === 'CRITICAL' || a.severity === 'WARNING'), [actions])
  const [showAllActions, setShowAllActions] = useState(false)

  const alerts = useMemo(() => events.filter((e) => e.severity === 'CRITICAL' || e.severity === 'WARNING').slice(0, 30), [events])
  const crashes = events.filter((e) => e.event_type === 'CRASH')
  const sirenBuses = useMemo(() => {
    const ids = new Set(events.filter((e) => e.event_type === 'EMERGENCY_SIREN').map((e) => e.bus_id))
    return buses.filter((b) => ids.has(b.bus_id))
  }, [events, buses])

  const [call, setCall] = useState(null)
  useEffect(() => subscribe(setCall), [])

  const busNames = useMemo(() => {
    const m = {}
    for (const b of buses) m[b.bus_id] = b.driver?.name
    return m
  }, [buses])

  const pin = call && call.status !== 'idle' ? call : null

  const fc = summary?.fleet_counts
  const risk = summary?.risk
  const dSafe = summary?.driver_safety
  const vHealth = summary?.vehicle_health
  const occ = summary?.occupancy
  const load = summary?.load
  const road = summary?.road
  const attentionCount = summary?.attention?.length ?? null

  return (
    <>
      <PageHeader
        title={isLive ? "Fleet Intelligence Dashboard — LIVE" : "Fleet Intelligence Dashboard"}
        sub={isLive
          ? "Live prototype data · REAL SENSOR VALUES · all telemetry stays labeled live"
          : "Command overview · city public-transport fleet · simulated telemetry"}
        right={
          <>
            <SimBadge />
            <span className={`badge ${summary?.live_prototype_connected ? 'badge-green' : 'badge-blue'}`}>
              {isLive
                ? (summary?.live_prototype_connected ? `LIVE · ${Num(summary.connected_nodes)} node(s)` : 'LIVE · NO NODES')
                : `SIMULATION`}
            </span>
          </>
        }
      />
      {error && <div className="card mb-16" style={{ color: 'var(--red)' }}>Cannot reach backend: {String(error)}</div>}

      <QuickNav nav={nav} />

      {/* Live prototype connection panel (existing behaviour) */}
      {isLive && (
        <div className={`card mb-16 ${liveStatus.connected ? 'card-live' : 'card-waiting'}`}>
          <div className="card-header">
            <h3 className="card-title">
              {liveStatus.connected ? '🟢 LIVE PROTOTYPE CONNECTED' : '🟡 WAITING FOR PROTOTYPE'}
            </h3>
            <span className={`badge ${liveStatus.connected ? 'badge-green' : 'badge-amber'}`}>
              {liveStatus.connected ? `${liveStatus.connected_count} node(s)` : 'NO NODES'}
            </span>
          </div>
          {liveStatus.connected && liveStatus.nodes.length > 0 && (
            <div className="flex wrap gap-8">
              {liveStatus.nodes.map((node) => (
                <div key={node.bus_id} className="live-node-card">
                  <strong>{node.bus_id}</strong>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {node.connected ? '● ONLINE' : '○ OFFLINE'} ·
                    GPS: {node.gps_available ? 'OK' : 'WAITING'} ·
                    Last update: {node.last_seen_ago}s ago
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* LEVEL 1 · REQUIRES ATTENTION */}
      <div className="card mb-16" style={{ borderLeft: '4px solid var(--red)' }}>
        <div className="card-header">
          <h3 className="card-title">🚨 Requires Attention</h3>
          <span className={`badge ${attentionCount && attentionCount > 0 ? 'badge-red' : 'badge-green'}`}>
            {attentionCount == null ? '…' : `${attentionCount} item(s)`}
          </span>
        </div>
        <AttentionPanel summary={summary} nav={nav} />
      </div>

      {/* LEVEL 1 · INCIDENTS + fleet KPI */}
      <div className="grid grid-2 mb-16">
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">🚨 Incidents</h3>
            <span className="muted" style={{ fontSize: 11 }}>active workflow → Incidents page</span>
          </div>
          <IncidentSummary summary={summary} nav={nav} />
        </div>

        {/* LEVEL 2 · top-level fleet KPIs (from live fleet data, never hardcoded) */}
        <div className="grid stats-grid">
          <StatCard label="Total Buses" value={fc ? Num(fc.total_buses) : '…'} icon="🚌" tone="blue" />
          <StatCard label="Active" value={fc ? Num(fc.active) : '…'} icon="✔️" tone="green" />
          <StatCard label="Normal" value={fc ? Num(fc.normal) : '…'} icon="🟢" tone="green" hint="no active concerns" />
          <StatCard label="Warning" value={fc ? Num(fc.warning) : '…'} icon="🟠" tone="amber" hint="risk HIGH or subsystem warning" />
          <StatCard label="Critical" value={fc ? Num(fc.critical) : '…'} icon="🔴" tone="red" hint="needs immediate attention" />
          <StatCard label="Offline" value={fc ? Num(fc.offline) : '…'} icon="📴" tone="blue" hint="live telemetry stale" />
          <StatCard label="Avg Fleet Risk" value={risk ? Num(risk.avg_score) : '…'} icon="🎯" tone="red" hint={risk ? `high ${risk.by_level?.HIGH || 0} · critical ${risk.by_level?.CRITICAL || 0}` : ''} />
        </div>
      </div>

      {/* LEVEL 3 · subsystem summaries */}
      <div className="grid grid-4 mb-16">
        <SummaryCard
          title="Driver Safety"
          icon="👁️"
          rows={[
            ['Normal', dSafe ? Num(dSafe.normal) : '…', 'var(--green)'],
            ['Attention', dSafe ? Num(dSafe.attention) : '…', 'var(--amber)'],
            ['Drowsy', dSafe ? Num(dSafe.drowsy) : '…', 'var(--red)'],
            ['Unavailable', dSafe ? Num(dSafe.unavailable) : '…', 'var(--accent)'],
            ['Source', isLive ? 'live telemetry' : 'simulated', 'var(--accent)'],
          ]}
        />
        <SummaryCard
          title="Vehicle Health"
          icon="🔧"
          rows={[
            ['Healthy', vHealth ? Num(vHealth.NORMAL) : '…', 'var(--green)'],
            ['Warning', vHealth ? Num(vHealth.WARNING) : '…', 'var(--amber)'],
            ['Inspection', vHealth ? Num(vHealth['INSPECTION REQUIRED']) : '…', 'var(--red)'],
            ['Unknown', vHealth ? Num(vHealth.unknown) : '…', 'var(--accent)'],
          ]}
        />
        <SummaryCard
          title="Occupancy"
          icon="🧑‍🤝‍🧑"
          rows={[
            ['Normal', occ ? Num(occ.normal) : '…', 'var(--green)'],
            ['Moderate', occ ? Num(occ.moderate) : '…', 'var(--amber)'],
            ['High', occ ? Num(occ.high) : '…', 'var(--amber)'],
            ['Critical', occ ? Num(occ.critical) : '…', 'var(--red)'],
            ['Camera-based', occ ? Num(occ.camera_based) : '…', 'var(--accent)'],
            ['Simulated/telemetry', occ ? Num(occ.simulated) : '…', 'var(--accent)'],
            ['Unavailable', occ ? Num(occ.unavailable) : '…', 'var(--accent)'],
          ]}
        />
        <SummaryCard
          title="Load"
          icon="⚖️"
          rows={[
            ['Normal', load ? Num(load.normal) : '…', 'var(--green)'],
            ['High Load', load ? Num(load.high) : '…', 'var(--amber)'],
            ['Critical Overload', load ? Num(load.critical) : '…', 'var(--red)'],
          ]}
        />
      </div>

      {/* LEVEL 3 · road risk summary */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">🛣️ Road Intelligence</h3>
          <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => nav('/roads')}>View Road Intelligence →</button>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          {[
            ['High-risk routes', road ? Num(road.high_risk_routes) : '…'],
            ['Active road hazards', road ? Num(road.active_defects) : '…'],
            ['Affected buses', road ? Num(road.affected_buses) : '…'],
            ['Risk zones', road ? Num(road.zones) : '…'],
          ].map(([label, value]) => (
            <div key={label}>
              <div className="muted" style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase' }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#17212B', fontFamily: 'monospace' }}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* LEVEL 3 · ETA / delay summary (Phase 13) */}
      {summary?.eta && (
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">⏱️ ETA & Delay Intelligence</h3>
            <span className="badge badge-blue" style={{ fontSize: 10 }}>{summary.eta.source || 'HEURISTIC'}</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
            {[
              ['On Time', `${summary.eta.on_time_percentage ?? 0}%`, summary.eta.on_time_percentage >= 70 ? 'var(--green)' : 'var(--amber)'],
              ['Delayed', `${summary.eta.delayed_percentage ?? 0}%`, summary.eta.delayed_percentage > 30 ? 'var(--red)' : 'var(--amber)'],
              ['Severe', Num(summary.eta.severe_delay_buses?.length ?? 0), 'var(--red)'],
            ].map(([label, value, color]) => (
              <div key={label}>
                <div className="muted" style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase' }}>{label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: color || '#17212B', fontFamily: 'monospace' }}>{value}</div>
              </div>
            ))}
          </div>
          {summary.eta.delay_distribution && (
            <div className="muted mt-8" style={{ fontSize: 11 }}>
              {Object.entries(summary.eta.delay_distribution).filter(([,v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(' · ')}
            </div>
          )}
        </div>
      )}

      {/* LEVEL 3 · demand / capacity intelligence (Phase 14) */}
      {summary?.demand && (
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">🚌 Passenger Demand & Capacity</h3>
            <span className="badge badge-blue" style={{ fontSize: 10 }}>{summary.demand.source || 'HEURISTIC'}</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
            {[
              ['Over Capacity', Num(summary.demand.overloaded_buses?.length ?? 0), 'var(--red)'],
              ['Near Capacity', Num(summary.demand.near_capacity_buses?.length ?? 0), 'var(--amber)'],
              ['High Utilization', `${summary.demand.high_utilization_percentage ?? 0}%`, summary.demand.high_utilization_percentage > 30 ? 'var(--amber)' : 'var(--green)'],
              ['Unknown Occupancy', Num(summary.demand.unknown_occupancy_buses?.length ?? 0), '#6b7280'],
            ].map(([label, value, color]) => (
              <div key={label}>
                <div className="muted" style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase' }}>{label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: color || '#17212B', fontFamily: 'monospace' }}>{value}</div>
              </div>
            ))}
          </div>
          {summary.demand.load_distribution && (
            <div className="muted mt-8" style={{ fontSize: 11 }}>
              Load: {Object.entries(summary.demand.load_distribution).filter(([,v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(' · ')}
            </div>
          )}
          {summary.demand.crowding_distribution && (
            <div className="muted mt-4" style={{ fontSize: 11 }}>
              Crowding: {Object.entries(summary.demand.crowding_distribution).filter(([,v]) => v > 0).map(([k, v]) => `${k}: ${v}`).join(' · ')}
            </div>
          )}
        </div>
      )}

      {/* LEVEL 3 · map + real-time event feeds */}
      <div className="grid grid-2 mb-16">
        <div className="card map-card">
          <div className="card-header">
            <h3 className="card-title">Fleet Map</h3>
            {crashes.length > 0 && (
              <span className="badge badge-red">✖ {crashes.length} crash event(s)</span>
            )}
          </div>
          <FleetMap buses={buses} onSelectBus={(id) => nav(`/fleet/${id}`)} />
          <div className="map-legend">
            <div><span className="badge badge-blue">🚌 bus</span></div>
          </div>
        </div>
        <div className="flex col gap-8">
          {pin && (
            <div
              className={`call-pin call-pin-${pin.status}`}
              onClick={() => pin.busId && nav(`/fleet/${encodeURIComponent(pin.busId)}`)}
              title={`Open ${pin.busId} to call the driver directly`}
            >
              <div className="call-pin-top">
                <span className="call-pin-tag">
                  <span className="cc-pulse" /> {pin.status === 'ringing' ? 'INCOMING DRIVER CALL' : 'LIVE DRIVER CALL'}
                </span>
                <span className="muted" style={{ fontSize: 11 }}>pinned · top priority</span>
              </div>
              <div className="call-pin-info">
                <span className="call-pin-icon">{pin.status === 'ringing' ? '📲' : '☎️'}</span>
                <div>
                  <div className="call-pin-line">
                    <strong>{pin.busId}</strong>
                    {busNames[pin.busId] && <em style={{ fontSize: 12 }}> · driver {busNames[pin.busId]}</em>}
                  </div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {pin.status === 'ringing'
                      ? 'driver pressed the in-bus CALL button' + (pin.startedAt ? ' · ' + new Date(pin.startedAt).toLocaleTimeString() : '')
                      : `operator ↔ driver · ${pin.direction === 'in' ? 'driver → operator' : 'operator → driver'}`}
                    {pin.startedAt && <span> · {timeAgo(pin.startedAt)}</span>}
                  </div>
                </div>
              </div>
              <div className="call-pin-actions" onClick={(ev) => ev.stopPropagation()}>
                {pin.status === 'ringing' ? (
                  <>
                    <button className="btn call-answer" onClick={answerCall}>✓ Accept</button>
                    <button className="btn call-decline" onClick={declineCall}>✕ Decline</button>
                  </>
                ) : (
                  <button className="btn call-hangup" onClick={hangup}>⏹ End call</button>
                )}
                <button className="btn call-open" onClick={() => pin.busId && nav(`/fleet/${encodeURIComponent(pin.busId)}`)}>Open bus</button>
              </div>
            </div>
          )}
          <AlertFeed
            events={alerts}
            editable
            busNames={busNames}
            onItemClick={(e) => nav(`/fleet/${encodeURIComponent(e.bus_id)}`)}
          />
        </div>
      </div>

      {sirenBuses.length > 0 && (
        <div className="card mb-16" style={{ borderLeft: '4px solid var(--indigo)' }}>
          <div className="card-header">
            <h3 className="card-title">🚑 Emergency Siren Detected</h3>
          </div>
          <div className="flex wrap gap-8">
            {sirenBuses.map((b) => (
              <span key={b.bus_id} className="chip">
                <strong>{b.bus_id}</strong> · {b.route} · at {b.speed_kmh.toFixed(0)} km/h
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Critical actions (auth-guarded by backend; roles preserved) */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">🚨 Recommended Actions</h3>
          <div className="flex align-center gap-8">
            {criticalActions.length > 0 && <span className="badge badge-red">{criticalActions.length}</span>}
            <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => api.evaluateActions()}>Refresh</button>
          </div>
        </div>
        {criticalActions.length === 0 ? (
          <div className="empty" style={{ padding: '12px 16px', fontSize: 13 }}>No critical actions.</div>
        ) : (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(showAllActions ? criticalActions : criticalActions.slice(0, 3)).map((a) => (
                <div
                  key={a.action_id}
                  onClick={() => nav(`/fleet/${encodeURIComponent(a.bus_id)}`)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)',
                    background: 'var(--bg-card)', cursor: 'pointer', fontSize: 13,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: 'var(--red)', fontWeight: 700 }}>{a.bus_id}</span>
                    <span className="muted" style={{ fontSize: 12 }}>{a.type}</span>
                  </div>
                  <button
                    className="btn btn-sm btn-ghost"
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={(e) => { e.stopPropagation(); api.ackAction(a.action_id); }}
                  >
                    Acknowledge
                  </button>
                </div>
              ))}
            </div>
            {criticalActions.length > 3 && (
              <button className="btn btn-ghost" style={{ width: '100%', fontSize: 12, marginTop: 4 }} onClick={() => setShowAllActions(!showAllActions)}>
                {showAllActions ? 'Show less' : `+${criticalActions.length - 3} more`}
              </button>
            )}
          </>
        )}
      </div>
    </>
  )
}