import { useMemo, useState } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import FleetMap from '../components/FleetMap.jsx'
import { riskTone } from '../components/UI.jsx'
import { RoadCorridorCard } from '../components/V2IntelligencePanels.jsx'

const RANGES = ['Today', 'Last 7 days', 'Last 30 days']

/* Demo "photo" of a road defect (inline SVG placeholder for demonstration). */
function DefectPhoto({ type }) {
  return (
    <div
      style={{
        width: 96, height: 72, borderRadius: 8, border: '1px solid var(--border)',
        overflow: 'hidden', flexShrink: 0, position: 'relative',
      }}
    >
      <svg width="96" height="72" viewBox="0 0 96 72" xmlns="http://www.w3.org/2000/svg">
        <rect width="96" height="72" fill="#dbe4ee" />
        <rect y="6" width="96" height="16" fill="#9db7d1" />
        <rect y="30" width="96" height="28" fill="#3b4a5a" />
        <rect y="30" width="8" height="28" fill="#f8fafc" />
        <rect x="20" y="30" width="8" height="28" fill="#f8fafc" />
        <rect x="40" y="30" width="8" height="28" fill="#f8fafc" />
        <rect x="60" y="30" width="8" height="28" fill="#f8fafc" />
        <circle cx="72" cy="48" r="7" fill="#111827" />
        <polygon points="58,56 62,42 66,56" fill="#f59e0b" />
        <polygon points="56,42 62,30 68,42" fill="#b91c1c" />
        <text x="6" y="20" fontSize="9" fill="#334155" fontFamily="Segoe UI, Arial, sans-serif" fontWeight="700">{type}</text>
      </svg>
    </div>
  )
}

const SOURCE_STYLES = {
  SIMULATION: { bg: '#ede9fe', color: '#7c3aed', label: 'ESTIMATED' },
  HEURISTIC: { bg: '#fef3c7', color: '#b45309', label: 'HEURISTIC' },
  MODEL: { bg: '#d1fae5', color: '#047857', label: 'MODEL' },
  LIVE: { bg: '#fee2e2', color: '#dc2626', label: 'LIVE' },
  UNKNOWN: { bg: '#f3f4f6', color: '#6b7280', label: 'UNKNOWN' },
}

function SourceBadge({ source }) {
  const s = SOURCE_STYLES[source] || SOURCE_STYLES.UNKNOWN
  return (
    <span className="badge" style={{ background: s.bg, color: s.color, fontSize: 10 }}>
      {s.label}
    </span>
  )
}

function ExposureBadge({ state }) {
  const colors = {
    EXPOSED: { bg: '#fee2e2', color: '#dc2626' },
    APPROACHING: { bg: '#fef3c7', color: '#b45309' },
    CLEAR: { bg: '#d1fae5', color: '#047857' },
    UNKNOWN: { bg: '#f3f4f6', color: '#6b7280' },
  }
  const c = colors[state] || colors.UNKNOWN
  return (
    <span className="badge" style={{ background: c.bg, color: c.color, fontSize: 10 }}>
      {state}
    </span>
  )
}

export default function RoadIntelligence() {
  const [range, setRange] = useState('Today')
  const { data: defData } = usePoll(api.roadDefects, 5000)
  const { data: busData } = usePoll(api.buses, 5000)
  const { data: riskData } = usePoll(api.roadRisk, 8000)
  const { data: summaryData } = usePoll(api.roadSummary, 10000)
  const { data: exposureData } = usePoll(api.roadsExposures, 8000)
  const defects = defData?.defects || []
  const buses = busData?.buses || []
  const zones = riskData?.zones || []
  const clusters = riskData?.clusters || []
  const routeIndex = riskData?.route_index || {}
  const summary = summaryData || {}
  const exposures = exposureData?.exposures || []

  const filtered = useMemo(() => {
    const days = range === 'Today' ? 1 : range === 'Last 7 days' ? 7 : 30
    const cutoff = Date.now() - days * 86400000
    return defects.filter((d) => new Date(d.last_detected).getTime() >= cutoff)
  }, [defects, range])

  /* Potholes/defects re-spotted at the same spot by different buses */
  const repeated = useMemo(() => filtered.filter((d) => (d.buses?.length || 0) > 1), [filtered])
  const repeatedTotal = repeated.reduce((n, d) => n + (d.buses?.length || 0), 0)

  const exposedBuses = exposures.filter((e) => e.exposure_state === 'EXPOSED')
  const approachingBuses = exposures.filter((e) => e.exposure_state === 'APPROACHING')

  return (
    <>
      <PageHeader
        title="Road Intelligence"
        sub="Potholes · road defects · risk zones · route risk · bus exposure"
        right={<SimBadge />}
      />

      {/* Summary cards */}
      <div className="grid grid-4 mb-16">
        <div className="card" style={{ borderLeft: '3px solid var(--amber)' }}>
          <div className="muted" style={{ fontSize: 11 }}>Active Defects</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{summary.total_defects || filtered.length}</div>
          <div className="muted" style={{ fontSize: 10 }}>
            {summary.total_detections || 0} total detections
          </div>
        </div>
        <div className="card" style={{ borderLeft: '3px solid var(--red)' }}>
          <div className="muted" style={{ fontSize: 11 }}>Risk Zones</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{zones.length}</div>
          <div className="muted" style={{ fontSize: 10 }}>
            {summary.high_risk_zones || 0} high/critical
          </div>
        </div>
        <div className="card" style={{ borderLeft: '3px solid var(--amber)' }}>
          <div className="muted" style={{ fontSize: 11 }}>Exposed Buses</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{exposedBuses.length}</div>
          <div className="muted" style={{ fontSize: 10 }}>
            {approachingBuses.length} approaching
          </div>
        </div>
        <div className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
          <div className="muted" style={{ fontSize: 11 }}>Affected Routes</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
            {Object.keys(routeIndex).length}
          </div>
          <div className="muted" style={{ fontSize: 10 }}>
            {summary.affected_routes?.length || 0} with risk
          </div>
        </div>
      </div>

      {/* Road Risk Corridors — moved here from the dashboard so corridor-level
          risk lives with the rest of road intelligence. */}
      <RoadCorridorCard />

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Time Range</h3>
          <div className="filter-row">
            {RANGES.map((r) => (
              <button key={r} className={`seg ${range === r ? 'active' : ''}`} onClick={() => setRange(r)}>
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-2 mb-16">
        <div className="card map-card">
          <div className="card-header">
            <h3 className="card-title">City Road-Condition Map</h3>
            <span className="badge badge-amber">
              {filtered.length} defect(s) · {zones.length} risk zone(s)
            </span>
          </div>
          <FleetMap buses={buses} defects={filtered} zones={zones} showDefects height={440} />
        </div>

        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Persistent Road Defects</h3>
            <span className="muted" style={{ fontSize: 12 }}>grouped by location</span>
          </div>
          <div className="alert-feed">
            {filtered.length === 0 && <div className="empty">No road defects in this range.</div>}
            {filtered
              .slice()
              .sort((a, b) => b.detection_count - a.detection_count)
              .map((d) => (
                <div className="alert-item" key={d.defect_id} style={{ borderLeftColor: 'var(--amber)' }}>
                  <div className="flex justify-between align-center">
                    <span className="alert-title">⚠ {d.type}</span>
                    <div className="flex gap-4">
                      <span className="badge badge-amber">×{d.detection_count}</span>
                      <SourceBadge source={d.data_source === 'live' ? 'LIVE' : 'ESTIMATED'} />
                    </div>
                  </div>
                  <div className="flex" style={{ gap: 12, marginTop: 8, alignItems: 'flex-start' }}>
                    <DefectPhoto type={d.type} />
                    <div className="alert-meta" style={{ flex: 1, lineHeight: 1.6 }}>
                      <div>Pothole detected at {new Date(d.last_detected).toLocaleString()}</div>
                      {d.buses?.length > 0 && (
                        <div>Seen by bus: <strong>{d.buses.join(', ')}</strong></div>
                      )}
                      <div>
                        Coordinates: <span className="mono">{(d.latitude ?? 0).toFixed(4)}, {(d.longitude ?? 0).toFixed(4)}</span>
                      </div>
                      <div className="muted">
                        first seen {new Date(d.first_detected).toLocaleString()} · confidence {Math.round((d.confidence || 0) * 100)}%
                      </div>
                    </div>
                  </div>
                  <div className="mt-8">
                    <div className="progress">
                      <div style={{ width: `${Math.round((d.confidence || 0) * 100)}%`, background: 'var(--amber)' }} />
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* Re-spotted potholes — repeated at the same place by different buses */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Potholes Re-Spotted by Other Buses</h3>
          <span className="badge badge-amber">
            {repeated.length} spot(s) · {repeatedTotal} detection(s) by different vehicles
          </span>
        </div>
        {repeated.length === 0 ? (
          <div className="empty">No pothole in this range was detected twice by different buses yet.</div>
        ) : (
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
            {repeated
              .slice()
              .sort((a, b) => (b.buses?.length || 0) - (a.buses?.length || 0))
              .map((d) => (
                <div className="card" key={`repeat-${d.defect_id}`} style={{ padding: '10px 14px' }}>
                  <div className="flex justify-between align-center mb-4">
                    <strong>⚠ {d.type}</strong>
                    <span className="badge badge-amber">×{d.detection_count}</span>
                  </div>
                  <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                    <div>Same spot, hit <strong>{d.buses?.length}</strong> different bus(es): <strong>{d.buses?.join(', ')}</strong></div>
                    <div>At <span className="mono">{(d.latitude ?? 0).toFixed(4)}, {(d.longitude ?? 0).toFixed(4)}</span></div>
                    <div className="muted">Last hit {new Date(d.last_detected).toLocaleString()}</div>
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>

      {/* Risk Zones with evidence */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Road Risk Zones</h3>
          <span className="muted" style={{ fontSize: 12 }}>
            {zones.length} zones computed from defect clusters
          </span>
        </div>
        {zones.length === 0 ? (
          <div className="empty">No risk zones yet — need active defect detections.</div>
        ) : (
          <div className="flex wrap gap-8">
            {zones.map((z) => (
              <div
                key={z.zone_id}
                className="card"
                style={{
                  minWidth: 280,
                  borderLeft: `4px solid ${riskTone(z.risk_level)}`,
                  padding: '10px 14px',
                }}
              >
                <div className="flex justify-between align-center mb-4">
                  <strong style={{ color: riskTone(z.risk_level) }}>{z.risk_level}</strong>
                  <span className="badge" style={{ fontSize: 10 }}>{z.risk_score}/100</span>
                </div>
                <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                  <div>{z.defect_count} defect(s) · {z.total_detections} detections</div>
                  <div>Routes: {(z.routes_affected || []).join(', ') || '—'}</div>
                  <div>Buses: {(z.affected_buses || []).slice(0, 3).join(', ')}{(z.affected_buses || []).length > 3 ? ` +${z.affected_buses.length - 3}` : ''}</div>
                  <div>Type: {z.top_defect_type}</div>
                  <div className="flex gap-4 mt-4">
                    <SourceBadge source={z.source} />
                    <span className="muted" style={{ fontSize: 10 }}>
                      {z.first_detected ? new Date(z.first_detected).toLocaleDateString() : '—'}
                    </span>
                  </div>
                  {z.evidence && (
                    <div className="muted mt-4" style={{ fontSize: 10, lineHeight: 1.4 }}>
                      {z.evidence}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Bus Exposure */}
      {exposures.length > 0 && (
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">Bus Road Exposure</h3>
            <span className="muted" style={{ fontSize: 12 }}>
              {exposedBuses.length} exposed · {approachingBuses.length} approaching
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Bus</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Route</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>State</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Nearest Zone</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Distance</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Risk Level</th>
                </tr>
              </thead>
              <tbody>
                {exposures
                  .filter((e) => e.exposure_state !== 'CLEAR')
                  .sort((a, b) => {
                    const order = { EXPOSED: 0, APPROACHING: 1, UNKNOWN: 2, CLEAR: 3 }
                    return (order[a.exposure_state] || 3) - (order[b.exposure_state] || 3)
                  })
                  .map((e) => (
                    <tr key={e.bus_id} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px' }}>{e.bus_id}</td>
                      <td style={{ padding: '6px 8px' }}>{e.route_code}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <ExposureBadge state={e.exposure_state} />
                      </td>
                      <td style={{ padding: '6px 8px' }}>{e.nearby_zone_id || '—'}</td>
                      <td style={{ padding: '6px 8px' }}>
                        {e.zone_distance_km != null ? `${e.zone_distance_km} km` : '—'}
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        <span
                          className="chip"
                          style={{ background: riskTone(e.zone_risk_level || 'LOW'), color: '#fff', fontSize: 10 }}
                        >
                          {e.zone_risk_level || '—'}
                        </span>
                      </td>
                    </tr>
                  ))}
                {exposures.filter((e) => e.exposure_state !== 'CLEAR').length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: '12px', textAlign: 'center', color: 'var(--muted)' }}>
                      All buses clear of road-risk zones
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Route Risk Index */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Route Risk Index</h3>
          <span className="muted" style={{ fontSize: 12 }}>
            average risk score per route from overlapping zones
          </span>
        </div>
        {Object.keys(routeIndex).length === 0 ? (
          <div className="empty">No route risk data.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Route</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Avg Score</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Zones</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Defects</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Hazards</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Level</th>
                  <th style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>Source</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(routeIndex)
                  .sort((a, b) => b[1].avg_score - a[1].avg_score)
                  .map(([code, r]) => (
                    <tr key={code} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px' }}>{code}</td>
                      <td style={{ padding: '6px 8px' }}>{r.avg_score}</td>
                      <td style={{ padding: '6px 8px' }}>{r.zones_count || r.zones}</td>
                      <td style={{ padding: '6px 8px' }}>{r.total_defects || r.defects}</td>
                      <td style={{ padding: '6px 8px' }}>{r.active_hazards}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <span className="chip" style={{ background: riskTone(r.risk_level || r.level), color: '#fff', fontSize: 10.5 }}>
                          {r.risk_level || r.level}
                        </span>
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        <SourceBadge source={r.source} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Health Correlations */}
      {summary.health_correlations && summary.health_correlations.length > 0 && (
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">Vehicle Health Correlation</h3>
            <span className="muted" style={{ fontSize: 12 }}>contextual — not causal</span>
          </div>
          <div className="alert-feed">
            {summary.health_correlations.map((hc, i) => (
              <div className="alert-item" key={i} style={{ borderLeftColor: 'var(--blue)' }}>
                <div className="alert-title">Bus {hc.bus_id}</div>
                <div className="alert-meta">
                  Vibration: {hc.vibration} · Exposure: {hc.exposure} · Zone: {hc.zone}
                  <br />
                  <em>{hc.correlation}</em>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* How clustering works */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">How repeated detections become one road issue</h3>
        </div>
        <div className="muted" style={{ fontSize: 13, lineHeight: 1.8 }}>
          Multiple detections within 30m are grouped into one <strong>road-defect cluster</strong>.
          Recurring clusters (spanning {'>'}30 minutes) receive higher risk scores.
          Each risk zone shows its evidence: detection count, affected buses/routes, source
          (ESTIMATED/HEURISTIC/LIVE), and temporal pattern. Bus exposure considers both
          proximity and route overlap for accurate operational awareness.
        </div>
      </div>
    </>
  )
}
