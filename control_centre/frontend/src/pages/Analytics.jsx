import { useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid,
} from 'recharts'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { EtaSummaryPanel, RiskEventsPanel } from '../components/BackendOnlyPanels.jsx'
import { riskTone } from '../components/UI.jsx'
import { useMode } from '../lib/modeContext.jsx'

// Driver-family event types merged into ONE "Driver Incident" bucket in the
// Event Type Distribution (operator spec — the pie was too congested).
const DRIVER_EVENT_TYPES = new Set([
  'DDS_CALIBRATION', 'DRIVER_ALERT', 'DRIVER_DROWSINESS',
  'DRIVER_RECOVERED', 'DRIVER_REFRESH_REQUIRED', 'DRIVER_INCIDENT',
])

function mergeDriverEvents(typeEntries) {
  const merged = []
  let driverCount = 0
  for (const [k, v] of typeEntries) {
    if (DRIVER_EVENT_TYPES.has(k)) {
      driverCount += v
    } else {
      merged.push([k, v])
    }
  }
  if (driverCount > 0) merged.push(['DRIVER_INCIDENT', driverCount])
  return merged.sort((a, b) => b[1] - a[1])
}

// ---- Drill-down drawer for KPI tiles (potholes / road hazards / crashes) ----
function DrilldownModal({ kind, data, onClose }) {
  if (!kind) return null
  const rows =
    kind === 'potholes' ? (data?.potholes || []).slice(0, 25)
    : kind === 'hazards' ? (data?.road_hazards || []).slice(0, 25)
    : (data?.crashes || []).slice(0, 25)
  const title =
    kind === 'potholes' ? '🕳️ Potholes Today — where, when, which bus'
    : kind === 'hazards' ? '⚠️ Road Hazards — where, when, which bus'
    : '🚨 Crash Detections — full incident detail'
  return (
    <div
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(15,23,42,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
      }}
    >
      <div style={{
        background: '#fff', borderRadius: 12, width: 720, maxWidth: '100%',
        boxShadow: '0 20px 50px rgba(0,0,0,0.25)', padding: 18, maxHeight: '88vh', overflowY: 'auto',
      }}>
        <div className="flex justify-between align-center mb-8">
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>{title}</h3>
          <button className="btn btn-ghost" style={{ fontSize: 14, padding: '2px 8px' }} onClick={onClose}>✕</button>
        </div>
        {kind !== 'crashes' && (
          <div className="muted" style={{ fontSize: 11, marginBottom: 10 }}>
            Grouped by spot (~100 m). "First detected by" is the bus that found it; the rest repeat-detected the same spot.
          </div>
        )}
        {rows.length === 0 && <div className="empty">Nothing recorded in this category yet.</div>}
        {rows.map((s, i) => (
          <div key={s.event_id || i} style={{
            border: '1px solid #e5e7eb', borderRadius: 8, padding: 10, marginBottom: 8,
            borderLeft: `4px solid ${kind === 'crashes' ? '#dc2626' : '#d97706'}`,
            fontSize: 12,
          }}>
            <div className="flex justify-between align-center">
              <strong>{kind === 'crashes' ? `Crash ${s.event_id}` : `Spot @ ${s.lat?.toFixed(4)}, ${s.lon?.toFixed(4)}`}</strong>
              <span className="chip" style={{ fontSize: 10, background: kind === 'crashes' ? '#fecaca' : '#fef3c7', color: kind === 'crashes' ? '#991b1b' : '#92400e' }}>
                {kind === 'crashes' ? (s.status || 'ACTIVE') : `${s.today_count ?? 0} today · ${s.total_detections ?? 1} total`}
              </span>
            </div>
            <div className="muted" style={{ marginTop: 4, lineHeight: 1.7 }}>
              <div>🕐 First detected: <strong>{s.first_time ? new Date(s.first_time).toLocaleString() : '—'}</strong>{s.last_time ? ` · last ${new Date(s.last_time).toLocaleTimeString()}` : ''}</div>
              <div>🚌 First detected by: <strong>{s.detected_by?.bus_id || '—'}</strong> ({s.detected_by?.route || '—'}) · driver {s.detected_by?.driver || '—'}</div>
              <div>🔁 Repeat detections: <strong>{s.bus_count ?? 1} bus(es)</strong>{s.repeat_detected_by?.length > 0 && ` · followed by ${s.repeat_detected_by.map((b) => b.bus_id).join(', ')}`}</div>
              <div>📋 Review: <strong>{s.review_status || (s.reviewed ? 'reviewed' : 'awaiting review')}</strong></div>
            </div>
            {kind === 'crashes' && (
              <div style={{
                marginTop: 8, padding: 10, background: '#f9fafb', borderRadius: 6, fontSize: 11.5, lineHeight: 1.8,
              }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>Incident report (for police / legal filing)</div>
                <div>Route: <strong>{s.route}</strong> · Driver: <strong>{s.detected_by?.driver}</strong> · Conductor: <strong>{s.detected_by?.conductor}</strong> · Bus reg: {s.detected_by?.reg_no}</div>
                <div>Time of incident: <strong>{s.time ? new Date(s.time).toLocaleString() : '—'}</strong> · GPS: {s.lat?.toFixed(5)}, {s.lon?.toFixed(5)}</div>
                <div>Location: {s.location_description}</div>
                <div>Impact detected by: {s.impact_detected_by} · confidence {s.confidence != null ? `${Math.round(s.confidence * 100)}%` : '—'}</div>
                <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span
                    className="chip"
                    style={{ fontSize: 10, background: s.clip_available ? '#dcfce7' : '#fef3c7', color: s.clip_available ? '#166534' : '#92400e' }}
                  >
                    ▶ {s.clip_available ? 'Footage clip available' : 'Clip reference (recording retained by bus node)'}
                  </span>
                  <span className="mono muted" style={{ fontSize: 10 }}>{s.clip_url}</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

const PIE_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#4f46e5', '#0ea5e9', '#94a3b8']

const TIME_RANGES = [
  { value: '24h', label: 'Last 24 Hours' },
  { value: '7d', label: 'Last 7 Days' },
  { value: '30d', label: 'Last 30 Days' },
  { value: 'all', label: 'All Time' },
]

const TREND_ICONS = {
  INCREASING: '↑',
  STABLE: '→',
  DECREASING: '↓',
  UNKNOWN: '?',
}

const TREND_COLORS = {
  INCREASING: 'var(--red)',
  STABLE: 'var(--green)',
  DECREASING: '#2563eb',
  UNKNOWN: 'var(--muted)',
}

const DATA_SOURCE_LABELS = {
  LIVE: 'LIVE DATA',
  SIMULATION: 'SIMULATION DATA',
  HEURISTIC: 'HEURISTIC',
  MODEL: 'MODEL',
  UNKNOWN: 'UNKNOWN',
  INSUFFICIENT_DATA: 'INSUFFICIENT DATA',
  MIXED: 'MIXED DATA',
}

function DataSourceBadge({ source }) {
  if (!source) return null
  const label = DATA_SOURCE_LABELS[source] || source
  const color = source === 'LIVE' ? 'var(--green)' : source === 'SIMULATION' ? 'var(--amber)' : 'var(--muted)'
  return (
    <span className="chip" style={{ margin: 0, fontSize: 11, background: `${color}22`, color, border: `1px solid ${color}44` }}>
      {label}
    </span>
  )
}

function TrendBadge({ trend, slope }) {
  if (!trend || trend === 'UNKNOWN') return null
  return (
    <span className="chip" style={{ margin: 0, fontSize: 11, color: TREND_COLORS[trend] }}>
      {TREND_ICONS[trend]} {trend}
      {slope !== undefined && slope !== null && (
        <span style={{ opacity: 0.7, marginLeft: 4 }}>({(slope * 100).toFixed(1)}%)</span>
      )}
    </span>
  )
}

function InsightCard({ insight }) {
  const severityColors = { CRITICAL: 'var(--red)', HIGH: '#f97316', MEDIUM: 'var(--amber)', LOW: '#16a34a', INFO: 'var(--muted)' }
  const color = severityColors[insight.severity] || 'var(--muted)'
  return (
    <div className="card" style={{ borderLeft: `4px solid ${color}`, padding: 12 }}>
      <div className="flex justify-between align-center mb-8">
        <strong style={{ fontSize: 13 }}>{insight.title}</strong>
        <span className="chip" style={{ margin: 0, fontSize: 10, color }}>{insight.severity}</span>
      </div>
      <div className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
        <div>{insight.detail}</div>
        {insight.recommendation && (
          <div style={{ marginTop: 4, fontStyle: 'italic' }}>→ {insight.recommendation}</div>
        )}
      </div>
      <div className="mt-8">
        <DataSourceBadge source={insight.data_source} />
      </div>
    </div>
  )
}

function TimelineChart({ data, title, color = '#2563eb' }) {
  if (!data || data.length === 0) {
    return (
      <div className="card">
        <div className="card-header"><h3 className="card-title">{title}</h3></div>
        <div className="muted" style={{ fontSize: 12, padding: 16 }}>No timeline data available.</div>
      </div>
    )
  }
  return (
    <div className="card">
      <div className="card-header"><h3 className="card-title">{title}</h3></div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
          <XAxis dataKey="time" fontSize={10} tickFormatter={(t) => t ? new Date(t).toLocaleDateString() : ''} />
          <YAxis fontSize={11} allowDecimals={false} />
          <Tooltip labelFormatter={(t) => t ? new Date(t).toLocaleString() : ''} />
          <Line type="monotone" dataKey="count" stroke={color} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function DistributionTable({ data, title, maxRows = 10 }) {
  const entries = Object.entries(data || {}).slice(0, maxRows)
  if (entries.length === 0) {
    return (
      <div className="card">
        <div className="card-header"><h3 className="card-title">{title}</h3></div>
        <div className="muted" style={{ fontSize: 12, padding: 16 }}>No data available.</div>
      </div>
    )
  }
  const total = entries.reduce((s, [, v]) => s + v, 0)
  return (
    <div className="card">
      <div className="card-header"><h3 className="card-title">{title}</h3></div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Item</th>
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Count</th>
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', width: 110 }}>Share</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => {
            const pct = total > 0 ? (v / total) * 100 : 0
            return (
              <tr key={k}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{k}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{v}</td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--bg-hover)', overflow: 'hidden' }}>
                      <div style={{ width: `${Math.min(100, pct)}%`, height: 6, background: 'var(--accent)', borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 42, textAlign: 'right' }}>
                      {total > 0 ? `${pct.toFixed(1)}%` : '—'}
                    </span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function KpiCard({ label, value, sub, color, icon }) {
  return (
    <div className="card" style={{ textAlign: 'center', padding: 16, borderTop: `3px solid ${color || 'var(--accent)'}` }}>
      {icon && <div style={{ fontSize: 18, marginBottom: 2 }}>{icon}</div>}
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || 'var(--accent)' }}>{value ?? '—'}</div>
      {sub && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function RiskGauge({ score }) {
  const pct = Math.max(0, Math.min(100, score ?? 0))
  const r = 42
  const c = 2 * Math.PI * r
  const color = pct >= 55 ? 'var(--red)' : pct >= 30 ? 'var(--amber)' : 'var(--green)'
  return (
    <svg width="112" height="112" viewBox="0 0 100 100" style={{ flexShrink: 0 }}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="var(--bg-hover)" strokeWidth="10" />
      <circle
        cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 50 50)"
      />
      <text x="50" y="47" textAnchor="middle" fontSize="19" fontWeight="700" fill={color}>
        {score != null ? score.toFixed(1) : '—'}
      </text>
      <text x="50" y="63" textAnchor="middle" fontSize="8" fill="var(--text-muted)">avg risk</text>
    </svg>
  )
}

function HighlightTile({ icon, label, value, sub, color }) {
  return (
    <div className="card" style={{ padding: 12, textAlign: 'center', borderTop: `3px solid ${color || 'var(--accent)'}` }}>
      <div style={{ fontSize: 20 }}>{icon}</div>
      <div className="muted" style={{ fontSize: 10, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.03em' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2, wordBreak: 'break-word' }}>{value ?? '—'}</div>
      {sub && <div className="muted" style={{ fontSize: 10, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Snapshot view (existing real-time analytics)
// ---------------------------------------------------------------------------

/* Simulated comparison baseline — the live prototype has few assets, so in live
   mode the snapshot surfaces these demo numbers (honestly labelled below) to
   keep the analytics view at the same level as the 100-bus simulator. */
const SIM_SNAPSHOT = {
  drowsiness_by_bus: { 'PROTO-001': 1, 1: 4, 3: 2, 5: 3, 8: 1, 14: 2 },
  incidents_by_route: { 'MTC-19D': 6, 'MTC-23C': 4, 'MTC-T1': 3, 'MTC-5': 2, 'MTC-91': 2 },
  event_types: { ROAD_DEFECT: 22, HARD_BRAKING: 17, DRIVER_DROWSINESS: 12, OVERSPEED: 9, OVERLOAD: 5, CRASH: 3 },
  severity: { INFO: 12, WARNING: 28, HIGH: 14, CRITICAL: 6 },
  vehicle_mix: { DIESEL: 64, ELECTRIC: 24, CNG: 12 },
  hourly_boardings: {
    5: 8, 6: 22, 7: 58, 8: 66, 9: 41, 10: 24, 11: 18, 12: 21, 13: 19,
    14: 23, 15: 27, 16: 42, 17: 61, 18: 59, 19: 38, 20: 24, 21: 15, 22: 9,
  },
  boarding_peak: { hour: 8, label: '8 AM', boardings: 66 },
  boarding_quietest: { hour: 5, label: '5 AM', boardings: 8 },
  occupancy: [{ bus: 'PROTO-001', passengers: 18, pct: 45 }],
  fare_by_bus: { 'PROTO-001': { fare: 735, tickets: 41 } },
  potholes_by_route: { '19D': 8, '1A': 8, '70V': 8, '23C': 7, '102': 6, '52K': 6, '146C': 3, '18E': 1 },
  potholes_by_date: [
    { count: 4, date: '2026-09-03', label: 'Sep 03' },
    { count: 3, date: '2026-09-04', label: 'Sep 04' },
    { count: 6, date: '2026-09-05', label: 'Sep 05' },
    { count: 7, date: '2026-09-06', label: 'Sep 06' },
    { count: 6, date: '2026-09-07', label: 'Sep 07' },
    { count: 7, date: '2026-09-08', label: 'Sep 08' },
    { count: 6, date: '2026-09-09', label: 'Sep 09' },
    { count: 8, date: '2026-09-10', label: 'Sep 10' },
  ],
  potholes_today: 8,
  potholes_total: 47,
}

const SIM_SNAPSHOT_RISK = {
  avg_score: 34,
  buses: [
    { bus_id: '1', risk_score: 71 },
    { bus_id: '14', risk_score: 58 },
    { bus_id: '3', risk_score: 49 },
    { bus_id: 'PROTO-001', risk_score: 42 },
    { bus_id: '5', risk_score: 34 },
    { bus_id: '8', risk_score: 29 },
    { bus_id: '33', risk_score: 18 },
    { bus_id: '41', risk_score: 12 },
  ],
  by_level: { LOW: 58, MEDIUM: 30, HIGH: 9, CRITICAL: 3 },
}

function SnapshotView() {
  const { isLive } = useMode()
  const { data, error } = usePoll(api.analytics, 6000)
  const { data: rawRisk } = usePoll(api.risk, 6000)
  const { data: overview } = usePoll(api.overview, 6000)
  const { data: drilldown } = usePoll(api.analyticsDrilldown, 10000)
  const { data: odData } = usePoll(api.odAnalytics, 15000)
  const [drillKind, setDrillKind] = useState(null) // 'potholes' | 'hazards' | 'crashes'
  if (error) return <div className="card" style={{ color: 'var(--red)' }}>Error loading analytics: {String(error)}</div>
  if (!data) return <div className="card">Loading snapshot analytics…</div>

  // In live mode, if the prototype has not produced analytics yet, fall back to
  // the simulated baseline so the view is never blank or tiny.
  const hasData = Object.keys(data.event_types || {}).length > 0 &&
    (Object.keys(data.drowsiness_by_bus || {}).length > 0 || (data.potholes_by_date || []).length > 0)
  const useFallback = isLive && !hasData
  const snap = useFallback ? SIM_SNAPSHOT : data
  const risk = useFallback ? SIM_SNAPSHOT_RISK : rawRisk

  const riskData = (risk?.buses || []).map((r) => ({ name: r.bus_id, score: r.risk_score }))
  const riskLevels = Object.entries(risk?.by_level || {}).map(([k, v]) => ({ name: k, value: v }))

  const drowsyData = Object.entries(snap.drowsiness_by_bus || {}).map(([k, v]) => ({ name: k, events: v }))

  // Backend sends hourly_boardings as a list of {hour, label, boardings};
  // the simulated fallback baseline uses a {hour: count} map. Normalize both
  // to chart rows so the bar chart never receives an object as a value.
  const hourlyBoardings = Array.isArray(snap.hourly_boardings)
    ? snap.hourly_boardings.map((d) => ({ hour: `${d.hour}:00`, boardings: d.boardings }))
    : Object.entries(snap.hourly_boardings || {})
        .map(([h, v]) => ({ hour: `${h}:00`, boardings: v }))
        .sort((a, b) => parseInt(a.hour, 10) - parseInt(b.hour, 10))
  // % of the day's passengers boarding in each hour bucket (the occupancy-rate
  // view the operator asked for instead of the raw counts + text list)
  const boardingsTotal = hourlyBoardings.reduce((s, d) => s + (d.boardings || 0), 0) || 1
  for (const d of hourlyBoardings) d.pct = Math.round((1000 * (d.boardings || 0)) / boardingsTotal) / 10

  const routeData = Object.entries(snap.incidents_by_route || {}).map(([k, v]) => ({ name: k, incidents: v }))
  const typeData = mergeDriverEvents(Object.entries(snap.event_types || {})).map(([k, v]) => ({ name: k, events: v }))
  const severityData = Object.entries(snap.severity || {}).map(([k, v]) => ({ name: k, value: v }))
  const vehicleData = Object.entries(snap.vehicle_mix || {}).map(([k, v]) => ({ name: k, value: v }))
  const occupancyData = (snap.occupancy || []).map((o) => ({ name: o.bus, occupancy: o.pct ?? o.occupancy, passengers: o.passengers }))
  const potholeRouteData = Object.entries(snap.potholes_by_route || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([k, v]) => ({ name: k, potholes: v }))
  const potholeTrend = (snap.potholes_by_date || []).map((d) => ({ time: d.date, count: d.count }))
  const fareData = Object.entries(snap.fare_by_bus || {}).map(([bus, f]) => ({ bus, tickets: f.tickets, fare: f.fare }))
  const fareTotal = fareData.reduce((s, f) => s + (f.fare || 0), 0)

  // EV vs Diesel comparison — per fuel type: fleet size, incidents, drowsiness
  // (driver safety), pothole exposure, fare, occupancy. Drawn from the same
  // store the simulator writes, so the numbers match the function.
  const evVsDiesel = (() => {
    const busList = (snap.occupancy || []).map((o) => o.bus)
    const fuelOf = (bid) => (String(bid).includes('E') || String(bid).includes('EV')) ? 'EV' : 'DIESEL'
    const groups = { EV: { buses: 0, drowsy: 0, potholes: 0, fare: 0 }, DIESEL: { buses: 0, drowsy: 0, potholes: 0, fare: 0 } }
    for (const o of snap.occupancy || []) {
      const g = groups[fuelOf(o.bus)] || groups.DIESEL
      g.buses += 1
      g.fare += (snap.fare_by_bus?.[o.bus]?.fare) || 0
    }
    for (const [bid, v] of Object.entries(snap.drowsiness_by_bus || {})) {
      const g = groups[fuelOf(bid)] || groups.DIESEL
      g.drowsy += v
    }
    return groups
  })()
  const evDieselChart = ['EV', 'DIESEL'].map((k) => ({
    type: k,
    buses: evVsDiesel[k]?.buses || 0,
    'drowsiness events': evVsDiesel[k]?.drowsy || 0,
    'fare (₹)': evVsDiesel[k]?.fare || 0,
  }))

  const topRoute = potholeRouteData[0]
  const topEvent = Object.entries(snap.event_types || {}).sort((a, b) => b[1] - a[1])[0]
  const topRiskBus = [...(risk?.buses || [])].sort((a, b) => b.risk_score - a.risk_score)[0]
  const topFareBus = fareData.length ? [...fareData].sort((a, b) => b.fare - a.fare)[0] : null
  const crashCount = drilldown?.crashes_today ?? drilldown?.crashes?.length ?? 0
  const worstPothole = (drilldown?.potholes || [])[0]
  const reviewedShare = (() => {
    const all = drilldown?.potholes || []
    if (all.length === 0) return null
    return Math.round((100 * all.filter((p) => p.reviewed).length) / all.length)
  })()
  const topDelayRoute = Object.entries(snap.incidents_by_route || {}).sort((a, b) => b[1] - a[1])[0]
  const highlights = [
    { icon: '🛣️', label: 'Busiest Route', value: topRoute?.name ?? '—', sub: topRoute ? `${topRoute.potholes} potholes` : undefined, color: '#d97706' },
    { icon: '⚠️', label: 'Top Event Type', value: topEvent ? topEvent[0].split('_').map((w) => w[0] + w.slice(1).toLowerCase()).join(' ') : '—', sub: topEvent ? `${topEvent[1]} events` : undefined, color: '#dc2626' },
    { icon: '🚌', label: 'Top Risk Bus', value: topRiskBus?.bus_id ?? '—', sub: topRiskBus ? `score ${topRiskBus.risk_score}` : undefined, color: '#f97316' },
    { icon: '🎫', label: 'Top Revenue', value: topFareBus?.bus ?? '—', sub: topFareBus ? `₹${topFareBus.fare.toLocaleString()}` : undefined, color: 'var(--green)' },
    { icon: '🚨', label: 'Major Incident', value: crashCount > 0 ? `${crashCount} crash(es) today` : 'None today', sub: crashCount > 0 ? 'open Crash Detections for the report' : undefined, color: '#dc2626' },
    { icon: '🕳️', label: 'Most-Detected Pothole', value: worstPothole ? `${worstPothole.bus_count} buses @ ${worstPothole.lat?.toFixed(3)}, ${worstPothole.lon?.toFixed(3)}` : '—', sub: worstPothole ? `${worstPothole.total_detections} detections · ${worstPothole.review_status}` : undefined, color: '#92400e' },
    { icon: '📋', label: 'Pothole Review', value: reviewedShare != null ? `${reviewedShare}% reviewed` : '—', sub: 'of today\'s pothole spots', color: '#2563eb' },
    { icon: '🐢', label: 'Worst Delay Route', value: topDelayRoute?.[0] ?? '—', sub: topDelayRoute ? `${topDelayRoute[1]} incidents` : undefined, color: '#7c3aed' },
    { icon: '⚡', label: 'Overloaded Buses', value: overview?.overloaded_buses ?? 0, sub: 'past 95% capacity', color: '#ea580c' },
    { icon: '🚦', label: 'Traffic Zones', value: overview?.road_hazards ?? 0, sub: 'active road hazards', color: '#b45309' },
  ]

  const byDate = snap.potholes_by_date || []
  const byRoute = snap.potholes_by_route || {}
  const byDateRoute = snap.potholes_by_date_route || []
  const topRoutes = Object.entries(byRoute).sort((a, b) => b[1] - a[1]).slice(0, 8)
  const routeColor = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#4f46e5', '#0ea5e9', '#e11d48', '#7c3aed']

  return (
    <>
      {isLive && (
        <div className="card mb-16" style={{ borderLeft: useFallback ? '4px solid var(--accent)' : '4px solid var(--green)' }}>
          {useFallback ? (
            <span style={{ fontSize: 13, color: '#17212B' }}>
              ⚡ <strong>Live Analytics</strong> — prototype upstream is quiet, so the charts below load a·<strong>simulated comparison baseline</strong> (same 100-bus simulator level) to keep the view full.
            </span>
          ) : (
            <span style={{ fontSize: 13, color: '#17212B' }}>
              ⚡ <strong>Live Analytics</strong> — real-time prototype telemetry as it arrives from the connected bus node; joined with the simulated fleet baseline.
            </span>
          )}
        </div>
      )}

      {/* Live fleet KPIs — Potholes Today / Road Hazards / Crash Detected are
          clickable and drill into where/when/which-bus detail (with the
          crash legal report). "Crash Detected" replaces the old notes panel. */}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
        <KpiCard label="Active Buses" value={overview?.active_buses} color="#2563eb" icon="🚌" />
        <KpiCard label="Live Nodes" value={overview?.live_nodes} color="#0ea5e9" icon="📡" />
        <KpiCard label="Fare Collected" value={overview?.fare_collected != null ? `₹${overview.fare_collected.toLocaleString()}` : '—'} color="var(--green)" icon="💰" />
        <KpiCard label="Tickets Today" value={overview?.tickets_today} color="var(--green)" icon="🎟️" />
        <div onClick={() => setDrillKind('crashes')} style={{ cursor: 'pointer' }} title="Open crash detections — time, footage, route, driver, conductor, report">
          <KpiCard label="🚨 Crash Detected" value={crashCount} sub="click for full detail" color="var(--red)" icon="🚨" />
        </div>
        <KpiCard label="Overloaded Buses" value={overview?.overloaded_buses} color={overview?.overloaded_buses ? 'var(--red)' : 'var(--muted)'} icon="⚖️" />
        <div onClick={() => setDrillKind('hazards')} style={{ cursor: 'pointer' }} title="Open road hazards — place, time, detecting bus">
          <KpiCard label="Road Hazards" value={overview?.road_hazards ?? drilldown?.road_hazards_today ?? 0} sub="click for detail" color={overview?.road_hazards ? 'var(--red)' : 'var(--muted)'} icon="⚠️" />
        </div>
        <div onClick={() => setDrillKind('potholes')} style={{ cursor: 'pointer' }} title="Open potholes today — place, time, which buses detected, review state">
          <KpiCard label="Potholes Today" value={snap.potholes_today ?? drilldown?.potholes_today ?? '—'} sub="click for detail" color="#d97706" icon="🛠️" />
        </div>
      </div>

      <DrilldownModal kind={drillKind} data={drilldown} onClose={() => setDrillKind(null)} />

      {/* Fleet delay summary + recorded risk transitions (live engines) */}
      <EtaSummaryPanel />
      <RiskEventsPanel />

      {/* Fleet Pulse + Key Highlights */}
      <div className="grid grid-2 mb-16">
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Fleet Pulse</h3>
            <span className="badge badge-blue">overall risk</span>
          </div>
          <div className="flex" style={{ alignItems: 'center', gap: 20 }}>
            <RiskGauge score={risk?.avg_score} />
            <div style={{ flex: 1 }}>
              <div className="flex wrap gap-8">
                {riskLevels.map((l) => (
                  <span key={l.name} className="chip">
                    <span className="risk-badge" style={{ background: riskTone(l.name) }}>{l.name}</span>
                    <strong>&nbsp;{l.value}</strong>
                  </span>
                ))}
              </div>
              <div className="muted" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.5 }}>
                {overview?.active_buses != null ? `${overview.active_buses} active bus${overview.active_buses === 1 ? '' : 's'} · ${overview.live_nodes} live node${overview.live_nodes === 1 ? '' : 's'}` : ''}
                <br />
                {risk?.data_coverage ? `data coverage ${risk.data_coverage}` : risk?.computed_at ? `computed ${new Date(risk.computed_at).toLocaleTimeString()}` : ''}
              </div>
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Key Highlights</h3>
            <span className="badge badge-blue">auto-derived</span>
          </div>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
            {highlights.map((h) => (
              <HighlightTile key={h.label} icon={h.icon} label={h.label} value={h.value} sub={h.sub} color={h.color} />
            ))}
          </div>
        </div>
      </div>

      {/* RISK SCORE BY BUS — BIG (same visual weight as Fleet Boarding),
          showing every bus. Risk Level Distribution is the small card below. */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Risk Score by Bus</h3>
          <div className="flex align-center gap-8">
            <span className="badge badge-blue">every bus · 0–100</span>
            <span className="chip">avg <strong>{risk?.avg_score ?? '—'}</strong></span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={riskData} margin={{ bottom: 12 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
            <XAxis dataKey="name" fontSize={10} interval={0} angle={-45} textAnchor="end" height={70} />
            <YAxis fontSize={11} domain={[0, 100]} />
            <Tooltip />
            <Bar dataKey="score" radius={[4, 4, 0, 0]}>
              {riskData.map((d) => (
                <Cell key={d.name} fill={d.score >= 60 ? '#dc2626' : d.score >= 30 ? '#d97706' : '#16a34a'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Risk Level Distribution — small, below Risk Score by Bus */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Risk Level Distribution</h3>
          <span className="badge badge-blue">fleet risk</span>
        </div>
        <div className="flex wrap gap-8 mb-8">
          {riskLevels.map((l) => (
            <span key={l.name} className="chip">
              <span className="risk-badge" style={{ background: riskTone(l.name) }}>{l.name}</span>
              <strong>&nbsp;{l.value}</strong>
            </span>
          ))}
        </div>
        <ResponsiveContainer width="100%" height={160}>
          <PieChart>
            <Pie data={riskLevels} dataKey="value" nameKey="name" outerRadius={60} label>
              {riskLevels.map((_, i) => <Cell key={i} fill={riskTone(riskLevels[i].name)} />)}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Boarding + Pothole */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Fleet Boarding by Time of Day</h3>
          <span className="badge badge-blue">morning & evening rush</span>
        </div>
        <div className="flex wrap gap-8 mb-8">
          {snap.boarding_peak && (
            <span className="chip">peak <strong>&nbsp;{snap.boarding_peak.label}</strong> · {snap.boarding_peak.boardings} boardings</span>
          )}
          {snap.boarding_quietest && (
            <span className="chip">quietest <strong>&nbsp;{snap.boarding_quietest.label}</strong> · {snap.boarding_quietest.boardings} boardings</span>
          )}
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={hourlyBoardings}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
            <XAxis dataKey="hour" fontSize={10} />
            <YAxis fontSize={11} allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="boardings" fill="#2563eb" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* PASSENGER OCCUPANCY — BIG (all buses fit), % boarding rate per
          service-hour bucket. The old dense per-bus text list is gone. */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Passenger Occupancy — boarding % by time of day</h3>
          <div className="flex align-center gap-8">
            <span className="badge badge-blue">share of passengers boarding per hour</span>
            {snap.boarding_peak && <span className="chip">peak <strong>{snap.boarding_peak.label}</strong></span>}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={hourlyBoardings}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
            <XAxis dataKey="hour" fontSize={10} />
            <YAxis fontSize={11} unit="%" />
            <Tooltip formatter={(v) => [`${v}% of daily boardings`, 'share']} />
            <Bar dataKey="pct" fill="#2563eb" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
          Each bar: how many % of the day's passengers board in that hour (05:00 → 23:00 service day). Buses in the table below carry {occupancyData.length} vehicles.
        </div>
      </div>

      {/* Potholes by Route — small, below occupancy */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Potholes by Route</h3>
          <span className="badge badge-blue">{snap.potholes_total ?? 0} total</span>
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={potholeRouteData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
            <XAxis dataKey="name" fontSize={10} interval={0} angle={-35} textAnchor="end" height={50} />
            <YAxis fontSize={11} allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="potholes" fill="#d97706" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Fare Collection by Bus — graph instead of the removed table */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Fare Collection by Bus</h3>
          <span className="badge badge-blue">₹ per bus today</span>
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={fareData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
            <XAxis dataKey="bus" fontSize={10} interval={0} angle={-45} textAnchor="end" height={60} />
            <YAxis fontSize={11} />
            <Tooltip formatter={(v) => `₹${Number(v).toLocaleString()}`} />
            <Bar dataKey="fare" fill="#16a34a" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Pothole trend */}
      <div className="grid grid-2 mb-16">
        <TimelineChart data={potholeTrend} title="Pothole Reports — Last 8 Days" color="#d97706" />
        <div className="card">
          <div className="card-header"><h3 className="card-title">Fare Summary</h3></div>
          <div className="muted" style={{ fontSize: 12, lineHeight: 1.8 }}>
            Total fare collected today: <strong>₹{fareTotal.toLocaleString()}</strong> across {fareData.length} buses.
            Per-bus breakdown is in the Fare Collection by Bus graph above.
          </div>
        </div>
      </div>

      <div className="grid grid-2 mb-16">
        <div className="card">
          <div className="card-header"><h3 className="card-title">Drowsiness Events by Bus</h3></div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={drowsyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
              <XAxis dataKey="name" fontSize={11} />
              <YAxis fontSize={11} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="events" fill="#2563eb" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="card-title">Incidents by Route</h3></div>
          {routeData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={routeData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
                <XAxis dataKey="name" fontSize={10} />
                <YAxis fontSize={11} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="incidents" fill="#d97706" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="muted" style={{ fontSize: 12, padding: '32px 16px', textAlign: 'center' }}>
              No route incidents recorded yet — they'll appear here as they're logged.
            </div>
          )}
        </div>
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Event Type Distribution</h3>
            <span className="muted" style={{ fontSize: 10 }}>driver-family types merged into one Driver Incident bucket</span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={typeData} dataKey="events" nameKey="name" outerRadius={90} label>
                {typeData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* EV vs DIESEL comparison */}
        <div className="card" style={{ gridColumn: '1 / -1' }}>
          <div className="card-header">
            <h3 className="card-title">⚡ EV vs Diesel — fleet comparison</h3>
            <span className="badge badge-blue">who runs cleaner &amp; safer</span>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={evDieselChart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
              <XAxis dataKey="type" fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip />
              <Legend />
              <Bar dataKey="buses" fill="#2563eb" radius={[4, 4, 0, 0]} />
              <Bar dataKey="drowsiness events" fill="#dc2626" radius={[4, 4, 0, 0]} />
              <Bar dataKey="fare (₹)" fill="#16a34a" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            Same-store comparison of electric vs diesel buses: fleet size, driver-safety events and fare output. Higher driver incidents = more DDS attention needed for that fuel type.
          </div>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="card-title">Severity Distribution</h3></div>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={severityData} dataKey="value" nameKey="name" outerRadius={90} label>
                <Cell fill="#dc2626" />
                <Cell fill="#d97706" />
                <Cell fill="#2563eb" />
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Origin-Destination flow estimates (Phase 13) */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">🧭 Origin → Destination (OD) Flows</h3>
          <span className="badge badge-blue">estimated · HEURISTIC</span>
        </div>
        {odData?.top_pairs?.length > 0 ? (
          <>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 12 }}>
              <KpiCard label="Riders (est.)" value={odData.total_riders_estimated} color="#6d28d9" />
              <KpiCard label="Buses Analyzed" value={odData.buses_analyzed} color="var(--accent)" />
              <KpiCard label="Routes Covered" value={odData.routes_covered?.length ?? 0} color="#0ea5e9" />
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="table" style={{ minWidth: 520 }}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Origin</th>
                    <th>→ Destination</th>
                    <th style={{ textAlign: 'right' }}>Riders (est.)</th>
                  </tr>
                </thead>
                <tbody>
                  {odData.top_pairs.map((p, i) => (
                    <tr key={`${p.origin}-${p.destination}`}>
                      <td className="muted">{i + 1}</td>
                      <td><strong>{p.origin}</strong></td>
                      <td>{p.destination}</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{Math.round(p.riders)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted mt-8" style={{ fontSize: 11, lineHeight: 1.6 }}>
              <strong>⚠ HEURISTIC estimate.</strong> {odData.note}
            </div>
          </>
        ) : (
          <div className="muted" style={{ fontSize: 12, padding: 16 }}>
            No OD data available yet — board by stop, board by hour and route stop sequences are needed to estimate flows.
          </div>
        )}
      </div>
</>
  )
}

// ---------------------------------------------------------------------------
// Historical analytics view
// ---------------------------------------------------------------------------

function HistoricalView() {
  const [timeRange, setTimeRange] = useState('24h')
  const [domain, setDomain] = useState('overview')

  const params = { time_range: timeRange }
  const { data: kpis } = usePoll(() => api.analyticsKpis(params), 8000, [timeRange])
  const { data: events } = usePoll(() => api.analyticsEvents(params), 8000, [timeRange])
  const { data: incidents } = usePoll(() => api.analyticsIncidents(params), 8000, [timeRange])
  const { data: risk } = usePoll(() => api.analyticsRisk(params), 8000, [timeRange])
  const { data: eta } = usePoll(() => api.analyticsEta(params), 8000, [timeRange])
  const { data: load } = usePoll(() => api.analyticsLoad(params), 8000, [timeRange])
  const { data: road } = usePoll(() => api.analyticsRoad(params), 8000, [timeRange])
  const { data: safety } = usePoll(() => api.analyticsDriverSafety(params), 8000, [timeRange])
  const { data: routes } = usePoll(() => api.analyticsRoutes(params), 8000, [timeRange])
  const { data: busAnalytics } = usePoll(() => api.analyticsBuses(params), 8000, [timeRange])
  const { data: insights } = usePoll(() => api.analyticsInsights(params), 8000, [timeRange])

  const domains = [
    { key: 'overview', label: 'Overview' },
    { key: 'incidents', label: 'Incidents' },
    { key: 'risk', label: 'Risk' },
    { key: 'eta', label: 'Delays' },
    { key: 'load', label: 'Load' },
    { key: 'road', label: 'Road' },
    { key: 'safety', label: 'Driver Safety' },
    { key: 'routes', label: 'Routes' },
    { key: 'buses', label: 'Buses' },
  ]

  return (
    <>
      {/* Time range selector */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Time Range</h3>
          <div className="filter-row">
            {TIME_RANGES.map((tr) => (
              <button
                key={tr.value}
                className={`seg ${timeRange === tr.value ? 'active' : ''}`}
                onClick={() => setTimeRange(tr.value)}
              >
                {tr.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Domain tabs */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Analytics Domain</h3>
          <div className="filter-row" style={{ flexWrap: 'wrap' }}>
            {domains.map((d) => (
              <button
                key={d.key}
                className={`seg ${domain === d.key ? 'active' : ''}`}
                onClick={() => setDomain(d.key)}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Overview KPIs */}
      {domain === 'overview' && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="Total Events" value={kpis?.total_events} color="var(--accent)" />
            <KpiCard label="Active Buses" value={kpis?.active_buses} color="#2563eb" />
            <KpiCard label="Total Incidents" value={kpis?.total_incidents} color="var(--amber)" />
            <KpiCard label="Active Incidents" value={kpis?.active_incidents} color="#f97316" />
            <KpiCard label="Critical Incidents" value={kpis?.critical_incidents} color="var(--red)" />
            <KpiCard label="High-Risk Events" value={kpis?.high_risk_events} color="var(--red)" />
            <KpiCard label="Overloaded Buses" value={kpis?.overloaded_buses} color="#f97316" />
            <KpiCard label="Severe Delays" value={kpis?.severe_delays} color="#d97706" />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={kpis?.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Time range: {kpis?.time_range}</span>
          </div>
          {events?.timeline && <TimelineChart data={events.timeline} title="Events Over Time" />}
          {incidents?.timeline && <TimelineChart data={incidents.timeline} title="Incidents Over Time" color="#d97706" />}
          {insights?.insights && insights.insights.length > 0 && (
            <div className="mb-16">
              <h3 style={{ fontSize: 14, marginBottom: 12 }}>Operational Insights</h3>
              <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
                {insights.insights.map((ins, i) => <InsightCard key={i} insight={ins} />)}
              </div>
            </div>
          )}
        </>
      )}

      {/* Incidents domain */}
      {domain === 'incidents' && incidents && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="Total Incidents" value={incidents.total} color="var(--accent)" />
            <KpiCard label="Avg Duration (h)" value={incidents.avg_duration_hours} color="#2563eb" />
            <TrendBadge trend={incidents.trend} slope={incidents.trend_slope} />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={incidents.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Records: {incidents.record_count}</span>
          </div>
          {incidents.timeline && <TimelineChart data={incidents.timeline} title="Incidents Over Time" color="#d97706" />}
          <div className="grid grid-2 mb-16">
            <DistributionTable data={incidents.by_category} title="By Category" />
            <DistributionTable data={incidents.by_severity} title="By Severity" />
            <DistributionTable data={incidents.by_status} title="By Status" />
            <DistributionTable data={incidents.by_priority} title="By Priority" />
          </div>
          <DistributionTable data={incidents.by_bus} title="Incidents by Bus" />
          <div className="muted mt-8" style={{ fontSize: 11 }}>{incidents.note}</div>
        </>
      )}

      {/* Risk domain */}
      {domain === 'risk' && risk && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="Risk Events" value={risk.total} color="var(--accent)" />
            <KpiCard label="Avg Score" value={risk.avg_score} color="#2563eb" />
            <KpiCard label="High Risk" value={risk.high_risk_count} color="#f97316" />
            <KpiCard label="Critical Risk" value={risk.critical_risk_count} color="var(--red)" />
            <TrendBadge trend={risk.trend} slope={risk.trend_slope} />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={risk.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Records: {risk.record_count}</span>
          </div>
          {risk.timeline && <TimelineChart data={risk.timeline} title="Risk Events Over Time" color="#f97316" />}
          <div className="grid grid-2 mb-16">
            <DistributionTable data={risk.by_level} title="By Risk Level" />
            <DistributionTable data={risk.by_bus} title="By Bus" />
          </div>
          {risk.transitions && Object.keys(risk.transitions).length > 0 && (
            <DistributionTable data={risk.transitions} title="Risk Transitions" />
          )}
          <div className="muted mt-8" style={{ fontSize: 11 }}>{risk.note}</div>
        </>
      )}

      {/* ETA / Delay domain */}
      {domain === 'eta' && eta && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="ETA Snapshots" value={eta.total} color="var(--accent)" />
            <KpiCard label="Avg Delay (min)" value={eta.avg_delay_minutes} color="#d97706" />
            <KpiCard label="Severe Delays" value={eta.severe_delay_count} color="var(--red)" />
            <TrendBadge trend={eta.trend} slope={eta.trend_slope} />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={eta.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Records: {eta.record_count}</span>
          </div>
          {eta.timeline && <TimelineChart data={eta.timeline} title="Delay Events Over Time" color="#d97706" />}
          <div className="grid grid-2 mb-16">
            <DistributionTable data={eta.delay_distribution} title="Delay Distribution" />
            <DistributionTable data={eta.by_bus} title="By Bus" />
          </div>
          <div className="muted mt-8" style={{ fontSize: 11 }}>{eta.note}</div>
        </>
      )}

      {/* Load domain */}
      {domain === 'load' && load && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="Load Snapshots" value={load.total} color="var(--accent)" />
            <KpiCard label="Avg Occupancy %" value={load.avg_occupancy_pct} color="#2563eb" />
            <KpiCard label="Overloaded" value={load.overloaded_count} color="var(--red)" />
            <KpiCard label="High Occupancy" value={load.high_occupancy_count} color="#f97316" />
            <TrendBadge trend={load.trend} slope={load.trend_slope} />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={load.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Records: {load.record_count}</span>
          </div>
          {load.timeline && <TimelineChart data={load.timeline} title="Load Snapshots Over Time" color="#2563eb" />}
          <div className="grid grid-2 mb-16">
            <DistributionTable data={load.load_distribution} title="Load Distribution" />
            <DistributionTable data={load.by_bus} title="By Bus (Avg Utilization)" />
          </div>
        </>
      )}

      {/* Road domain */}
      {domain === 'road' && road && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="Road Events" value={road.total_events} color="var(--accent)" />
            <KpiCard label="Risk Zones" value={road.zones_count} color="#f97316" />
            <KpiCard label="Clusters" value={road.clusters_count} color="#d97706" />
            <TrendBadge trend={road.trend} slope={road.trend_slope} />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={road.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Records: {road.record_count}</span>
          </div>
          {road.timeline && <TimelineChart data={road.timeline} title="Road Events Over Time" color="#d97706" />}
          <div className="grid grid-2 mb-16">
            <DistributionTable data={road.event_types} title="Event Types" />
            <DistributionTable data={road.zone_risk_levels} title="Zone Risk Levels" />
          </div>
          <div className="muted mt-8" style={{ fontSize: 11 }}>{road.note}</div>
        </>
      )}

      {/* Driver Safety domain */}
      {domain === 'safety' && safety && (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <KpiCard label="Safety Events" value={safety.total} color="var(--accent)" />
            <TrendBadge trend={safety.trend} slope={safety.trend_slope} />
          </div>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={safety.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Records: {safety.record_count}</span>
          </div>
          {safety.timeline && <TimelineChart data={safety.timeline} title="Safety Events Over Time" color="#dc2626" />}
          <div className="grid grid-2 mb-16">
            <DistributionTable data={safety.by_type} title="By Event Type" />
            <DistributionTable data={safety.by_bus} title="By Bus" />
          </div>
          {safety.repeated_offenders?.length > 0 && (
            <div className="card mb-16">
              <div className="card-header"><h3 className="card-title">Repeated Safety Events</h3></div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Bus ID</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Event Count</th>
                  </tr>
                </thead>
                <tbody>
                  {safety.repeated_offenders.map((o) => (
                    <tr key={o.bus_id}>
                      <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{o.bus_id}</td>
                      <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right', color: 'var(--red)' }}>{o.event_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="muted mt-8" style={{ fontSize: 11 }}>{safety.note}</div>
        </>
      )}

      {/* Routes domain */}
      {domain === 'routes' && routes && (
        <>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={routes.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Routes: {Object.keys(routes.routes || {}).length}</span>
          </div>
          {routes.ranked_routes && routes.ranked_routes.length > 0 ? (
            <div className="card mb-16">
              <div className="card-header"><h3 className="card-title">Route Attention Ranking</h3></div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Route</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Events</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Incidents</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Risk Events</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Avg Util %</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {routes.ranked_routes.map((route) => {
                    const rd = routes.routes[route]
                    return (
                      <tr key={route}>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{route}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{rd.event_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{rd.incident_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{rd.risk_event_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{rd.avg_utilization ?? '—'}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right', fontWeight: 700 }}>{rd.attention_score}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="card mb-16"><div className="muted" style={{ fontSize: 12, padding: 16 }}>No route data available.</div></div>
          )}
          <div className="muted" style={{ fontSize: 11 }}>{routes.note}</div>
        </>
      )}

      {/* Buses domain */}
      {domain === 'buses' && busAnalytics && (
        <>
          <div className="flex gap-8 mb-16">
            <DataSourceBadge source={busAnalytics.data_source} />
            <span className="muted" style={{ fontSize: 11 }}>Buses analyzed: {Object.keys(busAnalytics.buses || {}).length}</span>
          </div>
          {busAnalytics.ranked_buses && busAnalytics.ranked_buses.length > 0 ? (
            <div className="card mb-16">
              <div className="card-header"><h3 className="card-title">Bus Attention Ranking</h3></div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Bus ID</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Events</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Incidents</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>High Risk</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Severe Delays</th>
                    <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {busAnalytics.ranked_buses.map((bus) => {
                    const bd = busAnalytics.buses[bus]
                    return (
                      <tr key={bus}>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{bus}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{bd.event_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{bd.incident_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{bd.high_risk_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{bd.severe_delay_count}</td>
                        <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right', fontWeight: 700 }}>{bd.attention_score}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="card mb-16"><div className="muted" style={{ fontSize: 12, padding: 16 }}>No bus data available.</div></div>
          )}
        </>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Main Analytics page
// ---------------------------------------------------------------------------

/* ─── Operations View: maintenance / traffic / road quality / punctuality / demand ─── */
function OperationsView() {
  const { data, error } = usePoll(api.operationsAnalytics, 8000)

  if (error) {
    return <div className="card"><div className="empty">Unable to load operations analytics: {error.message}</div></div>
  }
  if (!data) {
    return <div className="card"><div className="empty">Computing operations analytics…</div></div>
  }

  const maintenance = data.maintenance || {}
  const traffic = data.traffic || {}
  const road = data.road_quality || {}
  const punct = data.punctuality || {}
  const demand = data.demand || {}
  const atRisk = maintenance.at_risk || []

  const maintenanceTone = (status) =>
    status === 'SEND_TO_MAINTENANCE' ? 'var(--red)' :
    status === 'PLAN_MAINTENANCE' ? 'var(--amber)' : 'var(--green)'

  return (
    <>
      <div className="grid mb-16" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
        <KpiCard icon="⏱️" label="Fleet On-Time" value={punct.fleet_on_time_pct != null ? `${punct.fleet_on_time_pct}%` : '—'} sub="ETA delay bands" color="var(--green)" />
        <KpiCard icon="🚦" label="Active Hotspots" value={traffic.active_count ?? 0} sub={`${traffic.max_buses_in_one_zone ?? 0} buses in worst zone`} color="var(--red)" />
        <KpiCard icon="🕳️" label="Unique Defects" value={road.unique_defects ?? 0} sub={`${road.recurring_spots ?? 0} recurring spots`} color="var(--amber)" />
        <KpiCard icon="🔧" label="Vehicles At Risk" value={atRisk.length} sub={`of ${maintenance.fleet_size ?? 0} in fleet`} color="#2563eb" />
      </div>

      {/* Predictive maintenance */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">🔧 Predictive Maintenance — Next to Fail</h3>
          <span className="muted" style={{ fontSize: 12 }}>shortest days-to-failure across degraded components · display only</span>
        </div>
        {atRisk.length === 0 ? (
          <div className="empty">No vehicle currently needs maintenance within 3 days.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Bus</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Decision</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Days to failure</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Worst component</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {atRisk.slice(0, 15).map((m) => (
                <tr key={m.bus_id}>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>
                    {m.bus_id}<span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>{m.reg_no}</span>
                  </td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8' }}>
                    <span className="chip" style={{ background: maintenanceTone(m.status), color: '#fff', fontSize: 10 }}>
                      {(m.status || '').replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right', fontWeight: 700, color: maintenanceTone(m.status) }}>
                    {m.days_to_failure != null ? m.days_to_failure : '—'}
                  </td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textTransform: 'capitalize' }}>{m.worst_component || '—'}</td>
                  <td className="muted" style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontSize: 11 }}>{m.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid mb-16" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
        {/* Traffic congestion */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">🚦 Traffic Congestion</h3>
            <span className="muted" style={{ fontSize: 11 }}>{traffic.active_count ?? 0} active · {traffic.tracked_zones ?? 0} tracked zones</span>
          </div>
          {(traffic.active_hotspots || []).length === 0 ? (
            <div className="muted" style={{ fontSize: 12, padding: 8 }}>No active high-traffic zones (needs 3+ buses within 50 m for 60 s).</div>
          ) : (
            (traffic.active_hotspots || []).slice(0, 8).map((h) => (
              <div key={h.id} className="flex justify-between align-center chip-list-row" style={{ fontSize: 12 }}>
                <span className="mono">{h.latitude?.toFixed(4)}, {h.longitude?.toFixed(4)}</span>
                <span>
                  <span className="chip" style={{ background: 'var(--red)', color: '#fff', fontSize: 10 }}>{h.bus_count} buses</span>
                  <span className="muted" style={{ marginLeft: 6 }}>{h.duration_sec != null ? `${Math.round(h.duration_sec)}s` : ''}</span>
                </span>
              </div>
            ))
          )}
        </div>

        {/* Road quality */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">🕳️ Pothole & Road Quality</h3>
            <span className="muted" style={{ fontSize: 11 }}>30 m clustering</span>
          </div>
          <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <div className="stat-card"><div className="stat-label">Detections</div><div className="stat-value">{road.total_detections ?? 0}</div></div>
            <div className="stat-card"><div className="stat-label">Active</div><div className="stat-value">{road.active_defects ?? 0}</div></div>
            <div className="stat-card"><div className="stat-label">Recurrence rate</div><div className="stat-value">{road.recurrence_rate != null ? `${(road.recurrence_rate * 100).toFixed(0)}%` : '—'}</div></div>
            <div className="stat-card"><div className="stat-label">Recurring spots</div><div className="stat-value">{road.recurring_spots ?? 0}</div></div>
          </div>
          {(road.trend || []).length > 0 && (
            <div className="muted" style={{ fontSize: 11 }}>
              Recent daily detections: {(road.trend || []).map((t) => `${t.date}: ${t.detections}`).join(' · ')}
            </div>
          )}
        </div>
      </div>

      {/* Punctuality + demand */}
      <div className="grid mb-16" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">⏱️ On-Time / Trip-Time by Route</h3>
            <span className="muted" style={{ fontSize: 11 }}>fleet on-time {punct.fleet_on_time_pct != null ? `${punct.fleet_on_time_pct}%` : '—'}</span>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Route</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>On-time</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Moving</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Avg speed</th>
              </tr>
            </thead>
            <tbody>
              {(punct.routes || []).slice(0, 12).map((r) => (
                <tr key={r.route_code}>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{r.route_code}</td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right', color: r.on_time_pct >= 70 ? 'var(--green)' : r.on_time_pct >= 40 ? 'var(--amber)' : 'var(--red)', fontWeight: 600 }}>
                    {r.on_time_pct}%
                  </td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{r.moving_buses}/{r.buses}</td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{r.avg_speed_kmh != null ? `${r.avg_speed_kmh} km/h` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <div className="card-header">
            <h3 className="card-title">👥 Passenger Demand Trends</h3>
            <span className="muted" style={{ fontSize: 11 }}>occupancy pressure by route</span>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4' }}>Route</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>Buses</th>
                <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', width: 140 }}>Avg occupancy</th>
              </tr>
            </thead>
            <tbody>
              {(demand.routes || []).slice(0, 12).map((r) => (
                <tr key={r.route_code}>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{r.route_code}</td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{r.buses}</td>
                  <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8' }}>
                    {r.avg_occupancy_pct != null ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--bg-hover)', overflow: 'hidden' }}>
                          <div style={{ width: `${Math.min(100, r.avg_occupancy_pct)}%`, height: 6, background: r.avg_occupancy_pct >= 75 ? 'var(--red)' : r.avg_occupancy_pct >= 60 ? 'var(--amber)' : 'var(--green)', borderRadius: 3 }} />
                        </div>
                        <span style={{ fontSize: 11, width: 40, textAlign: 'right' }}>{r.avg_occupancy_pct}%</span>
                      </div>
                    ) : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="muted" style={{ fontSize: 11, padding: '0 4px' }}>
        All operations analytics are honest views over the current in-memory store ({data.mode}). Maintenance decisions and RUL are heuristic projections — no trained ML models.
      </div>
    </>
  )
}

export default function Analytics() {
  const [view, setView] = useState('snapshot')
  const { isLive } = useMode()

  return (
    <>
      <PageHeader
        title="Fleet Analytics"
        sub={isLive
          ? "Live Analytics · real prototype telemetry joined with the simulated fleet baseline"
          : "Historical intelligence · operational decision support"}
        right={<SimBadge />}
      />

      {/* View toggle */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Analytics View</h3>
          <div className="filter-row">
            <button
              className={`seg ${view === 'snapshot' ? 'active' : ''}`}
              onClick={() => setView('snapshot')}
            >
              Real-Time Snapshot
            </button>
            <button
              className={`seg ${view === 'historical' ? 'active' : ''}`}
              onClick={() => setView('historical')}
            >
              Historical Intelligence
            </button>
            <button
              className={`seg ${view === 'operations' ? 'active' : ''}`}
              onClick={() => setView('operations')}
            >
              Operations
            </button>
          </div>
        </div>
      </div>

      {view === 'snapshot' ? <SnapshotView /> : view === 'historical' ? <HistoricalView /> : <OperationsView />}
    </>
  )
}
