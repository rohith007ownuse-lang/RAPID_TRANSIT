import { MapContainer, TileLayer, CircleMarker, Marker, Polyline, Popup, Tooltip } from 'react-leaflet'
import L from 'leaflet'
import { useMode } from '../lib/modeContext.jsx'

const BUS_ICON = L.divIcon({
  className: '',
  html: '<div style="width:26px;height:26px;border-radius:50%;background:#2563eb;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);display:grid;place-items:center;color:#fff;font-size:11px;font-weight:700;">🚌</div>',
  iconSize: [26, 26],
  iconAnchor: [13, 13],
})

const SELECTED_ICON = L.divIcon({
  className: '',
  html: '<div style="width:32px;height:32px;border-radius:50%;background:#dc2626;border:3px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.35);display:grid;place-items:center;color:#fff;font-size:13px;font-weight:700;">🚌</div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
})

const LIVE_ICON = L.divIcon({
  className: '',
  html: '<div style="width:30px;height:30px;border-radius:50%;background:#16a34a;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:800;">●</div>',
  iconSize: [30, 30],
  iconAnchor: [15, 15],
})

const LIVE_SELECTED_ICON = L.divIcon({
  className: '',
  html: '<div style="width:36px;height:36px;border-radius:50%;background:#16a34a;border:4px solid #fff;box-shadow:0 2px 12px rgba(0,0,0,.5);display:grid;place-items:center;color:#fff;font-size:14px;font-weight:800;">●</div>',
  iconSize: [36, 36],
  iconAnchor: [18, 18],
})

const DEFECT_ICON = L.divIcon({
  className: '',
  html: '<div style="width:20px;height:20px;border-radius:50%;background:#d97706;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);color:#fff;font-size:10px;display:grid;place-items:center;">⚠</div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
})

const CRASH_ICON = L.divIcon({
  className: '',
  html: '<div style="width:26px;height:26px;border-radius:50%;background:#dc2626;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);color:#fff;font-size:12px;display:grid;place-items:center;">✖</div>',
  iconSize: [26, 26],
  iconAnchor: [13, 13],
})

const DEFAULT_CENTER = [13.0827, 80.2747]

const A_ICON = L.divIcon({
  className: '',
  html: '<div style="width:24px;height:24px;border-radius:50%;background:#059669;border:2px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.35);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:800;">A</div>',
  iconSize: [24, 24],
  iconAnchor: [12, 12],
})

const B_ICON = L.divIcon({
  className: '',
  html: '<div style="width:24px;height:24px;border-radius:50%;background:#dc2626;border:2px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.35);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:800;">B</div>',
  iconSize: [24, 24],
  iconAnchor: [12, 12],
})

export default function FleetMap({
  buses = [],
  defects = [],
  onSelectBus,
  selectedBusId = null,
  height = 460,
  showDefects = false,
  routePath = null,
  activeLeg = null,
}) {
  const { isLive } = useMode()

  // Filter buses with valid GPS positions
  const validBuses = buses.filter(b =>
    b.latitude != null && b.longitude != null &&
    !isNaN(b.latitude) && !isNaN(b.longitude)
  )

  // Calculate center based on valid buses or default
  const center = validBuses.length > 0
    ? [validBuses[0].latitude, validBuses[0].longitude]
    : DEFAULT_CENTER

  return (
    <MapContainer center={center} zoom={isLive && validBuses.length === 1 ? 15 : 11} style={{ minHeight: height, height: '100%', zIndex: 0 }}>
      <TileLayer
        attribution='&copy; OpenStreetMap contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {showDefects && defects.map((d) => (
        <Marker key={d.defect_id} position={[d.latitude, d.longitude]} icon={DEFECT_ICON}>
          <Popup>
            <strong>{d.type}</strong>
            <div>detections: {d.detection_count}</div>
            <div>confidence: {Math.round(d.confidence * 100)}%</div>
            <div>seen by: {d.buses.join(', ')}</div>
          </Popup>
        </Marker>
      ))}
      {routePath && routePath.length >= 2 && (
        <>
          <Polyline
            positions={routePath}
            pathOptions={{ color: '#2563eb', weight: 4, opacity: 0.85 }}
          />
          {activeLeg && activeLeg.length === 2 && (
            <Polyline
              positions={activeLeg}
              pathOptions={{ color: '#dc2626', weight: 6, opacity: 1 }}
            />
          )}
          <Marker position={routePath[0]} icon={A_ICON}>
            <Tooltip direction="top">Start · Point A</Tooltip>
          </Marker>
          <Marker position={routePath[routePath.length - 1]} icon={B_ICON}>
            <Tooltip direction="top">Destination · Point B</Tooltip>
          </Marker>
        </>
      )}
      {validBuses.map((b) => {
        const isLiveBus = b.data_source === 'live' || b._live
        const isSelected = selectedBusId === b.bus_id
        const icon = isLiveBus
          ? (isSelected ? LIVE_SELECTED_ICON : LIVE_ICON)
          : (isSelected ? SELECTED_ICON : BUS_ICON)

        return (
          <Marker
            key={b.bus_id}
            position={[b.latitude, b.longitude]}
            icon={icon}
            eventHandlers={onSelectBus ? { click: () => onSelectBus(b.bus_id) } : undefined}
          >
            <Tooltip direction="top">
              {b.bus_id}
              {isLiveBus && <span style={{ color: '#16a34a', fontWeight: 700 }}> ● LIVE</span>}
              {!isLiveBus && <span style={{ color: '#6b7280' }}> ◈ SIM</span>}
              <div className="muted" style={{ fontSize: 11 }}>
                {(b.speed_kmh ?? 0).toFixed(0)} km/h {b.speed_kmh > 0 ? '· ' + (b.journey?.state || '').toLowerCase() : '· stopped'}
              </div>
            </Tooltip>
            <Popup>
              <strong>{b.bus_id}</strong>
              <div className="mono muted" style={{ fontSize: 11 }}>{b.reg_no}</div>
              <div>{b.route}</div>
              <div>driver: {b.driver.name || b.driver.state}</div>
              <div>passengers: {b.occupancy.passengers}</div>
              <div>speed: {(b.speed_kmh ?? 0).toFixed(0)} km/h</div>
            </Popup>
          </Marker>
        )
      })}
    </MapContainer>
  )
}

export function CrashDot({ lat, lng, label }) {
  return (
    <CircleMarker center={[lat, lng]} radius={14} pathOptions={{ color: '#dc2626', fillColor: '#fecaca', fillOpacity: 0.35 }}>
      {label && <Tooltip direction="top">{label}</Tooltip>}
    </CircleMarker>
  )
}

export function LiveNodeMarker({ node }) {
  const { bus_id, connected, last_seen_ago, gps_available } = node

  if (!connected) {
    return null // Don't render disconnected nodes
  }

  return (
    <div className="live-node-status">
      <span className="dot dot-green" />
      <strong>{bus_id}</strong>
      <span className="muted" style={{ fontSize: 11 }}>
        {gps_available ? 'GPS OK' : 'GPS WAITING'} · {last_seen_ago}s ago
      </span>
    </div>
  )
}