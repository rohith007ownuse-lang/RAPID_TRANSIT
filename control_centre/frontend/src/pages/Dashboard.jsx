import { useMemo, useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatCard } from '../components/UI.jsx'
import AlertFeed from '../components/AlertFeed.jsx'
import FleetMap from '../components/FleetMap.jsx'
import SuggestSearch from '../components/SuggestSearch.jsx'
import { subscribe, answerCall, declineCall, hangup } from '../lib/callCenter.js'
import { useMode } from '../lib/modeContext.jsx'

function timeAgo(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

/* ─── MTC Routes & Stops — suggestion-style search (above the map) ─── */
function MtcSearchBar({ onSelectRoute, onSelectStop }) {
  const [routes, setRoutes] = useState([])
  const [stops, setStops] = useState([])
  const [gtfsSummary, setGtfsSummary] = useState(null)

  useEffect(() => {
    api.gtfsSummary().then(d => setGtfsSummary(d)).catch(() => {})
    api.gtfsRoutes().then(d => { if (d?.routes) setRoutes(d.routes) }).catch(() => {})
    api.gtfsStops().then(d => { if (d?.stops) setStops(d.stops.slice(0, 3000)) }).catch(() => {})
  }, [])

  const items = useMemo(() => {
    const routeItems = routes.map((r) => ({
      key: `route-${r.route_id}`,
      kind: 'route',
      label: String(r.route_short_name || r.route_id),
      sublabel: r.route_long_name || '',
      keywords: `${r.route_id || ''}`,
      raw: r,
    }))
    const stopItems = stops.map((s) => ({
      key: `stop-${s.stop_id}`,
      kind: 'stop',
      label: s.stop_name,
      sublabel: s.routes?.length > 0 ? `routes ${s.routes.slice(0, 4).join(', ')}` : (s.stop_id || ''),
      keywords: `${s.stop_id || ''}`,
      raw: s,
    }))
    return [...routeItems, ...stopItems]
  }, [routes, stops])

  return (
    <div className="card mb-16">
      <div className="card-header">
        <h3 className="card-title">🗺️ MTC Routes &amp; Stops</h3>
        {gtfsSummary?.loaded ? (
          <span className="badge badge-green" style={{ fontSize: 10 }}>
            {gtfsSummary.routes} routes · {gtfsSummary.stops} stops
          </span>
        ) : (
          <span className="badge badge-blue" style={{ fontSize: 10 }}>GTFS</span>
        )}
      </div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
        {gtfsSummary?.loaded
          ? `Chennai Metropolitan Transport Corporation · ${gtfsSummary.trips?.toLocaleString()} trips · type a route number or stop name — suggestions appear as you type`
          : 'Loading GTFS data…'}
      </div>
      <SuggestSearch
        items={items}
        placeholder="Search routes, stops… (e.g. 154, Koyambedu)"
        onSelect={(it) => {
          if (it.kind === 'route') onSelectRoute?.(String(it.raw.route_short_name || it.raw.route_id), it.raw)
          else onSelectStop?.(it.raw)
        }}
      />
    </div>
  )
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

/* ─── Level 1 · REQUIRES ATTENTION (focus on HIGH 60%+ / CRITICAL / OFFLINE) ─── */
const RANK = { CRITICAL: 0, HIGH: 1, WARNING: 2, OFFLINE: 3, INFO: 4 }
const GROUP_LABEL = {
  CRITICAL: 'Critical',
  HIGH: 'High',
  WARNING: 'Medium',
  OFFLINE: 'Offline',
  INFO: 'Info',
}
function AttentionPanel({ summary, nav }) {
  const [showHidden, setShowHidden] = useState(false)
  // Focus policy: only risk ≥ 60% (HIGH), CRITICAL and OFFLINE belong in the
  // attention panel. Lower-severity (medium/low risk) items stay out of the
  // operator's way — they are counted below and can be expanded on demand.
  const all = (summary?.attention || []).slice().sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9))
  const att = showHidden ? all : all.filter((a) => a.severity !== 'WARNING')
  const hiddenReal = all.filter((a) => a.severity === 'WARNING').length

  if (!summary) {
    return <div className="empty">Loading fleet summary…</div>
  }
  if (all.length === 0) {
    return <div className="empty" style={{ color: 'var(--green)' }}>✓ No attention items — fleet nominal.</div>
  }
  if (att.length === 0) {
    return (
      <>
        <div className="empty" style={{ color: 'var(--green)' }}>
          ✓ No HIGH (60%+) or CRITICAL risk buses — operator focus clear.
        </div>
        {hiddenReal > 0 && (
          <button className="btn btn-ghost" style={{ width: '100%', fontSize: 12 }} onClick={() => setShowHidden(true)}>
            show {hiddenReal} lower-risk bus(es) (&lt;60%)
          </button>
        )}
      </>
    )
  }
  const visible = showHidden ? att : att.slice(0, 8)
  const groups = []
  for (const a of visible) {
    let g = groups.find((x) => x.severity === a.severity)
    if (!g) {
      g = { severity: a.severity, items: [] }
      groups.push(g)
    }
    g.items.push(a)
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {groups.map((g) => (
        <div key={g.severity}>
          <div className="flex align-center gap-8" style={{ margin: '2px 0 6px' }}>
            <SevChip severity={g.severity} />
            <span
              style={{
                fontSize: 11,
                color: '#66727E',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                fontWeight: 600,
              }}
            >
              {GROUP_LABEL[g.severity] || g.severity}
            </span>
            <span className="muted" style={{ fontSize: 11 }}>· {g.items.length} bus(es)</span>
            {g.severity === 'CRITICAL' && <span className="badge badge-red">ACT NOW</span>}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {g.items.map((a) => (
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
                    {(a.reasons || []).map((r, i) => (
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
          </div>
        </div>
      ))}
      {att.length > 8 && (
        <button className="btn btn-ghost" style={{ width: '100%', fontSize: 12 }} onClick={() => setShowHidden(!showHidden)}>
          {showHidden ? 'Show less' : `+${att.length - 8} more`}
        </button>
      )}
      {!showHidden && hiddenReal > 0 && (
        <div className="muted" style={{ fontSize: 11, textAlign: 'center' }}>
          {hiddenReal} lower-risk bus(es) (&lt;60%) hidden — focus is on 60%+ risk.{' '}
          <button className="btn btn-ghost" style={{ fontSize: 11, padding: '1px 6px' }} onClick={() => setShowHidden(true)}>
            show all
          </button>
        </div>
      )}
    </div>
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

const Num = (v) => (v == null ? '—' : v)

/* Simulated fallbacks so the fleet KPIs are never empty (used only when the
   backend has not supplied a live/sim snapshot yet). */
const SIM_COUNTS = { total_buses: 100, active: 96, normal: 62, warning: 22, critical: 8, offline: 4 }
const SIM_RISK = { avg_score: 34, by_level: { HIGH: 22, CRITICAL: 8 } }

export default function Dashboard() {
  const nav = useNavigate()
  const { isLive, liveStatus } = useMode()
  const { data: summary, error } = usePoll(api.fleetSummary, 4000)
  const { data: busData } = usePoll(api.buses, 4000)
  const { data: evData } = usePoll(api.events, 4000)
  const { data: hotspotData } = usePoll(api.trafficHotspots, 6000)

  const buses = busData?.buses || []
  const hotspots = hotspotData?.hotspots || []
  const events = useMemo(() => (evData?.events || []).filter((e) => e.status === 'ACTIVE'), [evData])

  const crashes = events.filter((e) => e.event_type === 'CRASH')

  const [call, setCall] = useState(null)
  useEffect(() => subscribe(setCall), [])

  const busNames = useMemo(() => {
    const m = {}
    for (const b of buses) m[b.bus_id] = b.driver?.name
    return m
  }, [buses])

  const pin = call && call.status !== 'idle' ? call : null

  const fc = summary?.fleet_counts || SIM_COUNTS
  const risk = summary?.risk || SIM_RISK
  const dSafe = summary?.driver_safety
  const vHealth = summary?.vehicle_health
  const occ = summary?.occupancy
  const load = summary?.load
  const road = summary?.road
  const attentionCount = summary?.attention?.length ?? null

  // Map layer controls
  const [showMtcRoutes, setShowMtcRoutes] = useState(false)
  const [showMtcStops, setShowMtcStops] = useState(false)
  const [selectedRouteId, setSelectedRouteId] = useState(null)
  const [focusStop, setFocusStop] = useState(null)
  const [showHospitals, setShowHospitals] = useState(false)
  const [showFireStations, setShowFireStations] = useState(false)
  const [showPoliceStations, setShowPoliceStations] = useState(false)
  const [showTrafficPolice, setShowTrafficPolice] = useState(false)

  return (
    <>
      <PageHeader
        title={isLive ? "Rapid Transit · Live" : "Rapid Transit · Command Dashboard"}
        sub={isLive ? "" : "City Public Transportation Control Center"}
        right={<SimBadge />}
      />
      {error && <div className="card mb-16" style={{ color: 'var(--red)' }}>Cannot reach backend: {String(error)}</div>}

      {/* MTC ROUTES & STOPS SEARCH — above the map for instant access */}
      <MtcSearchBar
        onSelectRoute={(routeId) => {
          setSelectedRouteId(routeId)
          setShowMtcRoutes(true)
          setFocusStop(null)
        }}
        onSelectStop={(stop) => {
          setFocusStop(stop)
          setShowMtcStops(true)
        }}
      />

      {/* TOP · FLEET MAP + LIVE ALERTS */}
      <div className="grid grid-2 mb-16">
        <div className="card map-card">
          <div className="card-header">
            <h3 className="card-title">Fleet Map</h3>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              {crashes.length > 0 && (
                <span className="badge badge-red">✖ {crashes.length} crash</span>
              )}
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                <input type="checkbox" checked={showMtcRoutes} onChange={e => setShowMtcRoutes(e.target.checked)} />
                <span style={{ color: '#94a3b8' }}>●</span> Routes
              </label>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                <input type="checkbox" checked={showMtcStops} onChange={e => setShowMtcStops(e.target.checked)} />
                <span style={{ color: '#003366' }}>●</span> Stops
              </label>
              <span style={{ color: '#e2e8f0', fontSize: 10 }}>|</span>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                <input type="checkbox" checked={showHospitals} onChange={e => setShowHospitals(e.target.checked)} />
                🏥 Hospitals
              </label>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                <input type="checkbox" checked={showFireStations} onChange={e => setShowFireStations(e.target.checked)} />
                🚒 Fire
              </label>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                <input type="checkbox" checked={showPoliceStations} onChange={e => setShowPoliceStations(e.target.checked)} />
                🚓 Police
              </label>
              <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                <input type="checkbox" checked={showTrafficPolice} onChange={e => setShowTrafficPolice(e.target.checked)} />
                🚦 Traffic
              </label>
            </div>
          </div>
          <FleetMap
            buses={buses}
            onSelectBus={(id) => nav(`/fleet/${id}`)}
            showMtcRoutes={showMtcRoutes}
            showMtcStops={showMtcStops}
            selectedRouteId={selectedRouteId}
            onSelectRoute={setSelectedRouteId}
            showHospitals={showHospitals}
            showFireStations={showFireStations}
            showPoliceStations={showPoliceStations}
            showTrafficPolice={showTrafficPolice}
            hotspots={hotspots}
            focusStop={focusStop}
          />
          <div className="map-legend">
            <div><span className="badge badge-blue">🚌 bus</span></div>
            {hotspots.length > 0 && (
              <div><span className="badge badge-red">⚠ traffic red dot</span> {hotspots.length}</div>
            )}
            {selectedRouteId && (
              <div>
                <span className="badge badge-green" style={{ fontSize: 10 }}>
                  Route: {selectedRouteId}
                  <button
                    style={{ marginLeft: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: 10 }}
                    onClick={() => setSelectedRouteId(null)}
                  >
                    ✕
                  </button>
                </span>
              </div>
            )}
            {focusStop && (
              <div>
                <span className="badge badge-blue" style={{ fontSize: 10 }}>
                  Stop: {focusStop.stop_name}
                  <button
                    style={{ marginLeft: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: 10 }}
                    onClick={() => setFocusStop(null)}
                  >
                    ✕
                  </button>
                </span>
              </div>
            )}
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
          {/* LIVE ALERTS: criticals pinned until acknowledged; AI-suggested
              response on every alert. Clicking opens the vehicle live feed. */}
          <AlertFeed
            events={events}
            editable
            busNames={busNames}
            onItemClick={(e) => nav(`/fleet/${encodeURIComponent(e.bus_id)}`)}
          />
        </div>
      </div>

      {/* LEVEL 1 · REQUIRES ATTENTION (HIGH 60%+ / CRITICAL / OFFLINE focus) */}
      <div className="card mb-16" style={{ borderLeft: '4px solid var(--red)' }}>
        <div className="card-header">
          <h3 className="card-title">🚨 Requires Attention</h3>
          <span className={`badge ${attentionCount && attentionCount > 0 ? 'badge-red' : 'badge-green'}`}>
            {attentionCount == null ? '…' : `${attentionCount} item(s)`}
          </span>
        </div>
        <AttentionPanel summary={summary} nav={nav} />
      </div>

      {/* LEVEL 2 · FLEET OVERVIEW KPI */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">📊 Fleet Overview</h3>
          <span className="muted" style={{ fontSize: 11 }}>one glance · total → risk</span>
        </div>
        <div className="grid stats-grid" style={{ marginTop: 4 }}>
          <StatCard label="Total Buses" value={Num(fc.total_buses)} icon="🚌" tone="blue" />
          <StatCard label="Active" value={Num(fc.active)} icon="✔️" tone="green" />
          <StatCard label="Normal" value={Num(fc.normal)} icon="🟢" tone="green" hint="no active concerns" />
          <StatCard label="Warning" value={Num(fc.warning)} icon="🟠" tone="amber" hint="risk HIGH or subsystem warning" />
          <StatCard label="Critical" value={Num(fc.critical)} icon="🔴" tone="red" hint="needs immediate attention" />
          <StatCard label="Offline" value={Num(fc.offline)} icon="📴" tone="blue" hint="live telemetry stale" />
          <StatCard label="Avg Fleet Risk" value={Num(risk.avg_score)} icon="🎯" tone="red" hint={`high ${risk.by_level?.HIGH ?? 0} · critical ${risk.by_level?.CRITICAL ?? 0}`} />
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
            ['Source', isLive ? 'live telemetry' : 'estimated', 'var(--accent)'],
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
            ['Estimated/telemetry', occ ? Num(occ.simulated) : '…', 'var(--accent)'],
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
            <span className="badge badge-blue" style={{ fontSize: 10 }}>
              {isLive ? (summary.demand.source || 'LIVE') : 'ESTIMATED'}
            </span>
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
    </>
  )
}
