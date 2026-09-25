import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid,
} from 'recharts'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { riskTone } from '../components/UI.jsx'

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
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #eef1f4', textAlign: 'right' }}>%</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', fontWeight: 600 }}>{k}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>{v}</td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid #f4f6f8', textAlign: 'right' }}>
                {total > 0 ? `${((v / total) * 100).toFixed(1)}%` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function KpiCard({ label, value, sub, color }) {
  return (
    <div className="card" style={{ textAlign: 'center', padding: 16 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: color || 'var(--accent)' }}>{value ?? '—'}</div>
      {sub && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Snapshot view (existing real-time analytics)
// ---------------------------------------------------------------------------

function SnapshotView() {
  const { data, error } = usePoll(api.analytics, 6000)
  const { data: risk } = usePoll(api.risk, 6000)
  if (error) return <div className="card" style={{ color: 'var(--red)' }}>Error loading analytics: {String(error)}</div>
  if (!data) return <div className="card">Loading snapshot analytics…</div>

  const riskData = (risk?.buses || []).map((r) => ({ name: r.bus_id, score: r.risk_score }))
  const riskLevels = Object.entries(risk?.by_level || {}).map(([k, v]) => ({ name: k, value: v }))

  const drowsyData = Object.entries(data.drowsiness_by_bus || {}).map(([k, v]) => ({ name: k, events: v }))
  const routeData = Object.entries(data.incidents_by_route || {}).map(([k, v]) => ({ name: k, incidents: v }))
  const typeData = Object.entries(data.event_types || {}).map(([k, v]) => ({ name: k, events: v }))
  const severityData = Object.entries(data.severity || {}).map(([k, v]) => ({ name: k, value: v }))
  const vehicleData = Object.entries(data.vehicle_mix || {}).map(([k, v]) => ({ name: k, value: v }))

  const byDate = data.potholes_by_date || []
  const byRoute = data.potholes_by_route || {}
  const byDateRoute = data.potholes_by_date_route || []
  const topRoutes = Object.entries(byRoute).sort((a, b) => b[1] - a[1]).slice(0, 8)
  const routeColor = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#4f46e5', '#0ea5e9', '#e11d48', '#7c3aed']

  return (
    <>
      {/* Risk Distribution */}
      <div className="grid grid-2 mb-16">
        <div className="card">
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
            <span className="chip">avg score <strong>{risk?.avg_score ?? '—'}</strong></span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={riskLevels} dataKey="value" nameKey="name" outerRadius={80} label>
                {riskLevels.map((_, i) => <Cell key={i} fill={riskTone(riskLevels[i].name)} />)}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="card-title">Risk Score by Bus</h3></div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={riskData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
              <XAxis dataKey="name" fontSize={10} interval={0} angle={-35} textAnchor="end" height={50} />
              <YAxis fontSize={11} domain={[0, 100]} />
              <Tooltip />
              <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                {riskData.map((d) => (
                  <Cell key={d.name} fill={d.score >= 55 ? '#dc2626' : d.score >= 30 ? '#d97706' : '#16a34a'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Boarding + Pothole */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Fleet Boarding by Time of Day</h3>
          <span className="badge badge-blue">morning & evening rush</span>
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={Object.entries(data.hourly_boardings || {}).map(([h, v]) => ({ hour: `${h}:00`, boardings: v }))}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
            <XAxis dataKey="hour" fontSize={10} />
            <YAxis fontSize={11} allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="boardings" fill="#2563eb" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
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
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={routeData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef1f4" />
              <XAxis dataKey="name" fontSize={10} />
              <YAxis fontSize={11} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="incidents" fill="#d97706" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <div className="card-header"><h3 className="card-title">Event Type Distribution</h3></div>
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
    </>
  )
}

// ---------------------------------------------------------------------------
// Historical analytics view (Phase 17)
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

export default function Analytics() {
  const [view, setView] = useState('snapshot')

  return (
    <>
      <PageHeader
        title="Fleet Analytics"
        sub="Historical intelligence · operational decision support"
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
          </div>
        </div>
      </div>

      {view === 'snapshot' ? <SnapshotView /> : <HistoricalView />}
    </>
  )
}
