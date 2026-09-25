import { useParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge, BreadcrumbBus } from '../components/Layout.jsx'
import { StatusBadge, riskTone } from '../components/UI.jsx'
import CameraGrid, { CameraControlPanel, LiveCameraGrid, ProtoEventFeed } from '../components/CameraFeed.jsx'
import AlertFeed, { eventLabel } from '../components/AlertFeed.jsx'
import ReviewEditor, { BulkReviewEditor } from '../components/ReviewStatus.jsx'
import CallButton from '../components/CallButton.jsx'
import FleetMap from '../components/FleetMap.jsx'
import BusRouteTracker from '../components/BusRouteTracker.jsx'
import { useMode } from '../lib/modeContext.jsx'

function hourLabel(h) {
  return `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`
}

function GaugeBar({ label, value, max, unit = '', tone }) {
  const pct = Math.min(100, (100 * value) / max)
  const color = tone === 'red' ? 'var(--red)' : tone === 'amber' ? 'var(--amber)' : tone === 'blue' ? 'var(--accent)' : 'var(--green)'
  return (
    <div className="mb-8">
      <div className="flex justify-between muted" style={{ fontSize: 12 }}>
        <span>{label}</span>
        <span className="mono">{value}{unit}</span>
      </div>
      <div className="progress mt-8">
        <div style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

function Stat({ label, value, sub }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export default function BusDetails() {
  const { busId } = useParams()
  const { isLive } = useMode()
  const isProto = busId === 'PROTO-001'
  const { data } = usePoll(() => api.bus(busId), 3000, [busId])
  const { data: riskData } = usePoll(() => api.busRisk(busId), 5000, [busId])
  const { data: timelineData } = usePoll(() => api.busTimeline(busId), 8000, [busId])
  const { data: etaData } = usePoll(() => api.busEta(busId), 6000, [busId])
  const { data: demandData } = usePoll(() => api.busDemand(busId), 8000, [busId])
  const { data: roadThreatsData } = usePoll(() => api.busRoadThreats(busId), 8000, [busId])
  const bus = data?.bus
  const recent = data?.recent_events || []
  const risk = riskData

  // For PROTO-001 (70V), show camera even if bus data is loading
  if (!bus && isProto) {
    return (
      <>
        <BreadcrumbBus busId="70V" />
        <PageHeader
          title="70V — Koyambedu ↔ Kilambakkam"
          sub="Live Driver Monitoring · DDS Engine"
          right={<SimBadge />}
        />
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">Live Camera Feeds — 70V</h3>
            <span className="badge badge-green">REAL AI PERCEPTION</span>
          </div>
          {isLive ? <LiveCameraGrid /> : <CameraGrid />}
          {isLive && <ProtoEventFeed />}
        </div>
      </>
    )
  }

  if (!bus) {
    return (
      <>
        <BreadcrumbBus busId={busId} />
        <div className="empty">Loading {busId}…</div>
      </>
    )
  }

  const camStatus = (bus.driver.state === 'NORMAL') ? 'LIVE · DRIVER OK' : `LIVE · ${bus.driver.state}`
  const fatigueStage = bus.driver.fatigue_stage || 'WATCH'
  const perclos = bus.driver.perclos || 0
  const fatigueTone = fatigueStage === 'CRITICAL' ? 'red' : fatigueStage === 'ALERT' ? 'amber' : 'green'
  const activeEvents = recent.filter((e) => e.status === 'ACTIVE')
  const tkt = bus.ticketing || {}
  const en = bus.energy || { type: 'DIESEL', percent: 60 }
  const wheels = bus.wheels || []
  const occ = bus.occupancy || { passengers: 0, pct: 0, capacity: 60 }
  const journey = bus.journey || {}
  const stops = journey.stops || []
  const currentIndex = journey.current_index || 0

  // full route polyline: point A -> point B through every stop (same order the bus travels)
  const routePath = stops.map((s) => [s.lat, s.lon])
  const activeLeg = (() => {
    if (!journey.next_index && journey.next_index !== 0) return null
    const a = stops[currentIndex]
    const b = stops[journey.next_index ?? Math.min(currentIndex + 1, stops.length - 1)]
    return a && b ? [[a.lat, a.lon], [b.lat, b.lon]] : null
  })()

  const cabinAlert = bus.cabin_alert || recent.find((e) => e.event_type === 'DRIVER_ALERT')?.additional_data?.cabin_action

  // ----- boarding analytics (peak hours) -----
  const boardingHour = bus.boarding_by_hour || {}
  const boardingStopHour = bus.boarding_by_stop_hour || {}
  const hourlyData = Object.entries(boardingHour)
    .map(([h, v]) => ({ hour: Number(h), label: hourLabel(Number(h)), boardings: v }))
    .filter((d) => d.hour >= 4 && d.hour < 23)
    .sort((a, b) => a.hour - b.hour)
  const peakEntry = hourlyData.reduce((a, b) => (b.boardings > a.boardings ? b : a), { boardings: -1 })
  const peakHour = bus.boarding_peak_hour != null ? Number(bus.boarding_peak_hour) : peakEntry.hour
  const peakStops = Object.entries(boardingStopHour)
    .map(([stop, byHour]) => ({ stop, count: Number(byHour?.[String(peakHour)] || 0) }))
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 5)
  const dailyBoarded = bus.daily_boarding_total || hourlyData.reduce((a, d) => a + d.boardings, 0)
  const rushBoarded = hourlyData
    .filter((d) => [7, 8, 9].includes(d.hour))
    .reduce((a, d) => a + d.boardings, 0)
  const rushShare = dailyBoarded ? Math.round((100 * rushBoarded) / dailyBoarded) : 0

  return (
    <>
      <div className="mb-16">
        <BreadcrumbBus busId={busId} />
      </div>
      <PageHeader
        title={isProto ? '70V — Koyambedu ↔ Kilambakkam' : bus.route}
        sub={isProto ? `Live Driver Monitoring · ${bus.speed_kmh.toFixed(0)} km/h` : `${bus.reg_no || bus.bus_id} · ${bus.vehicle_type || 'DIESEL'} · ${bus.speed_kmh.toFixed(0)} km/h`}
        right={
          <>
            {!isProto && <CallButton busId={bus.bus_id} label={`${bus.route} · ${bus.reg_no || ''}`} />}
            <SimBadge />
          </>
        }
      />

      <div className="bus-detail-layout">
        {/* LEFT: live map + status cards below the map */}
        <div className="bus-detail-left">
          <div className="card map-card mb-16">
            <div className="card-header">
              <h3 className="card-title">Live Location</h3>
              <span className="muted mono">{bus.latitude.toFixed(4)}, {bus.longitude.toFixed(4)}</span>
            </div>
            <FleetMap buses={[bus]} height={320} routePath={routePath} activeLeg={activeLeg} />
            <div className="mt-8 flex wrap gap-8">
              <span className="chip" style={{ gap: 4 }}>
                <span style={{ display: 'inline-block', width: 14, height: 4, borderRadius: 2, background: '#2563eb' }} /> route A→B
              </span>
              <span className="chip" style={{ gap: 4 }}>
                <span style={{ display: 'inline-block', width: 14, height: 4, borderRadius: 2, background: '#dc2626' }} /> moving
              </span>
              <span className="chip mono"><strong>{bus.bus_id}</strong></span>
              <span className="chip mono">{bus.reg_no}</span>
              <StatusBadge status={bus.vehicle.health === 'NORMAL' && bus.driver.state === 'NORMAL' && bus.load.status === 'NORMAL' ? 'NORMAL' : 'ACTIVE'} />
            </div>
          </div>

          <div className="grid mb-16" style={{ gap: 12, gridTemplateColumns: 'repeat(2, 1fr)' }}>
            <div className="card">
              <div className="card-header"><h3 className="card-title">Driver Status</h3></div>
              <div className="flex justify-between align-center wrap" style={{ gap: 6 }}>
                <span className="flex align-center gap-8">
                  <StatusBadge status={bus.driver.state} />
                  <StatusBadge status={fatigueStage === 'CRITICAL' ? 'CRITICAL FATIGUE' : fatigueStage} />
                </span>
                <span className="muted">
                  EAR {(bus.driver.ear || 0).toFixed(3)} · MAR {(bus.driver.mar || 0).toFixed(3)} · PERCLOS {perclos.toFixed(0)}%
                </span>
              </div>
              {cabinAlert && (
                <div className="alert-item mt-8" style={{ borderLeftColor: 'var(--amber)' }}>
                  <div className="alert-title">🔊 Cabin audio warning issued</div>
                  <div className="alert-meta mono">{cabinAlert.message || 'DRIVER ALERT - wake up'} · via {cabinAlert.channel || 'speakers'}</div>
                </div>
              )}
              <div className="mt-16">
                <GaugeBar label="Eye-closure duration" value={bus.driver.closed_sec || 0} max={4} unit=" s" tone="amber" />
                <GaugeBar label="Head pitch" value={Math.abs(bus.driver.head_pitch_deg || 0)} max={20} unit="°" tone="blue" />
                <GaugeBar
                  label="PERCLOS — eyes-closed share (recent)"
                  value={perclos}
                  max={40}
                  unit="%"
                  tone={perclos >= 40 ? 'red' : perclos >= 25 ? 'amber' : 'green'}
                />
                <GaugeBar
                  label="Cumulative fatigue (long-term)"
                  value={bus.driver.fatigue_lt || 0}
                  max={100}
                  unit=""
                  tone={fatigueTone}
                />
                <GaugeBar
                  label="Recent drowsiness (short-term)"
                  value={bus.driver.fatigue_st || 0}
                  max={100}
                  unit=""
                  tone={(bus.driver.fatigue_st || 0) >= 50 ? 'amber' : 'green'}
                />
              </div>
            </div>

            <div className="card">
              <div className="card-header"><h3 className="card-title">Load / GVW</h3></div>
              <div className="flex justify-between mb-8">
                <StatusBadge status={bus.load.status} />
                <span className="mono">{bus.load.gvw_kg.toLocaleString()} kg</span>
              </div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                Passengers on board <strong>{occ.passengers}</strong> ({occ.pct}% of {occ.capacity || 60})
              </div>
              <GaugeBar label="Payload" value={bus.load.payload_kg} max={bus.load.payload_limit_kg} unit=" kg" tone={bus.load.status === 'NORMAL' ? 'green' : 'amber'} />
            </div>

            <div className="card">
              <div className="card-header"><h3 className="card-title">Energy &amp; Vehicle</h3></div>
              <div className="flex justify-between align-center">
                <StatusBadge status={bus.vehicle.health} />
                <span className="muted">maintenance: {bus.vehicle.maintenance_priority}</span>
              </div>
              <div className="mt-8">
                <GaugeBar
                  label={en.type === 'EV' ? 'Battery (EV %)' : 'Diesel (fuel %)'}
                  value={en.percent || 0}
                  max={100}
                  unit=" %"
                  tone={en.type === 'EV' ? 'green' : 'blue'}
                />
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                {en.type === 'EV' ? `${en.kwh || 0} kWh remaining` : `${en.litres || 0} litres remaining`}
              </div>
            </div>

            <div className="card">
              <div className="card-header"><h3 className="card-title">Speed &amp; Tyre Pressure (PSI)</h3></div>
              <div className="mb-8 flex justify-between align-center">
                <span className="muted">running speed</span>
                <span className="mono stat-value" style={{ fontSize: 22 }}>{bus.speed_kmh.toFixed(0)} <span style={{ fontSize: 12 }}>km/h</span></span>
              </div>
              <div className="grid" style={{ gap: 8, gridTemplateColumns: 'repeat(2, 1fr)' }}>
                {[0, 1, 2, 3].map((i) => {
                  const psi = wheels[i] || 0
                  const ok = psi >= 78 && psi <= 92
                  return (
                    <div key={i} className="flex justify-between" style={{ fontSize: 12 }}>
                      <span className="muted">Wheel {i + 1}</span>
                      <span className="mono" style={{ color: ok ? 'var(--green)' : 'var(--red)' }}>{psi.toFixed(0)} PSI</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: bus stops + GPS journey tracker beside the map */}
        <div className="bus-detail-right">
          <BusRouteTracker
            name={`Route ${bus.bus_id.split(' ')[0]}`}
            start={journey.start}
            end={journey.destination}
            stops={stops}
            currentStopIndex={currentIndex}
            state={journey.state}
          />
        </div>
      </div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Unified Risk Assessment</h3>
          <div className="flex align-center gap-8">
            <span className="muted" style={{ fontSize: 12 }}>weighted from driver / vehicle / load / speed / occupancy / history</span>
            {risk ? (
              <>
                <span
                  className="risk-badge"
                  style={{ background: riskTone(risk.risk_level), fontSize: 13, padding: '4px 12px' }}
                >
                  {risk.risk_level}
                </span>
                {risk.trend && risk.trend !== 'UNKNOWN' && (
                  <span className="chip" style={{ fontSize: 10, background: risk.trend === 'INCREASING' ? '#fee2e2' : risk.trend === 'DECREASING' ? '#dcfce7' : '#e0e7ff', color: risk.trend === 'INCREASING' ? '#dc2626' : risk.trend === 'DECREASING' ? '#16a34a' : '#2563eb' }}>
                    {risk.trend === 'INCREASING' ? '↑ Rising' : risk.trend === 'DECREASING' ? '↓ Falling' : '→ Stable'}
                  </span>
                )}
                {risk.data_coverage && (
                  <span className="chip" style={{ fontSize: 10, background: risk.data_quality === 'COMPLETE' ? '#dcfce7' : risk.data_quality === 'INSUFFICIENT' ? '#fee2e2' : '#fef3c7', color: risk.data_quality === 'COMPLETE' ? '#16a34a' : risk.data_quality === 'INSUFFICIENT' ? '#dc2626' : '#d97706' }}>
                    {risk.data_coverage} factors
                  </span>
                )}
              </>
            ) : null}
          </div>
        </div>
        {!risk ? (
          <div className="empty">Computing risk…</div>
        ) : (
          <div className="grid" style={{ gap: 20, gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)' }}>
            <div>
              <div className="flex justify-between align-center mb-8">
                <span className="muted" style={{ fontSize: 12 }}>RISK SCORE</span>
                <span className="risk-score-big" style={{ color: riskTone(risk.risk_level) }}>
                  {risk.risk_score}
                  <span style={{ fontSize: 13 }}>/100</span>
                </span>
              </div>
              <div className="progress mb-16" style={{ height: 12 }}>
                <div style={{ width: `${Math.min(100, risk.risk_score)}%`, background: riskTone(risk.risk_level) }} />
              </div>
              <h4 className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>SEGMENT BREAKDOWN</h4>
              {Object.entries(risk.segments).map(([key, seg]) => (
                <div key={key} className="mb-8">
                  <div className="flex justify-between muted" style={{ fontSize: 12, marginBottom: 3 }}>
                    <span className="capitalize">{key} <span className="muted">({seg.weight}%)</span></span>
                    <span className="mono">
                      {seg.available ? (
                        <>{seg.score} · {seg.state}</>
                      ) : (
                        <span style={{ color: '#9ca3af' }}>UNKNOWN</span>
                      )}
                    </span>
                  </div>
                  {seg.available ? (
                    <div className="progress" style={{ height: 6 }}>
                      <div
                        style={{
                          width: `${Math.min(100, seg.score)}%`,
                          background: seg.score >= 55 ? 'var(--red)' : seg.score >= 30 ? 'var(--amber)' : 'var(--green)',
                        }}
                      />
                    </div>
                  ) : (
                    <div className="muted" style={{ fontSize: 10, marginTop: 2 }}>Data unavailable</div>
                  )}
                  {seg.evidence && seg.evidence.length > 0 && (
                    <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                      {seg.evidence.map((e, i) => (
                        <span key={i}>{e.detail || e.type}{i < seg.evidence.length - 1 ? ' · ' : ''}</span>
                      ))}
                    </div>
                  )}
                  {seg.source && seg.source !== 'UNKNOWN' && (
                    <div className="muted" style={{ fontSize: 10, marginTop: 1 }}>Source: {seg.source}</div>
                  )}
                </div>
              ))}
            </div>
            <div>
              <h4 className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>TOP CONTRIBUTORS</h4>
              {risk.top_contributors && risk.top_contributors.length > 0 ? (
                <div className="chip-list mb-16">
                  {risk.top_contributors.map((c) => (
                    <div key={c.factor} className="chip-list-row" style={{ fontSize: 12.5 }}>
                      <span className="capitalize">{c.factor}</span>
                      <span className="muted"> — {c.contribution_pct}% of total risk</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="chip-list mb-16">
                  {risk.reasons.map((r) => (
                    <div key={r} className="chip-list-row" style={{ fontSize: 12.5 }}>{r}</div>
                  ))}
                </div>
              )}
              {risk.cross_system_evidence && risk.cross_system_evidence.length > 0 && (
                <>
                  <h4 className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>CROSS-SYSTEM EVIDENCE</h4>
                  <div className="chip-list mb-16">
                    {risk.cross_system_evidence.map((e, i) => (
                      <div key={i} className="chip-list-row" style={{ fontSize: 11.5 }}>
                        <span className="capitalize">{e.system.replace(/_/g, ' ')}</span>
                        <span className="muted"> — {e.detail}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
              <h4 className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>RECOMMENDED ACTIONS</h4>
              <div className="risk-actions">
                {risk.recommended_actions.map((a) => (
                  <div key={a} className="risk-action">▸ {a}</div>
                ))}
              </div>
            </div>
          </div>
        )}
</div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Driver Safety Timeline</h3>
          <div className="flex align-center gap-8">
            <span className="muted" style={{ fontSize: 12 }}>fatigue episodes, recoveries, refresh flags</span>
            {timelineData?.needs_refresh && (
              <span className="risk-badge" style={{ background: 'var(--amber)' }}>REFRESH REQUIRED</span>
            )}
          </div>
        </div>
        {!timelineData ? (
          <div className="empty">Loading timeline…</div>
        ) : timelineData.timeline.length === 0 ? (
          <div className="empty">No fatigue events recorded yet.</div>
        ) : (
          <div className="timeline-list">
            {timelineData.timeline.slice().reverse().map((entry, idx) => (
              <div key={idx} className="timeline-item">
                <div className="timeline-dot" style={{ background: entry.type === 'RECOVERED' ? 'var(--green)' : 'var(--amber)' }} />
                <div className="timeline-content">
                  <div className="flex justify-between">
                    <span className="mono" style={{ fontSize: 12.5 }}>
                      {entry.type === 'RECOVERED' ? '✓ Recovered' : '⚠ Episode started'}
                    </span>
                    <span className="muted mono" style={{ fontSize: 11 }}>{new Date(entry.ts).toLocaleTimeString()}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                    {entry.type === 'RECOVERED'
                      ? `Grade ${entry.grade} · ${entry.duration_ticks} ticks · from ${entry.stage_before}`
                      : `Grade ${entry.grade} · from ${entry.stage_before}`}
                    {' · at ' + entry.location}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">🚌 ETA & Delay Prediction</h3>
          <div className="flex align-center gap-8">
            <span className="muted" style={{ fontSize: 12 }}>dwell model + traffic + road friction</span>
            {etaData && (
              <>
                <span className="chip" style={{ fontSize: 10, background: '#e0e7ff', color: '#2563eb' }}>{etaData.source || 'HEURISTIC'}</span>
                <span className="risk-badge"
                  style={{ background:
                    etaData.delay_summary === 'SEVERE_DELAY' ? 'var(--red)' :
                    etaData.delay_summary === 'SIGNIFICANT_DELAY' ? 'var(--red)' :
                    etaData.delay_summary === 'MINOR_DELAY' ? 'var(--amber)' : 'var(--green)'
                  }}>
                  {etaData.delay_summary}
                </span>
              </>
            )}
          </div>
        </div>
        {!etaData ? (
          <div className="empty">Computing ETA…</div>
        ) : etaData.etas.length === 0 ? (
          <div className="empty">No route data for ETA.</div>
        ) : (
          <>
            {etaData.delay_causes && etaData.delay_causes.length > 0 && (
              <div className="mb-16" style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: 6, border: '1px solid #e2e8f0' }}>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>DELAY FACTORS</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {etaData.delay_causes.map((c, i) => (
                    <span key={i} className="chip" style={{
                      fontSize: 11,
                      background: c.severity === 'CRITICAL' ? '#fecaca' : c.severity === 'WARNING' ? '#fed7aa' : '#e0e7ff',
                      color: c.severity === 'CRITICAL' ? '#991b1b' : c.severity === 'WARNING' ? '#9a3412' : '#1e40af',
                    }}>
                      {c.category}: {c.description}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="grid" style={{ gap: 8, gridTemplateColumns: '1fr 1fr', marginBottom: 12 }}>
              <div className="stat-card">
                <div className="stat-label">Remaining Distance</div>
                <div className="stat-value">{etaData.total_remaining_distance_km ?? '—'} km</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">ETA to Destination</div>
                <div className="stat-value">{etaData.eta_destination ? new Date(etaData.eta_destination).toLocaleTimeString() : '—'}</div>
              </div>
            </div>
            <div className="eta-list">
              <div className="grid" style={{ gap: 4, gridTemplateColumns: '3fr 1fr 1fr 1fr 1fr' }}>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600 }}>Stop</div>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>ETA</div>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>Dwell</div>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>Delay</div>
                <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'center' }}>Band</div>
              </div>
              {etaData.etas.map((e, i) => (
                <div key={i} className="eta-row">
                  <div className="eta-stop">
                    {e.is_major && <span className="badge badge-amber" style={{ fontSize: 9, marginRight: 4 }}>MAJOR</span>}
                    <span className="mono" style={{ fontSize: 12 }}>{e.stop}</span>
                  </div>
                  <div className="mono" style={{ fontSize: 12, textAlign: 'right' }}>
                    {new Date(e.eta).toLocaleTimeString()}
                  </div>
                  <div className="mono" style={{ fontSize: 11, textAlign: 'right', color: 'var(--amber)' }}>
                    {e.base_dwell_sec}s
                  </div>
                  <div className="mono" style={{ fontSize: 11, textAlign: 'right', color: 'var(--red)' }}>
                    +{e.total_delay_sec - e.base_dwell_sec}s
                  </div>
                  <span className="chip" style={{ background: riskTone(e.delay_band), color: '#fff', fontSize: 10.5, textAlign: 'center' }}>
                    {e.delay_band}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">📊 Boarding Demand Forecast</h3>
          <div className="flex align-center gap-8">
            <span className="muted" style={{ fontSize: 12 }}>time-of-day + weekday + road friction model</span>
            {demandData && (
              <span className="muted" style={{ fontSize: 11 }}>
                hour factor {demandData.forecast[0]?.time_factor}x · friction {demandData.forecast[0]?.friction_factor}x
              </span>
            )}
          </div>
        </div>
        {!demandData ? (
          <div className="empty">Computing demand forecast…</div>
        ) : demandData.forecast.length === 0 ? (
          <div className="empty">No upcoming stops for demand forecast.</div>
        ) : (
          <div className="demand-list">
            <div className="grid" style={{ gap: 4, gridTemplateColumns: '3fr 1fr 1fr 1fr 1fr' }}>
              <div className="muted" style={{ fontSize: 11, fontWeight: 600 }}>Stop</div>
              <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>Forecast</div>
              <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>Base</div>
              <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'right' }}>Friction</div>
              <div className="muted" style={{ fontSize: 11, fontWeight: 600, textAlign: 'center' }}>Confidence</div>
            </div>
            {demandData.forecast.map((f, i) => (
              <div key={i} className="demand-row">
                <div className="demand-stop">
                  {f.is_major && <span className="badge badge-amber" style={{ fontSize: 9, marginRight: 4 }}>MAJOR</span>}
                  <span className="mono" style={{ fontSize: 12 }}>{f.stop}</span>
                </div>
                <div className="mono" style={{ fontSize: 12, textAlign: 'right', fontWeight: 600, color: 'var(--accent)' }}>
                  {f.forecast_boardings}
                </div>
                <div className="mono" style={{ fontSize: 11, textAlign: 'right', color: 'var(--muted)' }}>
                  {f.base_boardings}
                </div>
                <div className="mono" style={{ fontSize: 11, textAlign: 'right', color: f.friction_factor < 1 ? 'var(--red)' : 'var(--green)' }}>
                  {f.friction_factor}x
                </div>
                <span className="chip" style={{ background: f.confidence >= 0.85 ? 'var(--green)' : 'var(--amber)', color: '#fff', fontSize: 10.5, textAlign: 'center' }}>
                  {Math.round(f.confidence * 100)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">🛣️ Road Threats on Current Leg</h3>
          <div className="flex align-center gap-8">
            <span className="muted" style={{ fontSize: 12 }}>potholes / roadworks within 1 km of route segment</span>
            {roadThreatsData && roadThreatsData.threats.length > 0 && (
              <span className="risk-badge" style={{ background: 'var(--amber)' }}>
                {roadThreatsData.threats.length} threat(s)
              </span>
            )}
          </div>
        </div>
        {!roadThreatsData ? (
          <div className="empty">Computing road threats…</div>
        ) : roadThreatsData.threats.length === 0 ? (
          <div className="empty">No road threats on current leg.</div>
        ) : (
          <div className="threats-list">
            {roadThreatsData.threats.map((t, i) => (
              <div key={i} className="threat-row">
                <div className="threat-info">
                  <span className="mono" style={{ fontSize: 12.5 }}>
                    {t.top_defect_type} · {t.defect_count} detection(s)
                  </span>
                  <span className="muted" style={{ fontSize: 11, marginLeft: 8 }}>
                    {t.distance_km} km from segment · score {t.risk_score}
                  </span>
                </div>
                <span className="chip" style={{ background: riskTone(t.risk_level), color: '#fff', fontSize: 10.5 }}>
                  {t.risk_level}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Ticketing & Fare Collection</h3>
          <span className="badge badge-blue">MTC ticket machine</span>
        </div>
        <div className="grid stats-grid">
          <Stat label="Passengers on board" value={occ.passengers} sub={`${occ.pct}% capacity`} />
          <Stat label="Tickets sold today" value={tkt.tickets_today ?? 0} sub={tkt.device || 'TMS-5'} />
          <Stat label="Total passengers today" value={tkt.passengers_total ?? 0} sub="printed tickets" />
          <Stat label="Fare collected today" value={`₹${Number(tkt.fare_collected || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`} sub={`avg ₹${tkt.avg_fare ?? 0} · ${tkt.avg_km ?? 0} km`} />
        </div>
      </div>

      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Peak Boarding Hours — Who boards when</h3>
          <span className="badge badge-blue">hour-of-day analytics</span>
        </div>
        <div className="grid" style={{ gap: 16, gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr)' }}>
          <div>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={hourlyData}>
                <XAxis dataKey="label" fontSize={10} interval={0} angle={-40} textAnchor="end" height={46} />
                <YAxis fontSize={11} allowDecimals={false} />
                <Tooltip labelFormatter={(_, p) => p[0]?.payload?.label} formatter={(v) => [`${v} boarded`, 'Passengers']} />
                <Bar dataKey="boardings" radius={[4, 4, 0, 0]}>
                  {hourlyData.map((d) => (
                    <Cell key={d.hour} fill={d.hour === peakHour ? '#2563eb' : '#b8cbe8'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="muted" style={{ fontSize: 12, textAlign: 'center' }}>
              passers boarding over the MTC service day (04:00 → 23:00, all rotations)
            </div>
          </div>
          <div>
            <div className="grid" style={{ gap: 8, gridTemplateColumns: '1fr 1fr' }}>
              <div className="stat-card">
                <div className="stat-label">Peak hour</div>
                <div className="stat-value">{hourLabel(peakHour)}</div>
                <div className="muted" style={{ fontSize: 12 }}>{peakEntry.boardings} boarded</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Morning rush (7–10)</div>
                <div className="stat-value">{rushShare}%</div>
                <div className="muted" style={{ fontSize: 12 }}>of today's boardings</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Quietest hour</div>
                <div className="stat-value">{hourLabel(hourlyData.reduce((a, b) => (b.boardings < a.boardings ? b : a)).hour)}</div>
                <div className="muted" style={{ fontSize: 12 }}>≈ {hourlyData.reduce((a, b) => (b.boardings < a.boardings ? b : a)).boardings} boarded</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Daily boardings</div>
                <div className="stat-value">{dailyBoarded}</div>
                <div className="muted" style={{ fontSize: 12 }}>across all trips</div>
              </div>
            </div>
            <div className="mt-16">
              <h4 className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>MOST PASSENGERS JOIN AT · {hourLabel(peakHour)}</h4>
              <div className="chip-list">
                {peakStops.map((s) => (
                  <div key={s.stop} className="flex justify-between align-center chip-list-row">
                    <span className="mono" style={{ fontSize: 12.5 }}>{s.stop}</span>
                    <span className="mono" style={{ fontSize: 12.5, color: 'var(--accent)', fontWeight: 700 }}>{s.count} boarded</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Camera Section - 70V with live AI */}
      {isProto && isLive && (
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">Live Camera Feeds — 70V</h3>
            <span className="badge badge-green">REAL AI PERCEPTION</span>
          </div>
          <LiveCameraGrid />
          <ProtoEventFeed />
        </div>
      )}

      {/* Camera Section - all other buses */}
      {!isProto && (
        <div className="card mb-16">
          <div className="card-header">
            <h3 className="card-title">Camera Feeds — {bus.bus_id}</h3>
            <span className="badge badge-green">Driver + Cabin live</span>
          </div>
          <CameraGrid
            cams={{
              driver: { active: true, status: `LIVE · ${bus.driver.state}`, meta: 'Driver webcam (bus node)' },
              cabin: { active: true, status: 'LIVE · CCTV', meta: 'Cabin camera · passengers & driver alert' },
              road: { active: false, status: 'PLANNED', meta: 'Front camera to be added' },
            }}
          />
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Recent Events</h3>
          <div className="flex align-center wrap" style={{ gap: 8 }}>
            <span className="muted" style={{ fontSize: 12 }}>{recent.length} events</span>
            <BulkReviewEditor events={recent} busId={bus.bus_id} />
          </div>
        </div>
        {recent.length === 0 && <div className="empty">No recorded events for this bus.</div>}
        <div className="flex" style={{ flexDirection: 'column', gap: 8 }}>
          {recent.slice(0, 10).map((e) => (
            <div key={e.event_id} className={`alert-item sev-${e.severity}`}>
              <div className="flex justify-between align-center wrap" style={{ gap: 8 }}>
                <span className="alert-title">
                  <StatusBadge status={e.severity} /> {eventLabel(e.event_type)} · {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <ReviewEditor event={e} />
              </div>
            </div>
          ))}
        </div>
        {activeEvents.length > 0 && (
          <AlertFeed events={activeEvents} max={8} header="Active Alerts" />
        )}
      </div>
    </>
  )
}