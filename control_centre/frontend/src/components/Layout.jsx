import { NavLink, Link, useNavigate } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import IncomingCall from './IncomingCall.jsx'
import CriticalIncidentPopup from './CriticalIncidentPopup.jsx'
import NotificationTray from './NotificationTray.jsx'
import { BrandLogo } from './UI.jsx'
import { useMode } from '../lib/modeContext.jsx'
import { useAuth } from '../lib/authContext.jsx'
import { api } from '../api.js'

const NAV = [
  { to: '/', label: 'Dashboard', icon: '▦', end: true },
  { to: '/fleet', label: 'Live Fleet', icon: '🚌' },
  { to: '/driver-safety', label: 'Driver Safety', icon: '👁️' },
  { to: '/load-management', label: 'Load Management', icon: '⚖️' },
  { to: '/incidents', label: 'Incidents', icon: '🚨' },
  { to: '/emergency', label: 'Emergency', icon: '🆘' },
  { to: '/roads', label: 'Road Intelligence', icon: '🛣️' },
  { to: '/ai-suggestions', label: 'AI Suggestions', icon: '🤖' },
  { to: '/routes', label: 'Route Map', icon: '🗺️' },
  { to: '/route-intelligence', label: 'Route Intel', icon: '📊' },
  { to: '/historical', label: 'Historical', icon: '📅' },
  { to: '/health', label: 'Vehicle Health', icon: '🔧' },
  { to: '/analytics', label: 'Analytics', icon: '📈' },
]

const ADMIN_NAV = [
  { to: '/settings', label: 'Settings', icon: '⚙️' },
  { to: '/features', label: 'Feature Toggles', icon: '🎛️' },
  { to: '/users', label: 'Users', icon: '👥' },
]

export function Brand() {
  return (
    <div className="brand">
      <BrandLogo size={34} />
      <div>
        <div className="brand-name">Rapid Transit</div>
        <div className="brand-sub">City Public Transport</div>
      </div>
    </div>
  )
}

function ModeSwitcher() {
  const { mode, switching, switchMode, liveStatus } = useMode()

  return (
    <div className="mode-switcher">
      <div className="mode-switcher-label">DATA SOURCE</div>
      <div className="mode-switcher-control">
        <button
          className={`mode-btn ${mode === 'simulation' ? 'active' : ''}`}
          onClick={() => switchMode('simulation')}
          disabled={switching}
        >
          ◈ ESTIMATED
        </button>
        <button
          className={`mode-btn ${mode === 'live' ? 'active' : ''}`}
          onClick={() => switchMode('live')}
          disabled={switching}
        >
          ● LIVE PROTOTYPE
        </button>
      </div>
      {mode === 'simulation' && (
        <div className="mode-status mode-status-sim">
          <span className="mode-status-dot dot-blue" />
          ESTIMATED · 300 buses
        </div>
      )}
      {mode === 'live' && (
        <div className="mode-status mode-status-live">
          <span className="mode-status-dot dot-green" />
          LIVE PROTOTYPE
        </div>
      )}
    </div>
  )
}

/* ─── Global Drowsiness Alert ─── */
function DrowsinessAlert() {
  const { isLive } = useMode()
  const [alert, setAlert] = useState(null)
  const lastEventRef = useRef(null)

  useEffect(() => {
    if (!isLive) return
    let alive = true
    const check = async () => {
      try {
        const data = await api.events({ data_source: 'live', type: 'DRIVER_DROWSINESS', status: 'ACTIVE' })
        if (!alive) return
        const events = (data.events || []).filter((e) => e.bus_id === 'PROTO-001')
        if (events.length > 0) {
          const latest = events[0]
          if (latest.event_id !== lastEventRef.current) {
            lastEventRef.current = latest.event_id
            const note = latest.additional_data?.note || 'Driver drowsiness detected'
            // Simplify the cause for the operator
            let cause = 'Drowsiness detected'
            if (note.includes('eye closure')) cause = 'Prolonged eye closure'
            else if (note.includes('PERCLOS')) cause = 'High PERCLOS'
            else if (note.includes('head pose')) cause = 'Head pose alert'
            setAlert({
              bus: '70V',
              route: 'Koyambedu → Kilambakkam',
              cause,
              severity: latest.severity,
            })
          }
        } else {
          // No active drowsiness events → clear alert (recovery)
          if (alert) setAlert(null)
          lastEventRef.current = null
        }
      } catch (e) { /* ignore */ }
    }
    check()
    const interval = setInterval(check, 5000)
    return () => { alive = false; clearInterval(interval) }
  }, [isLive])

  if (!isLive || !alert) return null

  const isCritical = alert.severity === 'CRITICAL'
  return (
    <div
      style={{
        position: 'fixed', top: 16, right: 16, zIndex: 9999,
        background: '#fff', borderLeft: `4px solid ${isCritical ? '#E53935' : '#F5A623'}`,
        borderRadius: 8, padding: '12px 16px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
        maxWidth: 340, cursor: 'pointer',
      }}
      onClick={() => setAlert(null)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 16 }}>🔴</span>
        <strong style={{ fontSize: 13, color: '#17212B' }}>Driver Drowsiness Alert</strong>
      </div>
      <div style={{ fontSize: 12, color: '#66727E', lineHeight: 1.5 }}>
        Bus {alert.bus} — {alert.route}<br />
        <span style={{ color: isCritical ? '#E53935' : '#F5A623', fontWeight: 600 }}>Cause: {alert.cause}</span>
      </div>
    </div>
  )
}

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <Brand />
        <ModeSwitcher />
        <div className="nav-section">Operations</div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
          >
            <span className="nav-icon">{n.icon}</span> {n.label}
          </NavLink>
        ))}
        <div className="nav-section">Administration</div>
        {(isAdmin ? ADMIN_NAV : [{ to: '/settings', label: 'Settings', icon: '⚙️' }]).map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
          >
            <span className="nav-icon">{n.icon}</span> {n.label}
            {!isAdmin && n.to === '/settings' && <span className="nav-lock" title="Admin only">🔒</span>}
          </NavLink>
        ))}
        <div className="nav-section session">
          <div className="session-user">{user?.username}</div>
          {user?.role && user?.role !== user?.username && <div className="session-role">{user?.role}</div>}
          <button className="btn btn-sm btn-ghost" onClick={handleLogout}>Logout</button>
        </div>
      </aside>
      <main className="main">{children}</main>
      <IncomingCall />
      <DrowsinessAlert />
      <NotificationTray />
      <CriticalIncidentPopup />
    </div>
  )
}

export function PageHeader({ title, sub, right }) {
  return (
    <div className="topbar">
      <div>
        <h1 className="page-title">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {right && <div className="flex gap-8 wrap">{right}</div>}
    </div>
  )
}

export function SimBadge({ show = true }) {
  const { isSimulation } = useMode()
  if (!show) return null
  return isSimulation ? (
    <span className="sim-badge" title="All data on this page is estimated demo data, not real sensor measurement.">
      ◈ ESTIMATED
    </span>
  ) : (
    <span className="live-badge" title="Live prototype data from connected hardware.">
      ● LIVE
    </span>
  )
}

export function DataBadge({ dataSource }) {
  if (dataSource === 'live') {
    return <span className="live-badge">● LIVE</span>
  }
  return <span className="sim-badge">◈ DEMO</span>
}

export function BreadcrumbBus({ busId }) {
  return (
    <div className="muted" style={{ fontSize: 13 }}>
      <Link to="/fleet">Live Fleet</Link> <span>/</span> {busId}
    </div>
  )
}