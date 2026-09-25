import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge } from '../components/UI.jsx'
import FleetMap from '../components/FleetMap.jsx'
import CallButton from '../components/CallButton.jsx'
import SuggestSearch from '../components/SuggestSearch.jsx'
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

export default function LiveFleet() {
  const nav = useNavigate()
  const { isLive, liveStatus } = useMode()
  const { data } = usePoll(api.buses, 3000)
  const { data: hotspotData } = usePoll(api.trafficHotspots, 6000)
  const { data: trafficStats } = usePoll(api.trafficStats, 5000)
  const { data: pedestrianStats } = usePoll(api.pedestrianStats, 5000)
  const { data: heatmapData } = usePoll(api.trafficHeatmap, 8000)
  const buses = data?.buses || []
  const hotspots = hotspotData?.hotspots || []
  const traffic = trafficStats || {}
  const pedestrian = pedestrianStats || {}
  const heatmap = heatmapData || {}
  const [filter, setFilter] = useState('')

  // Suggestion catalogue: every bus (id + reg no) and every route code.
  const searchItems = useMemo(() => {
    const seen = new Set()
    const items = []
    for (const b of buses) {
      items.push({
        key: `bus-${b.bus_id}`,
        label: b.bus_id,
        sublabel: `${b.route || ''}${b.reg_no ? ' · ' + b.reg_no : ''}`,
        keywords: `${b.reg_no || ''} ${b.route || ''}`,
      })
      const rc = b.route_code || b.route?.split(' - ')[0]
      if (rc && !seen.has(rc)) {
        seen.add(rc)
        items.push({ key: `route-${rc}`, label: String(rc), sublabel: 'route', keywords: 'route' })
      }
    }
    return items
  }, [buses])

  const q = filter.trim().toLowerCase()
  const filteredBuses = useMemo(() => {
    if (!q) return buses
    return buses.filter((b) => {
      const rc = b.route_code || b.route?.split(' - ')[0] || ''
      return (
        b.bus_id?.toLowerCase().includes(q) ||
        (b.reg_no || '').toLowerCase().includes(q) ||
        String(rc).toLowerCase().includes(q) ||
        (b.route || '').toLowerCase().includes(q)
      )
    })
  }, [buses, q])

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

      {/* Traffic stats card — shows vehicle detection from road camera */}
      {isLive && traffic.current_detections !== undefined && (
        <div className="card mb-16" style={{ borderLeft: '4px solid #0066cc' }}>
          <div className="card-header">
            <h3 className="card-title" style={{ color: '#0066cc' }}>🚗 Vehicle Detection (Road Camera)</h3>
            <span className="badge badge-blue">YOLOv8 COCO</span>
          </div>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Total This Frame</div>
              <div className="mono" style={{ fontSize: 24, fontWeight: 700, color: '#003366' }}>
                {traffic.current_detections ?? 0}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Unique (ByteTrack)</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#003366' }}>
                {traffic.unique_vehicles_this_frame ?? '—'}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Frames Processed</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#374151' }}>
                {traffic.total_frames_processed ?? 0}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Cumulative Vehicles</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#374151' }}>
                {traffic.total_detections ?? 0}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Cumulative Unique</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#374151' }}>
                {traffic.total_unique_vehicles ?? 0}
              </div>
            </div>
            {traffic.class_totals && (
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
                {Object.entries(traffic.class_totals).map(([name, count]) => (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      width: 12, height: 12, borderRadius: 3,
                      background: name === 'car' ? '#16a34a' :
                                name === 'bus' ? '#2563eb' :
                                name === 'truck' ? '#ea580c' : '#d946ef'
                    }} />
                    <span className="muted" style={{ fontSize: 12, fontWeight: 600 }}>
                      {name}: {count}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              Source: {traffic.detection_source || 'MODEL'} ·{' '}
              {traffic.tracking_active ? 'ByteTrack tracking ACTIVE (unique counted)' : 'Frame-level counts (no tracking)'}
            </div>
          </div>
        </div>
      )}

      {/* Pedestrian (vulnerable road user) detection card — road camera */}
      {isLive && pedestrian.current_detections !== undefined && (
        <div className="card mb-16" style={{ borderLeft: '4px solid #dc2626' }}>
          <div className="card-header">
            <h3 className="card-title" style={{ color: '#dc2626' }}>🚶 Pedestrian Presence (Vulnerable Road Users)</h3>
            <span className="badge badge-red">COCO person · MODEL</span>
          </div>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Pedestrians (frame)</div>
              <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: '#dc2626' }}>
                {pedestrian.current_detections ?? 0}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Near / On Roadway</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#f97316' }}>
                {pedestrian.near_roadway_this_frame ?? '—'}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Total Detections</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#374151' }}>
                {pedestrian.total_pedestrian_detections ?? 0}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Unique (ByteTrack)</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: '#374151' }}>
                {pedestrian.total_unique_pedestrians ?? 0}
              </div>
            </div>
            <div className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              Source: {pedestrian.detection_source || 'MODEL'} (COCO person) ·{' '}
              near/on-roadway = bbox-geometry heuristic · no age/group inference
            </div>
          </div>
        </div>
      )}

      {/* SUGGESTION SEARCH — above the map; typing suggests buses/routes */}
      <div className="card mb-16">
        <SuggestSearch
          items={searchItems}
          placeholder="Search bus number or route — suggestions appear as you type (e.g. D, D7, D70…)"
          onSelect={(it) => {
            // route suggestions filter the list; bus suggestions open the bus
            if (it.sublabel === 'route') setFilter(it.label)
            else nav(`/fleet/${encodeURIComponent(it.label)}`)
          }}
          onQuery={setFilter}
          style={{ maxWidth: 560 }}
        />
        {q && (
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            filtering {filteredBuses.length} of {buses.length} buses ·{' '}
            <button className="btn btn-ghost" style={{ fontSize: 11, padding: '1px 6px' }} onClick={() => setFilter('')}>
              clear
            </button>
          </div>
        )}
      </div>

      <div className="card map-card mb-16">
        <FleetMap buses={filteredBuses} onSelectBus={(id) => nav(`/fleet/${id}`)} height={420} hotspots={hotspots} heatmap={heatmap} />
        {(hotspots.length > 0 || heatmap?.cells?.length > 0) && (
          <div className="map-legend">
            {hotspots.length > 0 && <div><span className="badge badge-red">⚠ traffic red dot</span> {hotspots.length}</div>}
            {heatmap?.cells?.length > 0 && (
              <div><span
                style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 6, background: heatmap.hotspots_declared ? '#ef4444' : '#3b82f6', marginRight: 6 }}
              />congestion heat map · {heatmap.cells.length} cells
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">{isLive ? 'Fleet List — Live Nodes' : 'Fleet List'}</h3>
          <span className="muted" style={{ fontSize: 12 }}>{filteredBuses.length} shown</span>
        </div>
        <div className="table-wrap">
          <table className="table table-fleet">
            <thead>
              <tr>
                <th>Bus</th>
                <th>Route</th>
                <th>Status</th>
                <th>Driver</th>
                <th>Passengers</th>
                <th>Speed</th>
                <th>Intercom</th>
                <th>Last Update</th>
              </tr>
            </thead>
            <tbody>
              {filteredBuses.map((b) => (
                <tr key={b.bus_id} onClick={() => nav(`/fleet/${b.bus_id}`)} style={{ cursor: 'pointer' }}>
                  <td><strong>{b.bus_id}</strong></td>
                  <td>{b.route}</td>
                  <td><StatusBadge status={b.load?.status === 'NORMAL' && b.driver?.state === 'NORMAL' && b.vehicle?.health === 'NORMAL' ? 'NORMAL' : 'ACTIVE'} /></td>
                  <td><StatusBadge status={b.driver?.state || 'UNKNOWN'} /></td>
                  <td>{b.occupancy?.passengers ?? '—'}</td>
                  <td className="mono">{(b.speed_kmh ?? 0).toFixed(0)} km/h</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <CallButton busId={b.bus_id} label={`${b.route} · ${b.reg_no || ''}`} />
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
