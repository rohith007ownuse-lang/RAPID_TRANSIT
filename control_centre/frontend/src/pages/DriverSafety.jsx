import { useState, useMemo, useEffect } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge } from '../components/UI.jsx'
import CameraGrid from '../components/CameraFeed.jsx'
import Gauge from '../components/Gauge.jsx'
import AlertFeed from '../components/AlertFeed.jsx'
import SuggestSearch from '../components/SuggestSearch.jsx'
import { subscribe, getCall, answerCall, declineCall } from '../lib/callCenter.js'

function driverState(driver) {
  if (driver.state === 'DROWSY') return { label: 'CRITICAL', tone: 'badge-red', color: 'var(--red)' }
  if (driver.state === 'ATTENTION') return { label: 'ATTENTION', tone: 'badge-amber', color: 'var(--amber)' }
  return { label: 'NORMAL', tone: 'badge-green', color: 'var(--green)' }
}

function CallAlert() {
  const [call, setCall] = useState(getCall())
  useEffect(() => subscribe(setCall), [])

  if (call.status !== 'ringing') return null

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid var(--green)', background: 'var(--green-soft)' }}>
      <div className="card-header">
        <h3 className="card-title" style={{ color: 'var(--green)' }}>
          📲 Incoming Call — {call.label || call.busId}
        </h3>
      </div>
      <div className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
        The driver pressed the in-bus CALL button and wants to speak with the operator.
      </div>
      <div className="flex gap-8">
        <button className="btn btn-success" onClick={answerCall}>✓ Accept Call</button>
        <button className="btn btn-danger" onClick={declineCall}>✕ Decline</button>
      </div>
    </div>
  )
}

function BusButton({ bus, isActive, onClick }) {
  const state = bus.driver?.state || 'NORMAL'
  const dotColor = state === 'DROWSY' ? 'var(--red)' : state === 'ATTENTION' ? 'var(--amber)' : 'var(--green)'
  const hasAlert = state !== 'NORMAL'

  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 14px',
        borderRadius: 8,
        border: isActive ? '2px solid var(--accent)' : hasAlert ? `2px solid ${dotColor}` : '1px solid var(--border)',
        background: isActive ? 'var(--accent-soft)' : hasAlert ? (state === 'DROWSY' ? 'var(--red-soft)' : 'var(--amber-soft)') : 'var(--bg)',
        cursor: 'pointer',
        fontWeight: isActive || hasAlert ? 600 : 400,
        fontSize: 13,
        transition: 'all 0.15s',
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />
      {bus.bus_id}
    </button>
  )
}

function BusGrid({ buses, selectedBusId, onSelect }) {
  const { alertBuses, normalBuses } = useMemo(() => {
    const alert = []
    const normal = []
    for (const b of buses) {
      const state = b.driver?.state || 'NORMAL'
      if (state !== 'NORMAL') {
        alert.push(b)
      } else {
        normal.push(b)
      }
    }
    // Sort alert buses: DROWSY first, then ATTENTION
    alert.sort((a, b) => {
      const sa = a.driver?.state === 'DROWSY' ? 0 : 1
      const sb = b.driver?.state === 'DROWSY' ? 0 : 1
      return sa - sb
    })
    return { alertBuses: alert, normalBuses: normal }
  }, [buses])

  return (
    <div className="card mb-16">
      <div className="card-header">
        <h3 className="card-title">Select Bus</h3>
        <div className="flex align-center gap-8">
          {/* suggestion search beside the header — same SuggestSearch used on
              Live Fleet: first characters suggest buses, more chars narrow it */}
          <SuggestSearch
            items={buses.map((b) => ({
              key: b.bus_id,
              label: b.bus_id,
              sublabel: `${b.driver?.name || 'driver'} · ${b.route || ''}`,
              keywords: `${b.reg_no || ''} ${b.route || ''} ${b.driver?.name || ''}`,
            }))}
            placeholder="Search bus… (type D → D7, D70…)"
            onSelect={(it) => onSelect(it.label)}
            style={{ width: 280 }}
          />
          <span className="muted" style={{ fontSize: 12 }}>{buses.length} buses</span>
        </div>
      </div>

      {/* Alert buses at top */}
      {alertBuses.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--red)', marginBottom: 8, textTransform: 'uppercase' }}>
            ⚠ Alert — {alertBuses.length} bus(es) need attention
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {alertBuses.map((b) => (
              <BusButton key={b.bus_id} bus={b} isActive={selectedBusId === b.bus_id} onClick={() => onSelect(b.bus_id)} />
            ))}
          </div>
        </div>
      )}

      {/* Normal buses below */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase' }}>
          Normal — {normalBuses.length} buses
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {normalBuses.map((b) => (
            <BusButton key={b.bus_id} bus={b} isActive={selectedBusId === b.bus_id} onClick={() => onSelect(b.bus_id)} />
          ))}
        </div>
      </div>
    </div>
  )
}

export default function DriverSafety() {
  const { data: busData } = usePoll(api.buses, 4000)
  const buses = busData?.buses || []
  const [busId, setBusId] = useState(buses[0]?.bus_id || '')
  const { data, error } = usePoll(() => api.bus(busId), 3000, [busId])
  const bus = data?.bus
  const events = (data?.recent_events || []).filter((e) => e.event_type === 'DRIVER_DROWSINESS')

  const drowsyEvents = usePoll(() => api.events({ type: 'DRIVER_DROWSINESS', status: 'ACTIVE' }), 5000)
  const drowsyAlerts = drowsyEvents.data?.events || []

  const driver = bus?.driver || {}
  const dState = useMemo(() => driverState(driver), [driver.state])

  return (
    <>
      <PageHeader
        title="Driver Safety Monitoring"
        sub="Eye-state monitoring · EAR / MAR / head pose · drowsiness assessment"
        right={<SimBadge />}
      />

      <CallAlert />

      <BusGrid buses={buses} selectedBusId={busId} onSelect={setBusId} />

      {error && <div className="card mb-16" style={{ color: 'var(--red)' }}>Bus not found: {busId}</div>}

      {bus && (
        <>
          <div className="grid grid-3 mb-16">
            <div className="card">
              <div className="card-header">
                <h3 className="card-title">Driver State</h3>
                <span className={`badge ${dState.tone}`}>{dState.label}</span>
              </div>
              <div className="gauge-wrap" style={{ padding: '16px 0' }}>
                <StatusBadge status={driver.state || 'NORMAL'} />
                <div className="muted" style={{ fontSize: 12 }}>{driver.name || 'Unknown'} · {bus.bus_id}</div>
              </div>
            </div>
            <div className="card">
              <div className="card-header"><h3 className="card-title">Eye Aspect Ratio</h3></div>
              <Gauge value={Math.round((driver.ear || 0) * 1000) / 1000} min={0} max={0.45} label="EAR · threshold 0.23" />
            </div>
            <div className="card">
              <div className="card-header"><h3 className="card-title">Mouth Aspect Ratio</h3></div>
              <Gauge value={Math.round((driver.mar || 0) * 1000) / 1000} min={0} max={0.8} label="MAR · threshold 0.40" />
            </div>
            <div className="card">
              <div className="card-header"><h3 className="card-title">Head Pose</h3></div>
              <Gauge value={Math.abs(driver.head_pitch_deg || 0)} min={0} max={20} unit="°" label="pitch (down = +)" />
            </div>
            <div className="card">
              <div className="card-header"><h3 className="card-title">Eye Closure</h3></div>
              <Gauge value={driver.closed_sec || 0} min={0} max={4} unit="s" label="continuous closure" color={driver.closed_sec > 1.3 ? 'var(--red)' : 'var(--green)'} />
            </div>
            <div className="card">
              <div className="card-header"><h3 className="card-title">Attention</h3></div>
              <Gauge value={driver.state === 'NORMAL' ? 100 : driver.state === 'ATTENTION' ? 60 : 20} unit="%" label="computed attention" />
            </div>
          </div>

          <div className="card mb-16">
            <div className="card-header">
              <h3 className="card-title">Live Driver Camera</h3>
              <span className="badge badge-green">LIVE</span>
            </div>
            <CameraGrid
              cams={{
                driver: { active: true, status: `LIVE · ${driver.state}`, meta: 'Driver webcam (bus node)' },
                cabin: { active: true, status: 'LIVE · CCTV', meta: 'Cabin camera · passengers & driver alert' },
                road: { active: true, status: 'LIVE', meta: 'Front road camera · pothole detection' },
              }}
            />
          </div>

          <div className="grid grid-2">
            <div className="card">
              <div className="card-header"><h3 className="card-title">Warning History — {bus.bus_id}</h3></div>
              {events.length === 0 ? (
                <div className="empty">No drowsiness warnings recorded for this bus.</div>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Time</th><th>Severity</th><th>Confidence</th><th>Status</th></tr></thead>
                    <tbody>
                      {events.slice(0, 12).map((e) => (
                        <tr key={e.event_id}>
                          <td>{new Date(e.timestamp).toLocaleTimeString()}</td>
                          <td><StatusBadge status={e.severity} /></td>
                          <td className="mono">{Math.round(e.confidence * 100)}%</td>
                          <td><StatusBadge status={e.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <AlertFeed events={drowsyAlerts} header="Current Drowsiness Alerts" />
          </div>
        </>
      )}
    </>
  )
}
