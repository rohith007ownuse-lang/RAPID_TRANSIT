import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../lib/authContext.jsx'

/* Sound gate: OFF at startup, only plays when audio_alerts is ON in
   Feature Toggles. Checks backend first, falls back to localStorage. */
let _audioCache = { value: false, ts: 0 }
async function isAudioEnabled() {
  const now = Date.now()
  if (now - _audioCache.ts < 5000) return _audioCache.value
  try {
    const data = await api.getFeatures()
    _audioCache = { value: !!data?.audio_alerts, ts: now }
    return _audioCache.value
  } catch { /* fall through to localStorage */ }
  try {
    const saved = JSON.parse(localStorage.getItem('rapid_feature_toggles') || '{}')
    // localStorage stores full objects {enabled} or plain booleans
    const v = saved?.audio_alerts
    const enabled = typeof v === 'object' ? !!v.enabled : !!v
    _audioCache = { value: enabled, ts: now }
    return enabled
  } catch { return false }
}
function playEscalationSound(escalationLevel = 0) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    const repeats = Math.min(1 + escalationLevel, 3)
    let t = ctx.currentTime
    for (let r = 0; r < repeats; r++) {
      for (const freq of [660, 880]) {
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.type = 'sine'
        osc.frequency.value = freq
        gain.gain.setValueAtTime(0.0001, t)
        gain.gain.exponentialRampToValueAtTime(0.25, t + 0.03)
        gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.16)
        osc.connect(gain)
        gain.connect(ctx.destination)
        osc.start(t)
        osc.stop(t + 0.18)
        t += 0.2
      }
      t += 0.25
    }
    setTimeout(() => ctx.close().catch(() => {}), (t + 0.5) * 1000)
  } catch (e) { /* audio unavailable — popup still shows */ }
}

/* ─── Global Critical-Incident Popup ───
   Auto-assigned CRITICAL work pops up on every page. Clicking "View live
   feed" jumps straight to the bus. Respond / Reject act on the incident.
   Unanswered work re-pops with an escalated sound via escalation_level. */
export default function CriticalIncidentPopup() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const operator = user?.username || 'operator'
  const [items, setItems] = useState([])
  const [dismissed, setDismissed] = useState({})
  const seenRef = useRef({}) // incident_id -> escalation_level already sounded
  const dismissedRef = useRef({})
  dismissedRef.current = dismissed

  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const data = await api.assignedIncidents()
        if (!alive) return
        const critical = (data.incidents || []).filter(
          (i) => i.severity === 'CRITICAL' && i.status === 'ASSIGNED'
        )
        setItems(critical)
        for (const inc of critical) {
          const key = inc.incident_id
          const lvl = inc.escalation_level || 0
          if ((seenRef.current[key] ?? -1) < lvl) {
            seenRef.current[key] = lvl
            // Sound only if audio_alerts toggle is ON — silent otherwise
            if (!dismissedRef.current[key] && (await isAudioEnabled())) playEscalationSound(lvl)
          }
        }
      } catch (e) { /* ignore polling errors */ }
    }
    check()
    const id = setInterval(check, 3000)
    return () => { alive = false; clearInterval(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const act = async (fn, incidentId) => {
    try { await fn() } catch (e) { console.error('Incident action failed:', e) }
    setItems((prev) => prev.filter((i) => i.incident_id !== incidentId))
  }

  const visible = items.filter((i) => !dismissed[i.incident_id])
  const inc = visible[0] // ONE critical alert at a time
  if (!inc) return null

  return (
    <div style={{ position: 'fixed', top: 70, right: 14, zIndex: 10000, width: 360, maxWidth: '92vw' }}>
      <div
        style={{
          background: '#fff', borderLeft: '4px solid #E53935', borderRadius: 8,
          padding: '12px 16px', boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 16 }}>🚨</span>
          <strong style={{ fontSize: 13, color: '#17212B' }}>Critical — action needed</strong>
          {(inc.escalation_level || 0) > 0 && (
            <span style={{ fontSize: 10, fontWeight: 700, color: '#E53935' }}>
              ESCALATED ×{inc.escalation_level}
            </span>
          )}
          <button
            className="btn btn-ghost"
            style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 6px' }}
            onClick={() => setDismissed((d) => ({ ...d, [inc.incident_id]: true }))}
          >
            ✕
          </button>
        </div>
        <div style={{ fontSize: 12, color: '#66727E', lineHeight: 1.5 }}>
          <strong style={{ color: '#17212B' }}>{inc.title}</strong><br />
          Bus {inc.bus_id}{inc.route ? ` · ${inc.route}` : ''} · Assigned to <strong>{inc.assigned_to}</strong>
        </div>
        <div className="flex gap-8 mt-8 wrap">
          <button
            className="btn btn-primary"
            style={{ fontSize: 12 }}
            onClick={() => navigate(inc.bus_id ? `/fleet/${encodeURIComponent(inc.bus_id)}` : '/incidents')}
          >
            View live feed
          </button>
          <button
            className="btn"
            style={{ fontSize: 12 }}
            onClick={() => act(() => api.respondIncident(inc.incident_id, { operator }), inc.incident_id)}
          >
            Respond
          </button>
        </div>
      </div>
    </div>
  )
}
