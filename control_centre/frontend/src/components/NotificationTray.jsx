import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../lib/authContext.jsx'

/*
  ─── Global Notification Bell Tray ───
  Fixed at the top of the screen on every page. Shows a bell + count badge of
  assigned critical incidents. Click → opens a down bar listing every critical
  alert stacked one below another. Each row offers Acknowledge / View live feed
  / Respond — handled right inside the tray, no need to leave the page.
  Assigned incidents that no operator has reviewed yet stay listed here.
*/
export default function NotificationTray() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const operator = user?.username || 'operator'
  const [open, setOpen] = useState(false)
  const [incidents, setIncidents] = useState([])
  const [isResponding, setIsResponding] = useState({})
  const trayRef = useRef(null)

  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const data = await api.assignedIncidents()
        if (!alive) return
        setIncidents(data.incidents || [])
      } catch (e) { /* ignore polling errors */ }
    }
    check()
    const id = setInterval(check, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // Close when clicking outside the tray
  useEffect(() => {
    const onDocClick = (e) => {
      if (trayRef.current && !trayRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const act = async (fn, incidentId) => {
    setIsResponding((s) => ({ ...s, [incidentId]: true }))
    try { await fn() } catch (e) { console.error('Incident action failed:', e) }
    setIsResponding((s) => ({ ...s, [incidentId]: false }))
  }

  const count = incidents.length
  const busy = (id) => !!isResponding[id]

  return (
    <div ref={trayRef} style={{ position: 'fixed', top: 14, right: 14, zIndex: 11000 }}>
      {/* bell button */}
      <button
        className="btn"
        onClick={() => setOpen((o) => !o)}
        style={{
          position: 'relative', minWidth: 44, height: 44, borderRadius: 22,
          padding: '0 12px', boxShadow: '0 2px 12px rgba(0,0,0,0.18)',
        }}
        aria-label="Notifications"
      >
        <span style={{ fontSize: 18 }}>🔔</span>
        {count > 0 && (
          <span
            style={{
              position: 'absolute', top: -4, right: -4, minWidth: 20, height: 20,
              borderRadius: 10, background: '#E53935', color: '#fff',
              fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center',
              justifyContent: 'center', padding: '0 5px',
            }}
          >
            {count}
          </span>
        )}
      </button>

      {/* down bar — all critical alerts stacked */}
      {open && (
        <div
          style={{
            position: 'absolute', top: 52, right: 0, width: 400, maxWidth: '92vw',
            maxHeight: '70vh', overflowY: 'auto', background: '#fff',
            borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.28)',
            border: '1px solid #E5EAF0',
          }}
        >
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #E5EAF0', background: '#F7F9FC' }}>
            <strong style={{ fontSize: 13, color: '#17212B' }}>🔔 Critical Alerts</strong>
            <span className="muted" style={{ fontSize: 11, marginLeft: 8 }}>
              {count} waiting
            </span>
          </div>

          {incidents.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: '#66727E', fontSize: 12 }}>
              No critical alerts waiting right now.
            </div>
          ) : (
            incidents.map((inc) => (
              <div
                key={inc.incident_id}
                style={{
                  borderBottom: '1px solid #EDF1F5', padding: '12px 16px',
                  borderLeft: '4px solid #E53935',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 14 }}>🚨</span>
                  <strong style={{ fontSize: 12.5, color: '#17212B' }}>{inc.title}</strong>
                  {(inc.escalation_level || 0) > 0 && (
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#E53935' }}>
                      ESCALATED ×{inc.escalation_level}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: '#66727E', lineHeight: 1.5, marginBottom: 8 }}>
                  Bus {inc.bus_id}{inc.route ? ` · ${inc.route}` : ''} ·{' '}
                  {inc.status} → {inc.assigned_to || '–'}
                </div>
                <div className="flex gap-8 wrap">
                  <button
                    className="btn"
                    style={{ fontSize: 12 }}
                    disabled={busy(inc.incident_id)}
                    onClick={() => act(() => api.acknowledgeIncident(inc.incident_id, { operator }), inc.incident_id)}
                  >
                    ✓ Acknowledge
                  </button>
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
                    disabled={busy(inc.incident_id)}
                    onClick={() => act(() => api.respondIncident(inc.incident_id, { operator }), inc.incident_id)}
                  >
                    Respond
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}