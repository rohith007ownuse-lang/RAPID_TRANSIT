import { useState, useEffect, useRef } from 'react'
import { useMode } from '../lib/modeContext.jsx'
import { api } from '../api.js'

/* ─── Metric Card ─── */
function MetricCard({ label, value, unit, status, statusColor, barPct, showBar = true }) {
  return (
    <div style={{
      background: '#fff', border: '1px solid #D9E0E7', borderRadius: 6,
      padding: '6px 8px', marginBottom: 4, minWidth: 150,
    }}>
      <div style={{ fontSize: 9, fontWeight: 700, color: '#66727E', fontFamily: 'monospace', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 3, marginTop: 2 }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: '#17212B', fontFamily: 'monospace' }}>{value}</span>
        {unit && <span style={{ fontSize: 9, color: '#66727E', fontFamily: 'monospace' }}>{unit}</span>}
      </div>
      <div style={{ fontSize: 8, color: statusColor || '#66727E', fontFamily: 'monospace', marginTop: 1 }}>
        {status}
      </div>
      {showBar && (
        <div style={{ background: '#D9E0E7', height: 3, borderRadius: 2, marginTop: 4, overflow: 'hidden' }}>
          <div style={{
            width: `${Math.max(0, Math.min(100, barPct || 0))}%`,
            height: '100%', background: statusColor || '#22A447', borderRadius: 2,
            transition: 'width 0.3s',
          }} />
        </div>
      )}
    </div>
  )
}

/* ─── Driver Left Panel: Real-Time Metrics (real DDS values only) ─── */
function DDSLeftPanel({ det, dds }) {
  const state = det.state || 'NORMAL'
  const ear = det.ear ?? 0
  const mar = det.mar ?? 0
  const closed = det.closed_sec ?? 0
  const perclos = det.perclos ?? 0
  const face = det.face_detected ?? false
  const pitch = det.head_pitch ?? det.pitch ?? 0
  const yawns = det.yawn_count ?? dds?.last?.yawn_count ?? 0
  const monitoring = dds?.monitoring ?? false

  // Real values only — show '—' until the engine actually produces data.
  const hasData = face || ear > 0
  const fmt = (v, digits = 3) => (hasData ? v.toFixed(digits) : '—')

  const fatiguePct = det.drowsy_percent ?? dds?.last?.drowsy_percent ?? null
  const attentionPct = det.attention_percent ?? dds?.last?.attention_percent ?? null
  const perclosPct = perclos ? Math.round(perclos * 100) : null
  const eyeClosure = fmt(closed, 2)
  const gaze = face ? 'Tracking' : hasData ? 'No face' : '—'

  const earThr = dds?.thresholds?.ear_threshold ?? det.ear_threshold ?? 0.23
  const marThr = dds?.thresholds?.mar_threshold ?? det.mar_threshold ?? 0.40

  const fatigueColor = fatiguePct >= 70 ? '#E53935' : fatiguePct >= 35 ? '#F5A623' : '#22A447'
  const attentionColor = attentionPct >= 70 ? '#22A447' : attentionPct >= 35 ? '#F5A623' : '#E53935'
  const perclosColor = perclosPct >= 50 ? '#E53935' : perclosPct >= 20 ? '#F5A623' : '#22A447'
  const eyeColor = closed > 1.3 ? '#E53935' : closed > 0.5 ? '#F5A623' : '#22A447'

  const fatigueWord = fatiguePct >= 70 ? 'Critical' : fatiguePct >= 35 ? 'Warning' : 'Normal'
  const attentionWord = attentionPct >= 70 ? 'Good' : attentionPct >= 35 ? 'Fair' : 'Poor'
  const perclosWord = perclosPct >= 50 ? 'Critical' : perclosPct >= 20 ? 'Warning' : 'Normal'
  const eyeWord = closed > 1.3 ? 'Drowsy' : closed > 0.5 ? 'Closing' : 'Open'

  return (
    <div style={{
      width: 180, minWidth: 180, background: '#F7F9FB', borderRight: '1px solid #D9E0E7',
      padding: '10px 8px', overflowY: 'auto', height: '100%',
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#66727E', fontFamily: 'monospace', marginBottom: 8 }}>
        Real-Time Metrics
      </div>

      <MetricCard label="EAR (Eye Ratio)" value={fmt(ear)} unit={`/ thr ${earThr.toFixed(2)}`} status={ear < earThr && hasData ? 'below threshold' : hasData ? 'normal' : '—'} statusColor={ear < earThr && hasData ? '#E53935' : '#22A447'} barPct={earThr ? (ear / earThr) * 100 : 0} />
      <MetricCard label="MAR (Mouth Ratio)" value={fmt(mar)} unit={`/ thr ${marThr.toFixed(2)}`} status={mar > marThr && hasData ? 'above threshold' : hasData ? 'normal' : '—'} statusColor={mar > marThr && hasData ? '#E53935' : '#22A447'} barPct={marThr ? (mar / marThr) * 100 : 0} />
      <MetricCard label="Head Pose" value={hasData ? `${pitch.toFixed(1)}°` : '—'} unit="pitch" status={Math.abs(pitch) > 15 && hasData ? 'deviation' : hasData ? 'normal' : '—'} statusColor={Math.abs(pitch) > 15 && hasData ? '#F5A623' : '#22A447'} showBar={false} />
      <MetricCard label="Eye Closure" value={eyeClosure} unit="s" status={monitoring ? eyeWord : 'engine idle'} statusColor={monitoring ? eyeColor : '#66727E'} showBar={false} />
      <MetricCard label="PERCLOS" value={perclosPct != null ? `${perclosPct}%` : '—'} unit="60s" status={monitoring ? perclosWord : 'engine idle'} statusColor={monitoring ? perclosColor : '#66727E'} barPct={perclosPct || 0} />
      <MetricCard label="Fatigue" value={fatiguePct != null ? `${fatiguePct}%` : '—'} unit="%" status={fatigueWord} statusColor={fatigueColor} barPct={fatiguePct || 0} />
      <MetricCard label="Attention" value={attentionPct != null ? `${attentionPct}%` : '—'} unit="%" status={attentionWord} statusColor={attentionColor} barPct={attentionPct || 0} />
      <MetricCard label="Yawns" value={monitoring ? `${yawns}` : '—'} status={monitoring ? 'this session' : 'engine idle'} statusColor="#66727E" showBar={false} />
      <MetricCard label="Gaze" value={gaze} status={monitoring ? 'face tracking' : 'engine idle'} statusColor="#66727E" showBar={false} />
    </div>
  )
}

/* ─── Driver Right Panel: Driver Status (real values from DDS engine) ─── */
function DriverStatusPanel({ det, alertHistory, dds }) {
  const state = det.state || 'NORMAL'
  const severity = det.severity || 'NONE'
  const monitoring = dds?.monitoring ?? false
  const phase = dds?.phase || 'idle'
  const audioOk = dds?.audio?.enabled ?? false
  const audioTrig = dds?.audio?.triggered ?? 0
  const events = dds?.events_emitted ?? 0
  const mono = dds?.monitoring_seconds ?? 0

  const fmt = (v, digits = 2) => (v != null && v > 0 ? v.toFixed(digits) : '—')

  return (
    <div style={{
      width: 270, minWidth: 270, background: '#F7F9FB', borderLeft: '1px solid #D9E0E7',
      padding: '10px 12px', overflowY: 'auto', height: '100%',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 8 }}>
        <span style={{ color: severity === 'CRITICAL' ? '#E53935' : severity === 'WARNING' ? '#F5A623' : '#22A447', fontSize: 10, fontWeight: 700 }}>▲</span>
        <span style={{ fontSize: 10, fontWeight: 700, color: severity === 'CRITICAL' ? '#E53935' : '#17212B', fontFamily: 'monospace' }}>Driver Status</span>
      </div>

      <div style={{ fontSize: 8, fontWeight: 700, color: '#66727E', fontFamily: 'monospace', marginBottom: 4 }}>System Info</div>
      <div style={{
        background: '#fff', border: '1px solid #D9E0E7', borderRadius: 4,
        padding: 8, fontSize: 8, color: '#17212B', fontFamily: 'monospace', marginBottom: 10, lineHeight: 1.6,
      }}>
        • Camera: Active (driver slot)<br />
        • Audio warning: {audioOk ? 'ACTIVE' : 'unavailable'} · triggered {audioTrig}x<br />
        • Live events emitted: {events}<br />
        • Monitoring: {monitoring ? `active · ${fmt(mono, 0)}s` : phase}
      </div>

      <div style={{
        fontSize: 8, fontFamily: 'monospace', marginBottom: 10,
        color: severity === 'CRITICAL' ? '#E53935' : severity === 'WARNING' ? '#F5A623' : '#22A447',
      }}>
        {state === 'NORMAL' ? 'All systems operational' : `${state} [${severity}]`}
      </div>

      <div style={{ fontSize: 10, fontWeight: 700, color: '#17212B', fontFamily: 'monospace', marginBottom: 6 }}>
        Recent Summary
      </div>
      <div style={{
        background: '#fff', border: '1px solid #D9E0E7', borderRadius: 4,
        padding: 8, fontSize: 8, fontFamily: 'monospace',
      }}>
        {[
          { label: 'Eye Closures', value: alertHistory.eyeClosures },
          { label: 'Yawns', value: det.yawn_count ?? dds?.last?.yawn_count ?? 0 },
          { label: 'Fatigue Alerts', value: alertHistory.fatigueAlerts },
          { label: 'Avg Attention', value: `${alertHistory.avgAttention}%` },
          { label: 'PERCLOS Avg', value: `${alertHistory.perclosAvg}%` },
        ].map(({ label, value }) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid #F0F0F0' }}>
            <span style={{ color: '#66727E' }}>{label}</span>
            <span style={{ color: '#17212B', fontWeight: 600 }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── Camera Tile ─── */
function CameraTile({ label, slot, active, status, frame }) {
  const imgRef = useRef(null)

  useEffect(() => {
    if (frame && imgRef.current) {
      imgRef.current.src = `data:image/jpeg;base64,${frame}`
    }
  }, [frame])

  return (
    <div className="camera-tile">
      <div className="camera-view">
        <span className="camera-label">{label}</span>
        {active && frame ? (
          <div style={{ textAlign: 'center' }}>
            <img ref={imgRef} alt={`${slot} camera`}
              style={{ width: '100%', maxHeight: 300, objectFit: 'contain', borderRadius: 4 }} />
          </div>
        ) : active ? (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>📷</div>
            <div style={{ fontWeight: 600 }}>CAMERA CONNECTED</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Waiting for frames...</div>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <div style={{ fontSize: 40, marginBottom: 8, opacity: 0.6 }}>📷</div>
            <div style={{ fontWeight: 600 }}>CAMERA OFFLINE</div>
          </div>
        )}
      </div>
      <div className="camera-footer">
        <span>
          {active ? <span className="live-dot" /> : <span className="dot dot-grey" />}
          {active ? status : 'OFFLINE'}
        </span>
        <span>{active ? 'stream active' : 'not connected'}</span>
      </div>
    </div>
  )
}

/* ─── Minimal Camera Control Panel (operator-facing, simplified) ─── */
export function CameraControlPanel() {
  const { isLive } = useMode()
  if (!isLive) return null
  // The camera is auto-started in live mode; no operator controls needed here.
  return null
}

/* ─── Per-camera status strip (Phase 6 multi-camera: honest per-slot state) ─── */
function LiveCameraStatusStrip() {
  const { isLive } = useMode()
  const [statuses, setStatuses] = useState(null)

  useEffect(() => {
    if (!isLive) return
    let alive = true
    const load = async () => {
      try {
        const data = await api.cameraStatus()
        if (!alive) return
        setStatuses(data.slots || {})
      } catch (e) {
        console.error('Failed to fetch camera status:', e)
      }
    }
    load()
    const interval = setInterval(load, 3000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive])

  if (!isLive) return null

  const slots = [
    { key: 'driver', label: 'Driver' },
    { key: 'cabin', label: 'Cabin' },
    { key: 'road', label: 'Road' },
  ]
  const color = {
    CONNECTED: '#22A447',
    DISCONNECTED: '#66727E',
    DISABLED: '#66727E',
    STARTING: '#F5A623',
    ERROR: '#E53935',
  }

  return (
    <div className="camera-grid" style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
      {slots.map(({ key, label }) => {
        const s = (statuses && statuses[key]) || {}
        const c = color[s.status] || '#66727E'
        const meta =
          s.status === 'CONNECTED'
            ? [
                s.resolution ? `${s.resolution}` : 'res —',
                s.fps != null ? `${s.fps} fps` : 'fps —',
              ].join(' · ')
            : s.status === 'DISABLED'
              ? 'disabled via config'
              : s.status === 'ERROR'
                ? 'camera error'
                : 'no camera feed'
        return (
          <div key={key} style={{
            background: '#fff', border: `1px solid ${c}`,
            borderRadius: 6, padding: '7px 10px', flex: 1, minWidth: 150,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 10, fontWeight: 700, fontFamily: 'monospace', color: '#17212B' }}>{label}</span>
              <span className={s.status === 'CONNECTED' ? 'live-dot' : 'dot dot-grey'} />
            </div>
            <div style={{ fontSize: 10, fontWeight: 700, color: c, fontFamily: 'monospace', marginTop: 3 }}>{s.status || '—'}</div>
            <div style={{ fontSize: 9, color: '#66727E', fontFamily: 'monospace', marginTop: 2 }}>{meta}</div>
            {s.camera_id && (
              <div style={{ fontSize: 8, color: '#8A94A0', fontFamily: 'monospace', marginTop: 2 }}>
                {s.camera_id} · bus {s.bus_id}
              </div>
            )}
            {key === 'cabin' && <CabinOccupancyLine />}
          </div>
        )
      })}
    </div>
  )
}

/* ─── Cabin occupancy line on the Cabin status card (Phase 7) ───
   Shows a real estimate only when it exists; never shows 0 for unknown. */
function CabinOccupancyLine() {
  const { isLive } = useMode()
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!isLive) return
    let alive = true
    const load = async () => {
      try {
        const d = await api.cabinOccupancy()
        if (alive) setData(d)
      } catch (e) {
        console.error('Failed to fetch cabin occupancy:', e)
      }
    }
    load()
    const interval = setInterval(load, 3000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive])

  if (!isLive || !data) return null

  const occ = data.occupancy_count
  const status = data.status
  const pct = data.occupancy_percentage
  const crowd = data.crowding_level

  let text, color
  if (status === 'CONNECTED' && occ != null) {
    text = `Occupancy: ${pct}% · ${crowd}`
    color = '#17212B'
  } else if (status === 'CONNECTED') {
    text = 'No valid estimate yet'
    color = '#8A94A0'
  } else {
    text = 'Camera unavailable'
    color = '#8A94A0'
  }

  return (
    <div style={{ fontSize: 9, color, fontFamily: 'monospace', marginTop: 2 }}>
      {text}
    </div>
  )
}

/* ─── Cabin Intelligence panel (Phase 7) ───
   Rendered in live mode under the camera grid. 'unknown' is displayed as '—',
   never as 0 passengers. Confidence is shown only when genuinely provided
   (the heuristic estimator has none; a real cabin model would). */
function CabinIntelligencePanel() {
  const { isLive } = useMode()
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!isLive) return
    let alive = true
    const load = async () => {
      try {
        const d = await api.cabinOccupancy()
        if (alive) setData(d)
      } catch (e) {
        console.error('Failed to fetch cabin intelligence:', e)
      }
    }
    load()
    const interval = setInterval(load, 3000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive])

  if (!isLive) return null

  const status = data?.status || 'UNAVAILABLE'
  const connected = status === 'CONNECTED'
  const occ = data?.occupancy_count
  const showOcc = connected && occ != null
  const pct = showOcc ? data.occupancy_percentage : null
  const crowd = showOcc ? data.crowding_level : null
  const estText = connected && showOcc ? `${occ}/${data.capacity}` : '—'
  const sourceText = connected
    ? `Cabin Camera${data.estimator === 'heuristic' ? ' (heuristic estimator)' : ''}`
    : 'Camera unavailable'
  const confText = data.confidence != null ? `${Math.round(data.confidence * 100)}%` : '—'
  const statusColor = connected ? '#22A447' : status === 'ERROR' ? '#E53935' : '#8A94A0'

  const rows = [
    { label: 'Bus', value: data?.bus_id || 'PROTO-001', mono: true },
    { label: 'Camera', value: data?.camera_id || '—', mono: true },
    { label: 'Status', value: status, color: statusColor },
    { label: 'Occupancy', value: showOcc ? `${pct}% (${estText})` : '—', mono: true },
    { label: 'Crowding', value: crowd || '—' },
    { label: 'Source', value: sourceText },
    { label: 'Confidence', value: connected ? confText : '—' },
  ]

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <h3 className="card-title">Cabin Intelligence</h3>
        {connected ? (
          <span className="badge badge-green">CABIN CAMERA</span>
        ) : (
          <span className="badge" style={{ background: statusColor }}>{status}</span>
        )}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {rows.map((r) => (
          <div key={r.label} style={{ minWidth: 170, flex: 1 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: '#66727E', fontFamily: 'monospace', textTransform: 'uppercase' }}>
              {r.label}
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: r.color || '#17212B', fontFamily: 'monospace', marginTop: 2 }}>
              {r.value}
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 9, color: '#8A94A0', fontFamily: 'monospace', marginTop: 10 }}>
        Estimator: {data?.estimator_in_use || 'heuristic (development)'} · Source: camera (simulation: false) ·
        {status !== 'CONNECTED' ? ' occupancy unknown (never reported as 0)' : ''} ·
        aggregate-only; frames discarded after inference
      </div>
    </div>
  )
}

/* ─── PROTO-001 Live Event Feed (existing FLEET-IQ event system) ─── */
export function ProtoEventFeed({ limit = 6 }) {
  const { isLive } = useMode()
  const [events, setEvents] = useState([])

  useEffect(() => {
    if (!isLive) return
    let alive = true
    const fetchEvents = async () => {
      try {
        const data = await api.events({ data_source: 'live' })
        if (!alive) return
        const proto = (data.events || []).filter((e) => e.bus_id === 'PROTO-001')
        setEvents(proto.slice(0, limit))
      } catch (e) {
        console.error('Failed to fetch prototype events:', e)
      }
    }
    fetchEvents()
    const interval = setInterval(fetchEvents, 3000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive, limit])

  if (!isLive) return null

  const sevColor = { CRITICAL: '#E53935', WARNING: '#F5A623', INFO: '#66727E', NONE: '#22A447' }

  return (
    <div className="card card-live" style={{ marginTop: 16 }}>
      <div className="card-header">
        <h3 className="card-title">Live Event Feed — 70V</h3>
        <span className="badge badge-green">DDS → FLEET-IQ EVENTS</span>
      </div>
      {events.length === 0 ? (
        <div className="empty" style={{ fontSize: 12 }}>
          Driver monitoring active · no alerts yet — drowsiness events from the DDS engine appear here.
        </div>
      ) : (
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          {events.map((e) => (
            <div key={e.event_id} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              borderBottom: '1px solid #F0F0F0', fontSize: 12,
            }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: sevColor[e.severity] || '#66727E', flexShrink: 0 }} />
              <span style={{ fontWeight: 600, flexShrink: 0 }}>{e.event_type}</span>
              <span className="badge" style={{ background: sevColor[e.severity] || '#66727E', color: '#fff', fontSize: 9 }}>{e.severity}</span>
              <span className="muted" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11 }}>
                {e.additional_data?.note || ''}
              </span>
              <span className="muted mono" style={{ fontSize: 10, flexShrink: 0 }}>
                {new Date(e.timestamp).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ─── DDS Subprocess + Logs console (original DDS project) ─── */
function DdsConsole() {
  const { isLive } = useMode()
  const [proc, setProc] = useState(null)
  const [logs, setLogs] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try { setProc(await api.ddsSubprocess()) } catch (e) {}
    try { setLogs(await api.ddsLogs()) } catch (e) {}
  }

  useEffect(() => {
    if (!isLive) return
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [isLive])

  const procAct = async (fn) => {
    setBusy(true)
    try { await fn(); await load() } catch (e) { console.error('DDS subprocess action failed:', e) }
    setBusy(false)
  }

  if (!isLive) return null

  const fmtTime = (s) => (s ? new Date(s).toLocaleString() : '—')

  return (
    <div className="card card-live" style={{ marginTop: 16 }}>
      <div className="card-header">
        <h3 className="card-title">Original DDS — Subprocess & Session Logs</h3>
        <span className={proc?.available ? 'badge badge-green' : 'badge'}>
          {proc?.available ? 'DDS PROJECT FOUND' : 'DDS PROJECT NOT ON THIS MACHINE'}
        </span>
      </div>

      <div className="flex gap-8 mt-16 wrap align-center">
        <span className="chip" style={{ margin: 0 }}>status: <strong>{proc?.status ?? '…'}</strong></span>
        <span className="chip" style={{ margin: 0 }}>pid: <strong>{proc?.pid ?? '—'}</strong></span>
        <span className="chip" style={{ margin: 0 }}>uptime: <strong>{proc?.uptime ?? 0}s</strong></span>
        <span style={{ flex: 1 }} />
        <button
          className="btn btn-sm"
          disabled={busy || proc?.running}
          onClick={() => procAct(api.ddsSubprocessStart)}
          style={{ fontSize: 10 }}
        >
          ▶ LAUNCH DDS WINDOW
        </button>
        <button
          className="btn btn-sm btn-ghost"
          disabled={busy || !proc?.running}
          onClick={() => procAct(api.ddsSubprocessStop)}
          style={{ fontSize: 10 }}
        >
          ■ STOP SUBPROCESS
        </button>
      </div>

      {logs?.summary && (
        <div className="mt-16">
          <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Latest DDS session summary — {fmtTime(logs.summary.timestamp)}</div>
          <pre style={{ background: '#F7F9FB', border: '1px solid #D9E0E7', borderRadius: 4, padding: 8, fontSize: 10, lineHeight: 1.6, whiteSpace: 'pre-wrap', maxHeight: 180, overflowY: 'auto' }}>
            {logs.summary.content}
          </pre>
        </div>
      )}

      {!logs?.summary && logs?.available !== false && (
        <div className="muted mt-16" style={{ fontSize: 11 }}>
          No DDS session summary yet — run a monitoring session in the original DDS to populate its logs.
        </div>
      )}
    </div>
  )
}

/* ─── Live Camera Grid with Driver 3-Panel Layout ─── */
export function LiveCameraGrid() {
  const { isLive } = useMode()
  const [frame, setFrame] = useState(null)
  const [detections, setDetections] = useState({})
  const [dds, setDds] = useState(null)
  const [activeSlot, setActiveSlot] = useState('driver')
  const [busy, setBusy] = useState(false)
  const [alertHistory, setAlertHistory] = useState({
    eyeClosures: 0, yawns: 0, fatigueAlerts: 0, avgAttention: 95, perclosAvg: 0,
  })
  const prevState = useRef('NORMAL')

  useEffect(() => {
    if (!isLive) return

    const fetchData = async () => {
      try {
        const status = await api.cameraStatus()
        const slot = status.test_slot || 'driver'
        setActiveSlot(slot)

        const data = await api.cameraStream(slot)
        setFrame(data.frame)
        setDetections(data.detections || {})

        const det = data.detections || {}
        const currentState = det.state || 'NORMAL'
        if (currentState !== 'NORMAL' && prevState.current === 'NORMAL') {
          setAlertHistory(prev => ({
            ...prev,
            eyeClosures: prev.eyeClosures + (det.closed_sec > 0 ? 1 : 0),
            fatigueAlerts: prev.fatigueAlerts + (currentState === 'DROWSY' ? 1 : 0),
          }))
        }
        prevState.current = currentState

        setAlertHistory(prev => ({
          ...prev,
          avgAttention: currentState === 'NORMAL' ? 95 : currentState === 'ATTENTION' ? 60 : 20,
          perclosAvg: Math.round((det.perclos || 0) * 100),
        }))
      } catch (e) {
        console.error('Failed to fetch camera data:', e)
      }
    }

    const fetchDds = async () => {
      try {
        const data = await api.ddsStatus()
        setDds(data)
      } catch (e) {
        console.error('Failed to fetch DDS status:', e)
      }
    }

    fetchData()
    fetchDds()
    // 1 s polling keeps the live feed smooth; the JPEG is ~60 KB over localhost.
    const interval = setInterval(() => { fetchData(); fetchDds() }, 1000)
    return () => clearInterval(interval)
  }, [isLive])

  const act = async (fn) => {
    setBusy(true)
    try {
      await fn()
      const data = await api.ddsStatus()
      setDds(data)
    } catch (e) {
      console.error('DDS action failed:', e)
    }
    setBusy(false)
  }

  if (!isLive) return null

  const isDriver = activeSlot === 'driver'

  if (isDriver) {
    return (
      <>
        <div style={{
          display: 'flex', border: '1px solid #D9E0E7', borderRadius: 8,
          overflow: 'hidden', background: '#fff', minHeight: 420,
        }}>
          <DDSLeftPanel det={detections} dds={dds} />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{
            padding: '8px 12px', borderBottom: '1px solid #D9E0E7',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#17212B' }}>
              Driver Status — 70V
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="badge badge-green">LIVE</span>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => act(api.ddsCalibrate)}
                disabled={busy}
                title="Start 5 s personal-baseline calibration (face in frame)"
                style={{ fontSize: 10, padding: '2px 8px' }}
              >
                ◎ CALIBRATE
              </button>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => act(api.ddsStart)}
                disabled={busy}
                title="Start real DDS monitoring (uses calibrated thresholds)"
                style={{ fontSize: 10, padding: '2px 8px' }}
              >
                ▶ MONITOR
              </button>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => act(api.ddsStop)}
                disabled={busy}
                title="Stop DDS monitoring (audio warning silenced, camera stays on)"
                style={{ fontSize: 10, padding: '2px 8px' }}
              >
                ■ STOP
              </button>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => act(api.ddsReset)}
                disabled={busy}
                title="Reset driver monitoring"
                style={{ fontSize: 10, padding: '2px 8px' }}
              >
                ↺ RESET
              </button>
            </div>
          </div>
          <div style={{ flex: 1, padding: 8 }}>
            <CameraTile
              label="DRIVER — DROWSINESS"
              slot="driver"
              active={true}
              status="ACTIVE"
              frame={frame}
            />
          </div>
        </div>
        <DriverStatusPanel det={detections} alertHistory={alertHistory} dds={dds} />
      </div>
      <DdsConsole />
      </>
    )
  }

  // Road / Cabin: camera feed only
  return (
    <div style={{
      display: 'flex', border: '1px solid #D9E0E7', borderRadius: 8,
      overflow: 'hidden', background: '#fff', minHeight: 420,
    }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{
          padding: '8px 12px', borderBottom: '1px solid #D9E0E7',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#17212B' }}>
            {activeSlot === 'road' ? 'Road Status' : 'Cabin Status'}
          </span>
          <span className="badge badge-green">LIVE</span>
        </div>
        <div style={{ flex: 1, padding: 8 }}>
          <CameraTile
            label={activeSlot === 'road' ? 'ROAD — POTHOLE' : 'CABIN — MONITORING'}
            slot={activeSlot}
            active={true}
            status="ACTIVE"
            frame={frame}
          />
        </div>
      </div>
    </div>
  )
}

/* ─── Simulation Camera Grid ─── */
export function SimulationCameraGrid() {
  return (
    <div className="camera-grid">
      <div className="camera-main">
        <CameraTile label="DRIVER — DROWSINESS" active={false} status="SIMULATION" />
      </div>
      <div className="camera-row">
        <CameraTile label="CABIN — MONITORING" active={false} status="SIMULATION" />
        <CameraTile label="ROAD — POTHOLE" active={false} status="SIMULATION" />
      </div>
    </div>
  )
}

export default function CameraGrid() {
  const { isLive } = useMode()
  if (isLive) return (
    <>
      <LiveCameraStatusStrip />
      <LiveCameraGrid />
      <CabinIntelligencePanel />
    </>
  )
  return <SimulationCameraGrid />
}
