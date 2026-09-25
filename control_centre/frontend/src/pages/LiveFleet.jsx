import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge } from '../components/UI.jsx'
import FleetMap from '../components/FleetMap.jsx'
import CallButton from '../components/CallButton.jsx'
import { useMode } from '../lib/modeContext.jsx'


function timeAgo(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 3) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function ProtoCard({ onClick }) {
  return (
    <div
      className="card card-live"
      style={{ marginBottom: 16, cursor: 'pointer', border: '2px solid var(--green)' }}
      onClick={onClick}
    >
      <div className="card-header">
        <h3 className="card-title" style={{ color: 'var(--green)' }}>
          ● 70V — Koyambedu ↔ Kilambakkam
        </h3>
        <span className="badge badge-green">LIVE</span>
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>GPS</span>
          <div>● FIX</div>
        </div>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>DRIVER</span>
          <div>● ACTIVE</div>
        </div>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>DDS</span>
          <div>● MONITORING</div>
        </div>
      </div>
      <div className="muted" style={{ marginTop: 12, fontSize: 13 }}>
        Click to view camera feeds and driver monitoring
      </div>
    </div>
  )
}

function AnnouncementButton({ busId }) {
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState('')
  const [sent, setSent] = useState(false)

  const handleSend = () => {
    if (!msg.trim()) return
    // In real implementation, this would send via WebSocket/API
    console.log(`Announcement to ${busId}: ${msg}`)
    setSent(true)
    setTimeout(() => { setSent(false); setOpen(false); setMsg('') }, 2000)
  }

  if (!open) {
    return (
      <button
        className="btn btn-sm btn-secondary"
        onClick={(e) => { e.stopPropagation(); setOpen(true) }}
        title="Make announcement to passengers"
      >
        🔊
      </button>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 4, minWidth: 200 }} onClick={(e) => e.stopPropagation()}>
      {sent ? (
        <span style={{ color: 'var(--green)', fontSize: 12, fontWeight: 600 }}>✓ Sent!</span>
      ) : (
        <>
          <input
            type="text"
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            placeholder="Type announcement..."
            autoFocus
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            style={{ flex: 1, padding: '4px 8px', fontSize: 12, borderRadius: 4, border: '1px solid var(--border)' }}
          />
          <button className="btn btn-sm btn-primary" onClick={handleSend}>Send</button>
          <button className="btn btn-sm btn-ghost" onClick={() => setOpen(false)}>✕</button>
        </>
      )}
    </div>
  )
}

export default function LiveFleet() {
  const nav = useNavigate()
  const { isLive, liveStatus } = useMode()
  const { data } = usePoll(api.buses, 3000)
  const buses = data?.buses || []

  return (
    <>
      <PageHeader
        title="Live Fleet"
        sub={isLive ? `${buses.length} nodes online — LIVE PROTOTYPE` : `${buses.length} buses online`}
        right={<SimBadge />}
      />

      {/* 70V live node card — only in live mode */}
      {isLive && (
        <ProtoCard onClick={() => nav('/fleet/PROTO-001')} />
      )}

      <div className="card map-card mb-16">
        <FleetMap buses={buses} onSelectBus={(id) => nav(`/fleet/${id}`)} height={420} />
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">{isLive ? 'Fleet List — Live Nodes' : 'Fleet List'}</h3>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Bus</th>
                <th>Route</th>
                <th>Reg No</th>
                <th>Type</th>
                <th>Status</th>
                <th>Driver</th>
                <th>Passengers</th>
                <th>Speed</th>
                <th>Intercom</th>
                <th>Announcement</th>
                <th>Last Update</th>
              </tr>
            </thead>
            <tbody>
              {buses.map((b) => (
                <tr key={b.bus_id} onClick={() => nav(`/fleet/${b.bus_id}`)} style={{ cursor: 'pointer' }}>
                  <td><strong>{b.bus_id}</strong></td>
                  <td>{b.route}</td>
                  <td className="mono">{b.reg_no || ''}</td>
                  <td><StatusBadge status={b.vehicle_type || 'DIESEL'} /></td>
                  <td><StatusBadge status={b.load.status === 'NORMAL' && b.driver.state === 'NORMAL' && b.vehicle.health === 'NORMAL' ? 'NORMAL' : 'ACTIVE'} /></td>
                  <td><StatusBadge status={b.driver.state} /></td>
                  <td>{b.occupancy.passengers}</td>
                  <td className="mono">{(b.speed_kmh ?? 0).toFixed(0)} km/h</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <CallButton busId={b.bus_id} label={`${b.route} · ${b.reg_no || ''}`} />
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <AnnouncementButton busId={b.bus_id} />
                  </td>
                  <td className="muted">{timeAgo(b.last_update)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
