import { useState, useEffect, useRef } from 'react'
import { useMode } from '../lib/modeContext.jsx'
import { useAuth } from '../lib/authContext.jsx'
import { api } from '../api.js'
import { wsUrl } from '../websocket.js'

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
function CameraTile({ label, slot, active, status, frame, fillParent, error }) {
  const imgRef = useRef(null)

  useEffect(() => {
    if (frame && imgRef.current) {
      imgRef.current.src = `data:image/jpeg;base64,${frame}`
    }
  }, [frame])

  return (
    <div className="camera-tile" style={fillParent ? { height: '100%', minHeight: 0 } : undefined}>
      <div className="camera-view">
        <span className="camera-label">{label}</span>
        {active && frame ? (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <img ref={imgRef} alt={`${slot} camera`}
              style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: 4 }} />
          </div>
        ) : active ? (
          <div style={{ textAlign: 'center', padding: 20, maxWidth: 420 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>📷</div>
            <div style={{ fontWeight: 600 }}>CAMERA CONNECTED</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Waiting for frames...</div>
            {error && (
              <div style={{ fontSize: 11, marginTop: 8, color: '#b45309', background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 6, padding: '6px 8px', wordBreak: 'break-word' }}>
                {error}
              </div>
            )}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <div style={{ fontSize: 40, marginBottom: 8, opacity: 0.6 }}>📷</div>
            <div style={{ fontWeight: 600 }}>CAMERA OFFLINE</div>
            {error && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{error}</div>}
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

/* ─── Demo placeholder "photo" (inline SVG) for the cabin / outside cameras ─── */
function CameraScene({ kind }) {
  return (
    <svg width="100%" height="100%" viewBox="0 0 320 200" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
      {kind === 'cabin' ? (
        <g>
          <rect width="320" height="200" fill="#dce5ee" />
          <rect y="148" width="320" height="52" fill="#7e92a8" />
          <rect width="320" height="26" fill="#b7c5d4" />
          {[12, 88, 164, 240].map((x) => (
            <g key={x}>
              <rect x={x} y="44" width="56" height="96" rx="6" fill="#d8e7f6" stroke="#a7b6c6" strokeWidth="3" />
              <line x1={x + 28} y1="44" x2={x + 28} y2="140" stroke="#a7b6c6" strokeWidth="3" />
            </g>
          ))}
          {[52, 128, 204, 280].map((x) => (
            <g key={x}>
              <rect x={x - 14} y="150" width="40" height="26" rx="4" fill="#2f6fb2" />
              <rect x={x - 30} y="170" width="34" height="12" rx="3" fill="#265c92" />
            </g>
          ))}
          <circle cx="300" cy="22" r="6" fill="#f59e0b" />
        </g>
      ) : (
        <g>
          <rect width="320" height="200" fill="#cddbe8" />
          <rect y="110" width="320" height="62" fill="#3b4a5a" />
          <rect y="112" width="320" height="12" fill="#6d8299" />
          <rect y="62" width="320" height="14" fill="#9db7d1" />
          <rect x="0" y="176" width="320" height="24" fill="#2e3c4b" />
          {[8, 44, 80, 116, 152, 188, 224, 260, 296].map((x) => (
            <rect key={x} x={x} y="128" width="18" height="2" rx="1" fill="#e3eaf1" />
          ))}
          <circle cx="244" cy="150" r="17" fill="#111827" />
          <polygon points="198,142 204,116 210,142" fill="#f59e0b" />
          <polygon points="188,126 198,106 208,124" fill="#b91c1c" />
          <rect x="0" y="118" width="320" height="3" fill="#e3eaf1" />
        </g>
      )}
    </svg>
  )
}

/* ─── Cabin / Outside mini-tile (click → big lightbox) ─── */
function CameraMiniTile({ slot, mode, label, onExpand }) {
  return (
    <div className="camera-tile" onClick={onExpand} style={{ cursor: 'pointer', minHeight: 220 }}>
      <div className="camera-view" style={{ position: 'relative' }}>
        <CameraScene kind={slot} />
        <span className="camera-label">{label}</span>
        <span
          style={{
            position: 'absolute', right: 10, bottom: 10, background: 'rgba(15,23,42,0.7)',
            color: '#fff', borderRadius: 6, padding: '3px 8px', fontSize: 11, fontWeight: 600,
          }}
        >
          ⛶ enlarge
        </span>
      </div>
      <div className="camera-footer">
        <span>
          <span className={mode === 'live' ? 'live-dot' : 'dot dot-blue'} />
          {mode === 'live' ? 'LIVE' : 'ESTIMATED'}
        </span>
        <span>click to enlarge</span>
      </div>
    </div>
  )
}

/* ─── Big pop-up view of a selected camera (demo scene) ─── */
function CameraLightbox({ slot, label, onClose }) {
  return (
    <div
      className="camera-lightbox"
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(15,23,42,0.72)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div
        className="camera-lightbox-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#fff', borderRadius: 10, padding: 16, width: 'min(1000px, 94vw)',
          boxShadow: '0 18px 60px rgba(0,0,0,0.4)',
        }}
      >
        <div className="flex justify-between align-center mb-8">
          <strong style={{ fontSize: 14 }}>{label}</strong>
          <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={onClose}>✕ Close</button>
        </div>
        <div style={{ position: 'relative', height: '70vh', minHeight: 320, borderRadius: 8, overflow: 'hidden' }}>
          <CameraScene kind={slot} />
          <div className="camera-label">📸 {label} — demo placeholder image</div>
        </div>
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
  const isRealCount = data.estimator === 'ml-person-detector'
  const sourceText = connected
    ? `Cabin Camera${data.estimator === 'heuristic' ? ' (heuristic estimator)' : isRealCount ? ' (AI person count)' : ''}`
    : 'Camera unavailable'
  const confText = data?.confidence != null ? `${Math.round(data.confidence * 100)}%` : '—'
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
        Estimator: {data?.estimator_in_use || 'heuristic (development)'} · Source: camera ·
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
        <span className="badge badge-green">DDS → RAPID TRACKER EVENTS</span>
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

/* ─── Live Camera Grid with Driver 3-Panel Layout ─── */
export function LiveCameraGrid() {
  const { isLive } = useMode()
  const { token } = useAuth()
  const [frame, setFrame] = useState(null)
  const [detections, setDetections] = useState({})
  const [dds, setDds] = useState(null)
  const [selectedSlot, setSelectedSlot] = useState('driver')
  const [cabinData, setCabinData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [cameraFps, setCameraFps] = useState(0)
  const [wsConnected, setWsConnected] = useState(false)
  const [camError, setCamError] = useState(null)
  const [slotStatuses, setSlotStatuses] = useState({})
  const [alertHistory, setAlertHistory] = useState({
    eyeClosures: 0, yawns: 0, fatigueAlerts: 0, avgAttention: 95, perclosAvg: 0,
  })
  const prevState = useRef('NORMAL')
  const initialSlotDone = useRef(false)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  // Smoothness throttles: pixels repaint at up to 30 fps (backend now
  // delivers fresh frames at camera rate), metric panels and detection
  // lists at 4 Hz — full 30 Hz panel re-renders jank the page.
  const lastFrameAt = useRef(0)
  const lastDetAt = useRef(0)

  // WebSocket camera streaming (30 FPS)
  useEffect(() => {
    if (!isLive) return

    let ws = null
    let alive = true

    const connectWs = () => {
      if (!alive) return
      
      const wsUrlResolved = wsUrl('/', 8766)
      ws = new WebSocket(wsUrlResolved)
      wsRef.current = ws

      ws.onopen = () => {
        if (!alive) return
        console.log('[CameraWS] Connected')
        setWsConnected(true)
        // Subscribe to camera slot (token required when the API enforces
        // authenticated reads — camera frames are live driver/cabin imagery)
        ws.send(JSON.stringify({ type: 'subscribe_camera', slot: selectedSlot, token }))
      }

      ws.onmessage = (event) => {
        if (!alive) return
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'camera_frame') {
            // Ignore frames for a previously-selected slot arriving late.
            if (data.slot && data.slot !== selectedSlot) return
            const now = performance.now()
            // Pixels: repaint at up to 30 fps to match the video stream.
            if (data.frame && now - lastFrameAt.current >= 33) {
              lastFrameAt.current = now
              setFrame(data.frame)
            } else if (!data.frame) {
              setFrame(data.frame)
            }
            // Metrics + detection lists: 4 Hz is plenty for EAR/MAR/crowd
            // readouts and avoids re-rendering the side panels 30x/sec.
            const detAccepted = now - lastDetAt.current >= 250
            if (detAccepted) {
              lastDetAt.current = now
              setDetections(data.detections || {})
              if (data.fps) setCameraFps(data.fps)
            }
            // Surface backend capture errors instead of hanging on "Waiting...".
            if (data.frame) setCamError(null)
            else if (data.error) setCamError(data.error)

            // Track driver state for alerts (same 4 Hz gate — updating these
            // counters 30x/sec re-renders the status panels needlessly).
            if (selectedSlot === 'driver' && detAccepted) {
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
            }
          } else if (data.type === 'camera_subscribed') {
            console.log(`[CameraWS] Subscribed to ${data.slot}`)
          } else if (data.type === 'camera_error') {
            console.error('[CameraWS] Error:', data.reason)
            setCamError(data.reason)
          }
        } catch (e) {
          console.error('[CameraWS] Parse error:', e)
        }
      }

      ws.onclose = () => {
        if (!alive) return
        console.log('[CameraWS] Disconnected, reconnecting in 2s...')
        setWsConnected(false)
        reconnectTimer.current = setTimeout(connectWs, 2000)
      }

      ws.onerror = (err) => {
        console.error('[CameraWS] Error:', err)
      }
    }

    connectWs()

    return () => {
      alive = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (ws) {
        ws.onclose = null // prevent reconnect on cleanup
        ws.close()
      }
    }
  }, [isLive, selectedSlot, token])

  // Fetch DDS status separately (every 1s)
  useEffect(() => {
    if (!isLive || selectedSlot !== 'driver') return
    let alive = true
    const fetchDds = async () => {
      try {
        const data = await api.ddsStatus()
        if (alive) setDds(data)
      } catch (e) { /* ignore */ }
    }
    fetchDds()
    const interval = setInterval(fetchDds, 1000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive, selectedSlot])

  // Fetch cabin occupancy separately (every 3s)
  useEffect(() => {
    if (!isLive || selectedSlot !== 'cabin') return
    let alive = true
    const fetchOcc = async () => {
      try {
        const occ = await api.cabinOccupancy()
        if (alive) setCabinData(occ)
      } catch (e) { /* ignore */ }
    }
    fetchOcc()
    const interval = setInterval(fetchOcc, 3000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive, selectedSlot])

  // Poll per-slot camera status so cabin/road show honest state, not a guess.
  useEffect(() => {
    if (!isLive) return
    let alive = true
    const load = async () => {
      try {
        const st = await api.cameraStatus()
        if (alive) setSlotStatuses(st.slots || st.cameras || {})
      } catch (e) { /* ignore transient poll errors */ }
    }
    load()
    const id = setInterval(load, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [isLive])

  const switchSlot = async (slot) => {
    if (slot === selectedSlot || busy) return
    setBusy(true)
    setCamError(null)
    setFrame(null)
    lastFrameAt.current = 0
    lastDetAt.current = 0
    try {
      const res = await api.setTestMode(slot)
      if (res && res.success === false) {
        setCamError(res.message || `Camera for '${slot}' failed to start`)
      }
      setSelectedSlot(slot)
      setCabinData(null)
      const data = await api.cameraStream(slot)
      setFrame(data.frame)
      setDetections(data.detections || {})
      if (!data.frame) {
        try {
          const st = await api.cameraStatus()
          const s = (st.slots || {})[slot] || {}
          setCamError(s.error || s.status || `No frames from '${slot}' yet`)
          setSlotStatuses(st.slots || st.cameras || {})
        } catch (e) { /* ignore */ }
      }
    } catch (e) {
      console.error('Camera switch failed:', e)
      setCamError(e.message || 'Camera switch failed (auth/network?)')
    }
    setBusy(false)
  }

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

  const [lightbox, setLightbox] = useState(null)

  if (!isLive) return null

  return (
    <>
      <div className="camera-grid" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Camera status bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 12px', background: wsConnected ? '#dcfce7' : '#fef3c7', borderRadius: 8, border: `1px solid ${wsConnected ? '#16a34a' : '#f59e0b'}` }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: wsConnected ? '#166534' : '#92400e', fontFamily: 'monospace' }}>
            {wsConnected ? '● CONNECTED' : '○ CONNECTING...'}
          </span>
          {wsConnected && (
            <span style={{ fontSize: 11, color: '#166534', fontFamily: 'monospace' }}>
              {cameraFps} FPS · WebSocket Stream
            </span>
          )}
          {!wsConnected && (
            <span style={{ fontSize: 11, color: '#92400e', fontFamily: 'monospace' }}>
              Attempting WebSocket connection on port 8766...
            </span>
          )}
        </div>

        {/* Manual camera switcher */}
        <div className="filter-row" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {[
            { key: 'driver', label: '🎥 DRIVER' },
            { key: 'cabin', label: '🚌 CABIN' },
            { key: 'road', label: '🛣️ ROAD / POTHOLE' },
          ].map((c) => (
            <button
              key={c.key}
              className={`seg ${selectedSlot === c.key ? 'active' : ''}`}
              onClick={() => switchSlot(c.key)}
              disabled={busy}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Driver — big 3-panel DDS view */}
        {selectedSlot === 'driver' && (
        <div style={{
          display: 'flex', border: '1px solid #D9E0E7', borderRadius: 8,
          overflow: 'hidden', background: '#fff', minHeight: 420,
        }}>
          <DDSLeftPanel det={detections} dds={dds} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <div style={{
              padding: '8px 12px', borderBottom: '1px solid #D9E0E7',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6,
            }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#17212B' }}>
                Driver Status — 70V
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
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
            <div style={{ flex: 1, padding: 8, display: 'flex', flexDirection: 'column' }}>
              <CameraTile
                label="DRIVER — DROWSINESS"
                slot="driver"
                active={true}
                status="ACTIVE"
                frame={frame}
                fillParent
                error={camError}
              />
            </div>
          </div>
          <DriverStatusPanel det={detections} alertHistory={alertHistory} dds={dds} />
        </div>
        )}

        {/* Cabin — main panel */}
        {selectedSlot === 'cabin' && (
          <div style={{ display: 'flex', border: '1px solid #D9E0E7', borderRadius: 8, overflow: 'hidden', background: '#fff', minHeight: 420 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <div style={{ padding: '8px 12px', borderBottom: '1px solid #D9E0E7', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#17212B' }}>Cabin Status — PROTO-001</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="badge badge-green">LIVE</span>
                </div>
              </div>
              <div style={{ flex: 1, padding: 8 }}>
                <CameraTile label="CABIN — OCCUPANCY / MONITORING" slot="cabin" active status="ACTIVE" frame={frame} error={camError} />
              </div>
            </div>
            <div style={{ width: 260, borderLeft: '1px solid #D9E0E7', padding: 14, flexShrink: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#17212B', marginBottom: 8 }}>Cabin Hazard</div>
              {(() => {
                const dets = Array.isArray(detections) ? detections : []
                const fire = dets.filter((d) => d.type === 'fire')
                const smoke = dets.filter((d) => d.type === 'smoke')
                if (fire.length > 0) {
                  return (
                    <div style={{ background: 'var(--red-soft)', color: 'var(--red)', border: '1px solid var(--red)', borderRadius: 6, padding: '8px 10px', fontSize: 12, fontWeight: 700, marginBottom: 10 }}>
                      🔥 FIRE DETECTED{fire[0].confidence != null ? ` · ${(fire[0].confidence * 100).toFixed(0)}%` : ''}
                      {fire.length > 1 && <div style={{ fontWeight: 400, fontSize: 11 }}>{fire.length} fire sources in frame</div>}
                    </div>
                  )
                }
                if (smoke.length > 0) {
                  return (
                    <div style={{ background: 'var(--amber-soft)', color: '#b45309', border: '1px solid var(--amber)', borderRadius: 6, padding: '8px 10px', fontSize: 12, fontWeight: 700, marginBottom: 10 }}>
                      💨 SMOKE DETECTED{smoke[0].confidence != null ? ` · ${(smoke[0].confidence * 100).toFixed(0)}%` : ''}
                    </div>
                  )
                }
                return (
                  <div style={{ background: 'var(--green-soft)', color: 'var(--green)', border: '1px solid var(--green)', borderRadius: 6, padding: '8px 10px', fontSize: 12, marginBottom: 10 }}>
                    ✓ No hazards detected
                  </div>
                )
              })()}
              <div style={{ fontSize: 12, fontWeight: 700, color: '#17212B', marginBottom: 8 }}>Cabin Occupancy</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
                <div className="flex justify-between"><span className="muted">Status</span><strong>{cabinData?.status || '—'}</strong></div>
                <div className="flex justify-between"><span className="muted">Passengers</span><strong>{cabinData?.status === 'CONNECTED' && cabinData.occupancy_count != null ? cabinData.occupancy_count : '—'}</strong></div>
                <div className="flex justify-between"><span className="muted">Occupancy</span><strong>{cabinData?.status === 'CONNECTED' && cabinData.occupancy_percentage != null ? `${cabinData.occupancy_percentage}%` : '—'}</strong></div>
                <div className="flex justify-between"><span className="muted">Crowding</span><strong>{cabinData?.status === 'CONNECTED' && cabinData.crowding_level != null ? cabinData.crowding_level : '—'}</strong></div>
                <div className="flex justify-between"><span className="muted">Estimator</span><strong>{cabinData?.estimator === 'heuristic' ? 'heuristic (dev)' : cabinData?.estimator === 'ml-person-detector' ? 'AI person count (YOLO)' : cabinData?.estimator || '—'}</strong></div>
                {cabinData?.status === 'CONNECTED' && cabinData?.confidence != null && (
                  <div className="flex justify-between"><span className="muted">Confidence</span><strong>{Math.round(cabinData.confidence * 100)}%</strong></div>
                )}
              </div>
              <div className="muted" style={{ fontSize: 10, marginTop: 10, lineHeight: 1.5 }}>
                {cabinData?.estimator === 'ml-person-detector'
                  ? 'Passenger count is calculated by AI person detection (YOLO, COCO person class) on the cabin camera feed.'
                  : 'Passenger count is a development heuristic — never presented as AI-detected.'}
              </div>
            </div>
          </div>
        )}

        {/* Road — main panel */}
        {selectedSlot === 'road' && (
          <div style={{ display: 'flex', border: '1px solid #D9E0E7', borderRadius: 8, overflow: 'hidden', background: '#fff', minHeight: 420 }}>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <div style={{ padding: '8px 12px', borderBottom: '1px solid #D9E0E7', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#17212B' }}>Road / Pothole — PROTO-001</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="badge badge-green">LIVE</span>
                </div>
              </div>
              <div style={{ flex: 1, padding: 8 }}>
                <CameraTile label="OUTSIDE — ROAD / POTHOLE" slot="road" active status="ACTIVE" frame={frame} error={camError} />
              </div>
            </div>
            <div style={{ width: 260, borderLeft: '1px solid #D9E0E7', padding: 14, flexShrink: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#17212B', marginBottom: 8 }}>Pothole Detections</div>
              {Array.isArray(detections) && detections.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {detections.map((d, i) => (
                    <div key={i} style={{ border: '1px solid #F0D9A8', background: '#FFF8E6', borderRadius: 6, padding: '6px 8px', fontSize: 11 }}>
                      <strong>{d.class_name || 'pothole'}</strong>
                      {d.confidence != null && <span className="muted"> · conf {(d.confidence * 100).toFixed(0)}%</span>}
                      {d.source && <div className="muted" style={{ fontSize: 10 }}>source {d.source}</div>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="muted" style={{ fontSize: 11 }}>No potholes detected in the current frame.</div>
              )}
              <div className="muted" style={{ fontSize: 10, marginTop: 10, lineHeight: 1.5 }}>
                Detection runs on every frame from the road camera (contour heuristic).
              </div>
            </div>
          </div>
        )}

        {/* Cabin + Road — live-aware thumbnails. Single webcam feeds one AI
            slot at a time, so the non-selected slot honestly shows STANDBY
            (not a fake live feed); clicking switches the camera to it. */}
        <div className="camera-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {['cabin', 'road'].map((slot) => {
            const isSel = selectedSlot === slot
            const st = slotStatuses[slot] || {}
            const showFrame = isSel && frame
            return (
              <div key={slot} className="camera-tile" onClick={() => { if (!isSel) switchSlot(slot); else setLightbox(slot) }} style={{ cursor: 'pointer', minHeight: 220 }}>
                <div className="camera-view" style={{ position: 'relative' }}>
                  {showFrame ? (
                    <img src={`data:image/jpeg;base64,${frame}`} alt={`${slot} camera`}
                      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', borderRadius: 4 }} />
                  ) : (
                    <CameraScene kind={slot} />
                  )}
                  <span className="camera-label">{slot === 'cabin' ? 'CABIN — MONITORING' : 'OUTSIDE — ROAD / POTHOLE'}</span>
                  <span style={{ position: 'absolute', right: 10, bottom: 10, background: 'rgba(15,23,42,0.7)', color: '#fff', borderRadius: 6, padding: '3px 8px', fontSize: 11, fontWeight: 600 }}>
                    {isSel ? '⛶ enlarge' : `▶ switch camera (${st.status || 'standby'})`}
                  </span>
                </div>
                <div className="camera-footer">
                  <span>
                    <span className={isSel && frame ? 'live-dot' : 'dot dot-grey'} />
                    {isSel ? (frame ? 'LIVE' : (camError || st.status || 'STARTING')) : `STANDBY · ${st.status || 'single camera — click to view'}`}
                  </span>
                  <span>{isSel ? 'click to enlarge' : 'click to switch'}</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      {lightbox && (
        lightbox === selectedSlot && frame ? (
          <div className="camera-lightbox" onClick={() => setLightbox(null)}
            style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(15,23,42,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
            <div className="camera-lightbox-card" onClick={(e) => e.stopPropagation()}
              style={{ background: '#fff', borderRadius: 10, padding: 16, width: 'min(1000px, 94vw)', boxShadow: '0 18px 60px rgba(0,0,0,0.4)' }}>
              <div className="flex justify-between align-center mb-8">
                <strong style={{ fontSize: 14 }}>{lightbox === 'cabin' ? 'Cabin Camera — LIVE' : 'Outside Road Camera — LIVE'}</strong>
                <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => setLightbox(null)}>✕ Close</button>
              </div>
              <div style={{ position: 'relative', height: '70vh', minHeight: 320, borderRadius: 8, overflow: 'hidden', background: '#000' }}>
                <img src={`data:image/jpeg;base64,${frame}`} alt={`${lightbox} live`}
                  style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
              </div>
            </div>
          </div>
        ) : (
          <CameraLightbox
            slot={lightbox}
            label={lightbox === 'cabin' ? 'Cabin Camera' : 'Outside Road Camera'}
            onClose={() => setLightbox(null)}
          />
        )
      )}
    </>
  )
}

/* ─── Demo placeholder camera view ─── */
function DemoCameraView({ label, note, fillParent }) {
  return (
    <div className="camera-tile" style={fillParent ? { height: '100%', minHeight: 0 } : undefined}>
      <div className="camera-view" style={fillParent ? { minHeight: 0 } : undefined}>
        <span className="camera-label">{label}</span>
        <div style={{
          width: '100%', height: '100%', minHeight: 220, display: 'flex',
          flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10,
          background:
            'repeating-linear-gradient(45deg, #f1f5f9 0 14px, #e9eef4 14px 28px)',
          borderRadius: 8,
        }}>
          <div style={{ fontSize: 44, opacity: 0.8 }}>📷</div>
          <div style={{ fontWeight: 700, fontSize: 13, color: '#17212B' }}>ESTIMATED FEED</div>
          <div className="muted" style={{ fontSize: 12 }}>{note || 'synthetic demo — no real sensor'}</div>
        </div>
      </div>
      <div className="camera-footer">
        <span><span className="dot dot-blue" /> ESTIMATED</span>
        <span>estimated feed</span>
      </div>
    </div>
  )
}

/* ─── Build DDS-shaped objects from a demo bus driver ─── */
function detFromDriver(driver, thresholds = {}) {
  driver = driver || {}
  const state = driver.state || 'NORMAL'
  const fatigueSt = driver.fatigue_st ?? 0
  const episode = driver.episode && driver.episode.ticks_left > 0 ? driver.episode : null
  const yawns =
    driver.yawns ??
    (episode ? (state === 'DROWSY' ? 2 : 1) : 0)
  return {
    state,
    severity: state === 'DROWSY' ? 'CRITICAL' : state === 'ATTENTION' ? 'WARNING' : 'NONE',
    ear: driver.ear ?? 0,
    mar: driver.mar ?? 0,
    closed_sec: driver.closed_sec ?? 0,
    perclos: (driver.perclos ?? 0) / 100,
    face_detected: true,
    head_pitch: driver.head_pitch_deg ?? 0,
    pitch: driver.head_pitch_deg ?? 0,
    yawn_count: yawns,
    drowsy_percent: fatigueSt,
    attention_percent: Math.max(0, Math.min(100, 100 - fatigueSt)),
    ear_threshold: thresholds.ear_threshold ?? 0.23,
    mar_threshold: thresholds.mar_threshold ?? 0.4,
  }
}

/* ─── Demo Camera Grid: replicates the LIVE prototype DDS UI with
       demo driver face-reading values (honestly labelled ESTIMATED). ─── */
export function DemoCameraGrid() {
  const [bus, setBus] = useState(null)
  const [count, setCount] = useState(0)
  const [lightbox, setLightbox] = useState(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const data = await api.buses()
        if (!alive) return
        const buses = data.buses || []
        setCount(buses.length)
        if (buses.length === 0) { setBus(null); return }
        const scored = buses
          .map((b) => [b, (b.driver || {}).fatigue_lt ?? 0])
          .sort((a, b) => b[1] - a[1])
        const active = scored.find(([b]) => {
          const s = (b.driver || {}).state
          return s === 'DROWSY' || s === 'ATTENTION'
        })
        setBus((active || scored[0])[0])
      } catch (e) {
        /* ignore transient poll errors */
      }
    }
    tick()
    const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const driver = bus?.driver || null
  const det = detFromDriver(driver, {
    ear_threshold: 0.23,
    mar_threshold: 0.4,
  })
  const dds = {
    monitoring: !!driver,
    phase: driver ? 'estimated' : 'idle',
    thresholds: { ear_threshold: 0.23, mar_threshold: 0.4 },
    audio: { enabled: false, triggered: 0 },
    events_emitted: 0,
    monitoring_seconds: 0,
    last: {
      yawn_count: det.yawn_count,
      drowsy_percent: det.drowsy_percent,
      attention_percent: det.attention_percent,
    },
  }
  const alertHistory = {
    eyeClosures: driver ? (driver.state !== 'NORMAL' ? (driver.perclos >= 50 ? 3 : driver.perclos >= 20 ? 2 : 1) : 0) : 0,
    yawns: det.yawn_count,
    fatigueAlerts: driver ? (driver.fatigue_stage === 'CRITICAL' || (driver.episode?.grade || 0) >= 2 ? 1 : 0) : 0,
    avgAttention: Math.round(det.attention_percent),
    perclosAvg: Math.round(driver?.perclos ?? 0),
  }

  const featured = bus ? `${bus.route_code || bus.bus_id} · ${driver?.name || 'driver'}` : '—'

  return (
    <div className="camera-grid">
      <div className="camera-main" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          background: 'var(--indigo-soft)', border: '1px solid var(--indigo)',
          borderRadius: 8, padding: '8px 12px', flexWrap: 'wrap', gap: 6,
        }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--indigo)', fontFamily: 'monospace' }}>
            ◈ ESTIMATED DDS — driver face readings
          </span>
          <span className="" style={{ fontSize: 12, color: '#17212B' }}>
            Featured demo driver: <strong>{featured}</strong> · {count} bus fleet
          </span>
        </div>

        <div style={{
          display: 'flex', border: '1px solid #D9E0E7', borderRadius: 8,
          overflow: 'hidden', background: '#fff', minHeight: 420,
        }}>
          <DDSLeftPanel det={det} dds={dds} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <div style={{
              padding: '8px 12px', borderBottom: '1px solid #D9E0E7',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#17212B' }}>
                Driver Status — {featured}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="sim-badge">◈ ESTIMATED</span>
                <span className="muted" style={{ fontSize: 11 }}>
                  {driver ? `${driver.state || 'NORMAL'} · fatigue ${Math.round(driver.fatigue_lt ?? 0)}%` : 'waiting for fleet…'}
                </span>
              </div>
            </div>
            <div style={{ flex: 1, padding: 8, display: 'flex', flexDirection: 'column' }}>
              <DemoCameraView label="DRIVER — DROWSINESS" note="synthetic face-reading feed" fillParent />
            </div>
          </div>
          <DriverStatusPanel det={det} alertHistory={alertHistory} dds={dds} />
        </div>
      </div>

      <div className="camera-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <CameraMiniTile slot="cabin" mode="sim" label="CABIN — MONITORING" onExpand={() => setLightbox('cabin')} />
        <CameraMiniTile slot="road" mode="sim" label="OUTSIDE — ROAD / POTHOLE" onExpand={() => setLightbox('road')} />
      </div>

      {lightbox && (
        <CameraLightbox
          slot={lightbox}
          label={lightbox === 'cabin' ? 'Cabin Camera' : 'Outside Road Camera'}
          onClose={() => setLightbox(null)}
        />
      )}
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
  return <DemoCameraGrid />
}
