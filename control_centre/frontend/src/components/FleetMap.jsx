import { useState, useEffect, useMemo, useRef, Fragment } from 'react'
import { MapContainer, TileLayer, Circle, CircleMarker, Marker, Polyline, Popup, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { useMode } from '../lib/modeContext.jsx'
import { api } from '../api.js'

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
  html: '<div style="position:relative;width:26px;height:36px;display:grid;place-items:center;"><div style="position:absolute;width:9px;height:9px;background:#2563eb;border:2.5px solid #fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);top:4px;box-shadow:0 1px 5px rgba(0,0,0,.35);"></div><div style="position:absolute;top:4px;width:0;height:0;border:10px solid transparent;border-bottom:18px solid #2563eb;filter:drop-shadow(0 1px 3px rgba(0,0,0,.3));"></div><div style="position:absolute;left:0;right:0;top:6px;text-align:center;color:#fff;font-size:10px;font-weight:800;z-index:1;">A</div></div>',
  iconSize: [26, 36],
  iconAnchor: [13, 34],
})

const B_ICON = L.divIcon({
  className: '',
  html: '<div style="position:relative;width:26px;height:36px;display:grid;place-items:center;"><div style="position:absolute;width:9px;height:9px;background:#dc2626;border:2.5px solid #fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);top:4px;box-shadow:0 1px 5px rgba(0,0,0,.35);"></div><div style="position:absolute;top:4px;width:0;height:0;border:10px solid transparent;border-bottom:18px solid #dc2626;filter:drop-shadow(0 1px 3px rgba(0,0,0,.3));"></div><div style="position:absolute;left:0;right:0;top:6px;text-align:center;color:#fff;font-size:10px;font-weight:800;z-index:1;">B</div></div>',
  iconSize: [26, 36],
  iconAnchor: [13, 34],
})

const STOP_ICON = L.divIcon({
  className: '',
  html: '<div style="width:10px;height:10px;border-radius:50%;background:#003366;border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.4);cursor:pointer;"></div>',
  iconSize: [10, 10],
  iconAnchor: [5, 5],
})

const SELECTED_STOP_ICON = L.divIcon({
  className: '',
  html: '<div style="width:14px;height:14px;border-radius:50%;background:#004488;border:2.5px solid #fff;box-shadow:0 0 8px rgba(0,51,102,.6);"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
})

const HOSPITAL_ICON = L.divIcon({
  className: '',
  html: '<div style="width:22px;height:22px;border-radius:4px;background:#dc2626;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700;">🏥</div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

const FIRE_ICON = L.divIcon({
  className: '',
  html: '<div style="width:22px;height:22px;border-radius:4px;background:#ea580c;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700;">🚒</div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

const POLICE_ICON = L.divIcon({
  className: '',
  html: '<div style="width:22px;height:22px;border-radius:4px;background:#2563eb;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700;">🚓</div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

const TRAFFIC_ICON = L.divIcon({
  className: '',
  html: '<div style="width:22px;height:22px;border-radius:4px;background:#d97706;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3);display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700;">🚦</div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

// Component to handle map fly-to when a route is selected.
// Re-fits only when the route shape actually changes (first/last points and
// point count) so the 3s data poll can never yank the map back to the
// route bounds and override the user's zoom/pan.
function MapUpdater({ selectedRoutePolyline, focusStop }) {
  const map = useMap()
  const seenRef = useRef(null)
  useEffect(() => {
    if (selectedRoutePolyline && selectedRoutePolyline.length > 0) {
      const first = selectedRoutePolyline[0]
      const last = selectedRoutePolyline[selectedRoutePolyline.length - 1]
      const sig = `${selectedRoutePolyline.length}:${first?.[0]?.toFixed(4)},${first?.[1]?.toFixed(4)}:${last?.[0]?.toFixed(4)},${last?.[1]?.toFixed(4)}`
      if (seenRef.current !== sig) {
        seenRef.current = sig
        const bounds = L.latLngBounds(selectedRoutePolyline)
        map.flyToBounds(bounds, { padding: [40, 40], maxZoom: 14 })
      }
    }
  }, [selectedRoutePolyline, map])
  // Fly to a focus stop (picked from the MTC suggestion search)
  useEffect(() => {
    if (focusStop && focusStop.lat != null && focusStop.lon != null) {
      map.flyTo([focusStop.lat, focusStop.lon], 15, { duration: 0.8 })
    }
  }, [focusStop, map])
  return null
}

// Bus stop popup showing buses serving this stop and schedule
function StopPopup({ stop, buses }) {
  const [stopDetail, setStopDetail] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    api.gtfsStopDetail(stop.stop_id).then(d => {
      setStopDetail(d)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [stop.stop_id])

  // Find buses currently serving this stop's routes
  const servingBuses = useMemo(() => {
    if (!stop.routes || stop.routes.length === 0) return []
    const routeSet = new Set(stop.routes)
    return buses.filter(b => {
      const routeCode = b.route_code || b.route?.split(' - ')[0]
      return routeSet.has(routeCode)
    }).slice(0, 10)
  }, [stop.routes, buses])

  // Build schedule from boarding profiles of serving buses
  const schedule = useMemo(() => {
    if (!stop.routes || stop.routes.length === 0) return []
    const routeSet = new Set(stop.routes)
    const scheduleMap = {}
    for (const b of buses) {
      const routeCode = b.route_code || b.route?.split(' - ')[0]
      if (!routeSet.has(routeCode)) continue
      const byStop = b.boarding_by_stop_hour
      if (!byStop || !byStop[stop.stop_name]) continue
      const hours = byStop[stop.stop_name]
      for (const [h, count] of Object.entries(hours)) {
        if (count > 0) {
          if (!scheduleMap[h]) scheduleMap[h] = { total: 0, buses: new Set() }
          scheduleMap[h].total += count
          scheduleMap[h].buses.add(b.bus_id)
        }
      }
    }
    return Object.entries(scheduleMap)
      .map(([hour, data]) => ({ hour: parseInt(hour), ...data }))
      .sort((a, b) => a.hour - b.hour)
      .slice(0, 14)
  }, [stop.routes, stop.stop_name, buses])

  return (
    <div style={{ fontSize: 12, fontFamily: 'system-ui, sans-serif', lineHeight: 1.5 }}>
      <div style={{ fontWeight: 700, fontSize: 14, color: '#003366', marginBottom: 4 }}>
        {stop.stop_name}
      </div>
      <div style={{ color: '#6b7280', fontSize: 11, marginBottom: 6 }}>
        Stop ID: {stop.stop_id} · Lat: {stop.lat?.toFixed(4)} · Lon: {stop.lon?.toFixed(4)}
      </div>

      {/* Routes serving this stop */}
      {stop.routes?.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: '#6b7280', marginBottom: 3 }}>
            Routes ({stop.routes.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {stop.routes.map(r => (
              <span key={r} style={{ background: '#e0e7ff', color: '#3730a3', borderRadius: 4, padding: '2px 6px', fontSize: 11, fontWeight: 600 }}>
                {r}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Buses currently at/near this stop */}
      {servingBuses.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: '#6b7280', marginBottom: 3 }}>
            Buses on Route ({servingBuses.length})
          </div>
          <div style={{ maxHeight: 120, overflowY: 'auto' }}>
            {servingBuses.map(b => (
              <div key={b.bus_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', borderBottom: '1px solid #f1f5f9' }}>
                <div>
                  <span style={{ fontWeight: 600 }}>{b.bus_id}</span>
                  <span style={{ color: '#6b7280', marginLeft: 6, fontSize: 10 }}>{b.reg_no}</span>
                </div>
                <div style={{ fontSize: 11 }}>
                  <span style={{ color: b.speed_kmh > 0 ? '#16a34a' : '#6b7280' }}>
                    {b.speed_kmh > 0 ? `${b.speed_kmh.toFixed(0)} km/h` : 'stopped'}
                  </span>
                  <span style={{ marginLeft: 6, color: '#6b7280' }}>
                    {b.occupancy?.passengers ?? '?'} pax
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Schedule (boarding by hour) */}
      {schedule.length > 0 && (
        <div>
          <div style={{ fontWeight: 600, fontSize: 11, textTransform: 'uppercase', color: '#6b7280', marginBottom: 3 }}>
            Boarding Schedule (peak hours)
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
            {schedule.map(s => {
              const h = s.hour
              const label = h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h-12}p`
              const intensity = Math.min(s.total / 30, 1)
              return (
                <div key={h} style={{
                  background: `rgba(0,51,102,${0.15 + intensity * 0.6})`,
                  color: intensity > 0.5 ? '#fff' : '#003366',
                  borderRadius: 4, padding: '2px 6px', fontSize: 10, fontWeight: 600,
                  minWidth: 36, textAlign: 'center',
                }}>
                  <div>{label}</div>
                  <div style={{ fontSize: 9 }}>{s.total} pax</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {loading && <div style={{ color: '#6b7280', fontSize: 11 }}>Loading stop details…</div>}
    </div>
  )
}

export default function FleetMap({
  buses = [],
  defects = [],
  onSelectBus,
  selectedBusId = null,
  height = 460,
  showDefects = false,
  routePath = null,
  activeLeg = null,
  showMtcRoutes = false,
  showMtcStops = false,
  selectedRouteId = null,
  onSelectRoute = null,
  routePolylines = null,
  allRoutesPolylines = null,
  showHospitals = false,
  showFireStations = false,
  showPoliceStations = false,
  showTrafficPolice = false,
  onSelectFacility = null,
  hotspots = [],
  focusStop = null,
  heatmap = null,
}) {
  const { isLive } = useMode()
  const [mtcRoutes, setMtcRoutes] = useState([])
  const [mtcStops, setMtcStops] = useState([])
  const [selectedRouteDetail, setSelectedRouteDetail] = useState(null)
  const [hospitals, setHospitals] = useState([])
  const [fireStations, setFireStations] = useState([])
  const [policeStations, setPoliceStations] = useState([])
  const [trafficPolice, setTrafficPolice] = useState([])

  // Load MTC routes for the map
  useEffect(() => {
    if (showMtcRoutes && mtcRoutes.length === 0) {
      api.gtfsRoutes().then(d => {
        if (d?.routes) setMtcRoutes(d.routes)
      }).catch(() => {})
    }
  }, [showMtcRoutes, mtcRoutes.length])

  // Load MTC stops for the map
  useEffect(() => {
    if (showMtcStops && mtcStops.length === 0) {
      api.gtfsStops().then(d => {
        if (d?.stops) setMtcStops(d.stops)
      }).catch(() => {})
    }
  }, [showMtcStops, mtcStops.length])

  // Load selected route detail for polyline display
  useEffect(() => {
    if (selectedRouteId) {
      api.gtfsRouteDetail(selectedRouteId).then(d => {
        if (d?.polyline) setSelectedRouteDetail(d)
      }).catch(() => {})
    } else {
      setSelectedRouteDetail(null)
    }
  }, [selectedRouteId])

  // Load emergency facilities lazily
  useEffect(() => {
    if (showHospitals && hospitals.length === 0) {
      api.emergencyFacilities('hospital').then(d => {
        if (d?.facilities) setHospitals(d.facilities)
      }).catch(() => {})
    }
  }, [showHospitals, hospitals.length])

  useEffect(() => {
    if (showFireStations && fireStations.length === 0) {
      api.emergencyFacilities('fire').then(d => {
        if (d?.facilities) setFireStations(d.facilities)
      }).catch(() => {})
    }
  }, [showFireStations, fireStations.length])

  useEffect(() => {
    if (showPoliceStations && policeStations.length === 0) {
      api.emergencyFacilities('police').then(d => {
        if (d?.facilities) setPoliceStations(d.facilities)
      }).catch(() => {})
    }
  }, [showPoliceStations, policeStations.length])

  useEffect(() => {
    if (showTrafficPolice && trafficPolice.length === 0) {
      api.emergencyFacilities('traffic_police').then(d => {
        if (d?.facilities) setTrafficPolice(d.facilities)
      }).catch(() => {})
    }
  }, [showTrafficPolice, trafficPolice.length])

  // Filter buses with valid GPS positions
  const validBuses = buses.filter(b =>
    b.latitude != null && b.longitude != null &&
    !isNaN(b.latitude) && !isNaN(b.longitude)
  )

  // Calculate center based on valid buses or default
  const center = validBuses.length > 0
    ? [validBuses[0].latitude, validBuses[0].longitude]
    : DEFAULT_CENTER

  // Compute selected route polyline for fly-to
  const selectedPolyline = useMemo(() => {
    if (selectedRouteDetail?.polyline) return selectedRouteDetail.polyline
    if (routePath) return routePath
    return null
  }, [selectedRouteDetail, routePath])

  return (
    <>
      <style>{`
        /* Small red dot core: solid marker with a gentle pulse. */
        .dot-core {
          transform-box: fill-box;
          transform-origin: center;
          animation: dotPulse 1.6s ease-in-out infinite;
        }
        @keyframes dotPulse {
          0%, 100% { transform: scale(1); opacity: 0.85; }
          50%      { transform: scale(1.15); opacity: 0.60; }
        }
        /* Expanding red waves: three staggered ripple rings around every
           active congestion dot (radar-style). Opacity-only animation so it
           renders identically in every browser. */
        .wave-ring {
          transform-box: fill-box;
          transform-origin: center;
          animation: waveExpand 2.4s ease-out infinite;
        }
        .wave-ring.wv2 { animation-delay: 0.8s; }
        .wave-ring.wv3 { animation-delay: 1.6s; }
        @keyframes waveExpand {
          0%   { transform: scale(0.45); opacity: 0.95; }
          100% { transform: scale(1.25); opacity: 0; }
        }
        /* Big merged super-hotspot (6+ red dots within 200 m): BLINKS ONLY.
           A fixed 200 m ring whose fill pulses — no expanding waves, no
           moving parts, the ring never changes size. */
        .super-blink {
          transform-box: fill-box;
          transform-origin: center;
          animation: superBlink 1.1s steps(2, start) infinite;
        }
        @keyframes superBlink {
          0%, 49%  { opacity: 0.85; }
          50%, 100% { opacity: 0.18; }
        }
      `}</style>
      <MapContainer center={center} zoom={isLive && validBuses.length === 1 ? 15 : 11} style={{ minHeight: height, height: '100%', zIndex: 0 }}>
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapUpdater selectedRoutePolyline={selectedPolyline} focusStop={focusStop} />

        {/* Focused stop (from the MTC suggestion search) */}
        {focusStop && focusStop.lat != null && (
          <Marker position={[focusStop.lat, focusStop.lon]} icon={SELECTED_STOP_ICON}>
            <Tooltip direction="top" permanent>
              <div style={{ fontSize: 11, maxWidth: 200 }}>
                <strong>{focusStop.stop_name}</strong>
                {focusStop.routes?.length > 0 && (
                  <div style={{ color: '#003366', fontWeight: 600 }}>{focusStop.routes.slice(0, 5).join(', ')}</div>
                )}
              </div>
            </Tooltip>
          </Marker>
        )}

        {/* Traffic hotspots (5+ buses in a 150 m radius for >60 s): red dot
            core + expanding red wave rings. Merged zones (6+ red dots within
            200 m) render as ONE big ring that only BLINKS. */}
        {hotspots?.length > 0 && hotspots.map((h) => h.merged ? (
          <Fragment key={h.id}>
            {/* fixed 200 m zone boundary */}
            <Circle
              center={[h.latitude, h.longitude]}
              radius={h.radius_m || 200}
              pathOptions={{ color: '#b91c1c', weight: 2, fillColor: '#dc2626', fillOpacity: 0.10, opacity: 0.7 }}
            />
            {/* blinking fill — high red intensity, on/off only */}
            <Circle
              center={[h.latitude, h.longitude]}
              radius={h.radius_m || 200}
              pathOptions={{ color: 'transparent', weight: 0, fillColor: '#dc2626', fillOpacity: 0.45, className: 'super-blink' }}
            />
            <CircleMarker
              center={[h.latitude, h.longitude]}
              radius={22}
              pathOptions={{ color: 'transparent', weight: 0, fillOpacity: 0 }}
            >
              <Tooltip direction="top">
                <div style={{ fontSize: 11 }}>
                  <strong style={{ color: '#dc2626' }}>🔴 Major congestion zone</strong>
                  <div>{h.member_count} red dots merged (within 200 m)</div>
                  <div>{h.bus_count} buses stuck in this corridor</div>
                  {h.duration_sec != null && <div className="muted">active {Math.round(h.duration_sec)}s</div>}
                </div>
              </Tooltip>
            </CircleMarker>
          </Fragment>
        ) : (
          <Fragment key={h.id}>
            {/* expanding red waves (3 staggered ripple rings) */}
            {[['wv1', 55], ['wv2', 55], ['wv3', 55]].map(([cls, r]) => (
              <CircleMarker
                key={cls}
                center={[h.latitude, h.longitude]}
                radius={r}
                pathOptions={{ color: '#dc2626', weight: 4, fillColor: '#dc2626', fillOpacity: 0.22, className: `wave-ring ${cls}` }}
              />
            ))}
            {/* solid red dot core */}
            <CircleMarker
              center={[h.latitude, h.longitude]}
              radius={10}
              pathOptions={{ color: '#991b1b', weight: 2, fillColor: '#dc2626', fillOpacity: 1, className: 'dot-core' }}
            />
            <CircleMarker
              center={[h.latitude, h.longitude]}
              radius={20}
              pathOptions={{ color: 'transparent', weight: 0, fillOpacity: 0 }}
            >
              <Tooltip direction="top">
                <div style={{ fontSize: 11 }}>
                  <strong style={{ color: '#dc2626' }}>⚠ Traffic red dot</strong>
                  <div>{h.bus_count} buses in a 150 m radius</div>
                  {h.duration_sec != null && <div className="muted">active {Math.round(h.duration_sec)}s</div>}
                </div>
              </Tooltip>
            </CircleMarker>
          </Fragment>
        ))}

      {/* Congestion heat-map cells — translucent blue→red overlay. Built from
          current bus positions (positional, honest); intensity is normalized
          per data point. Cells only render when non-trivial data exists. */}
      {heatmap?.cells?.length > 0 && heatmap.cells.map((c, i) => {
        const f = Math.max(0, Math.min(1, c.intensity ?? 0))
        const color = f < 0.35 ? '#3b82f6' : f < 0.6 ? '#f59e0b' : '#ef4444'
        const radius = 14 + Math.round(26 * f)
        const opacity = 0.18 + 0.3 * f
        return (
          <CircleMarker
            key={`heat-${i}`}
            center={[c.lat, c.lon]}
            radius={radius}
            pathOptions={{ color: 'transparent', weight: 0, fillColor: color, fillOpacity: opacity }}
          >
            <Tooltip direction="top">
              <div style={{ fontSize: 11 }}>
                <strong>Congestion heat</strong>
                <div>{c.heat_buses} bus sample(s) in this cell</div>
                <div className="muted">intensity {Math.round(100 * (c.intensity ?? 0))}%</div>
              </div>
            </Tooltip>
          </CircleMarker>
        )
      })}

      {/* All-routes canvas layer (Route Map “All” button) — drawn beneath the
          SVG panes; the selected route is drawn on top as a normal SVG line. */}
      {allRoutesPolylines?.length > 0 && (
        <AllRoutesCanvas routes={allRoutesPolylines} onSelectRoute={onSelectRoute} />
      )}

      {/* Bulk pre-fetched route polylines (Route Map page) */}
      {routePolylines?.length > 0 && routePolylines.map((route) => (
        <RoutePolyline
          key={route.route_id}
          route={route}
          isSelected={selectedRouteId === route.route_id}
          onSelect={onSelectRoute}
        />
      ))}

      {/* MTC Route polylines */}
      {showMtcRoutes && mtcRoutes.slice(0, 200).map((route) => (
        <MtcRouteLine
          key={route.route_id}
          route={route}
          isSelected={selectedRouteId === route.route_id}
          onSelect={onSelectRoute}
        />
      ))}

      {/* Selected route detail polyline (thicker, highlighted). Skipped when
          bulk routePolylines are active — the selected one is already
          highlighted red there. */}
      {!routePolylines && !allRoutesPolylines && selectedRouteDetail?.polyline && selectedRouteDetail.polyline.length >= 2 && (
        <Polyline
          positions={selectedRouteDetail.polyline}
          pathOptions={{ color: '#4f46e5', weight: 5, opacity: 0.9 }}
        />
      )}

      {/* Selected route's stops */}
      {selectedRouteDetail?.stops?.length > 0 && selectedRouteDetail.stops.map((s) => (
        <Marker
          key={`sel-stop-${s.stop_id}`}
          position={[s.lat, s.lon]}
          icon={STOP_ICON}
        >
          <Tooltip direction="top">
            <div style={{ fontSize: 11, maxWidth: 200 }}>
              <strong>{s.stop_name}</strong>
              {s.arrival_time && <div style={{ color: '#6b7280' }}>sched. {s.arrival_time}</div>}
            </div>
          </Tooltip>
        </Marker>
      ))}

      {/* MTC Stop markers */}
      {showMtcStops && mtcStops.slice(0, 500).map((stop) => (
        <Marker
          key={stop.stop_id}
          position={[stop.lat, stop.lon]}
          icon={STOP_ICON}
        >
          <Tooltip direction="top" permanent={false} className="stop-tooltip">
            <div style={{ fontSize: 11, maxWidth: 180 }}>
              <strong>{stop.stop_name}</strong>
              <div style={{ color: '#6b7280' }}>ID: {stop.stop_id}</div>
              {stop.routes?.length > 0 && (
                <div style={{ color: '#003366', marginTop: 2, fontWeight: 600 }}>
                  {stop.routes.slice(0, 5).join(', ')}{stop.routes.length > 5 ? ` +${stop.routes.length - 5}` : ''}
                </div>
              )}
            </div>
          </Tooltip>
          <Popup maxWidth={320} minWidth={240}>
            <StopPopup stop={stop} buses={buses} />
          </Popup>
        </Marker>
      ))}

      {/* Existing route path (from BusDetails) — trip endpoints follow the
          current journey direction: origin shows as a blue "A" pin, the active
          destination as a red "B" pin. On the return trip they swap. */}
      {routePath && routePath.length >= 2 && !selectedRouteDetail && (() => {
        const selectedBus = buses.find((b) => b.bus_id === selectedBusId)
        const direction = selectedBus?.journey?.direction ?? 1
        const originIdx = direction === 1 ? 0 : routePath.length - 1
        const destIdx = direction === 1 ? routePath.length - 1 : 0
        return (
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
            <Marker position={routePath[originIdx]} icon={A_ICON}>
              <Tooltip direction="top">Origin · Point A</Tooltip>
            </Marker>
            <Marker position={routePath[destIdx]} icon={B_ICON}>
              <Tooltip direction="top">Destination · Point B</Tooltip>
            </Marker>
          </>
        )
      })()}

      {/* Road defect markers */}
      {showDefects && defects.map((d) => (
        <Marker key={d.defect_id} position={[d.latitude, d.longitude]} icon={DEFECT_ICON}>
          <Popup>
            <strong>{d.type}</strong>
            <div>detections: {d.detection_count}</div>
            <div>confidence: {Math.round((d.confidence || 0) * 100)}%</div>
            <div>seen by: {(d.buses || []).join(', ') || '—'}</div>
          </Popup>
        </Marker>
      ))}

      {/* Government Hospital markers */}
      {showHospitals && hospitals.map((h) => (
        <Marker key={h.facility_id} position={[h.latitude, h.longitude]} icon={HOSPITAL_ICON}>
          <Tooltip direction="top">
            <div style={{ fontSize: 11, maxWidth: 220 }}>
              <strong style={{ color: '#dc2626' }}>🏥 {h.name}</strong>
              <div style={{ color: '#6b7280', fontSize: 10 }}>{h.address || ''}</div>
            </div>
          </Tooltip>
          <Popup maxWidth={320}>
            <div style={{ fontSize: 12, fontFamily: 'system-ui', lineHeight: 1.6 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: '#dc2626', marginBottom: 6, borderBottom: '2px solid #dc2626', paddingBottom: 4 }}>🏥 {h.name}</div>
              <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Type:</strong> {h.type}</div>
              <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Category:</strong> <span style={{ color: '#dc2626', fontWeight: 600 }}>Government</span></div>
              {h.address && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Address:</strong> {h.address}</div>}
              {h.phone && h.phone !== 'NA' && (
                <div style={{ marginBottom: 2 }}>
                  <strong style={{ color: '#374151' }}>📞 Phone:</strong> 
                  <a href={`tel:${h.phone.replace(/[^0-9]/g, '')}`} style={{ color: '#dc2626', fontWeight: 600, marginLeft: 4 }}>{h.phone}</a>
                </div>
              )}
              {h.beds && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>🛏️ Beds:</strong> {h.beds}</div>}
              {h.emergency_available && (
                <div style={{ marginTop: 6, padding: '4px 8px', background: '#dcfce7', borderRadius: 4, color: '#166534', fontWeight: 600, fontSize: 11 }}>
                  ✓ Emergency Available 24/7
                </div>
              )}
              {h.specialties?.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <strong style={{ color: '#374151' }}>Specialties:</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {h.specialties.map((s, i) => (
                      <span key={i} style={{ background: '#fee2e2', color: '#991b1b', borderRadius: 4, padding: '2px 6px', fontSize: 10, fontWeight: 600 }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ marginTop: 8, padding: '6px 8px', background: '#fef2f2', borderRadius: 4, fontSize: 11 }}>
                <div style={{ color: '#991b1b', fontWeight: 600 }}>Emergency: <a href="tel:108" style={{ color: '#dc2626' }}>108</a> (Ambulance)</div>
                <div style={{ color: '#6b7280', marginTop: 2 }}>Source: {h.source}</div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}

      {/* Fire Station markers */}
      {showFireStations && fireStations.map((f) => (
        <Marker key={f.facility_id} position={[f.latitude, f.longitude]} icon={FIRE_ICON}>
          <Tooltip direction="top">
            <div style={{ fontSize: 11, maxWidth: 220 }}>
              <strong style={{ color: '#ea580c' }}>🚒 {f.name}</strong>
              <div style={{ color: '#6b7280', fontSize: 10 }}>{f.division || f.jurisdiction || ''}</div>
            </div>
          </Tooltip>
          <Popup maxWidth={300}>
            <div style={{ fontSize: 12, fontFamily: 'system-ui', lineHeight: 1.6 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: '#ea580c', marginBottom: 6, borderBottom: '2px solid #ea580c', paddingBottom: 4 }}>🚒 {f.name}</div>
              {f.division && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Division:</strong> <span style={{ color: '#c2410c', fontWeight: 600 }}>{f.division}</span></div>}
              {f.jurisdiction && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Jurisdiction:</strong> {f.jurisdiction}</div>}
              {f.phone && f.phone !== 'NA' && (
                <div style={{ marginBottom: 2 }}>
                  <strong style={{ color: '#374151' }}>📞 Phone:</strong> 
                  <a href={`tel:${f.phone.replace(/[^0-9]/g, '')}`} style={{ color: '#ea580c', fontWeight: 600, marginLeft: 4 }}>{f.phone}</a>
                </div>
              )}
              {f.phone_secondary && (
                <div style={{ marginBottom: 2 }}>
                  <strong style={{ color: '#374151' }}>📱 Officer Mobile:</strong> 
                  <a href={`tel:${f.phone_secondary.replace(/[^0-9]/g, '')}`} style={{ color: '#ea580c', fontWeight: 600, marginLeft: 4 }}>{f.phone_secondary}</a>
                </div>
              )}
              <div style={{ marginTop: 8, padding: '6px 8px', background: '#fff7ed', borderRadius: 4, fontSize: 11 }}>
                <div style={{ color: '#9a3412', fontWeight: 600 }}>Emergency: <a href="tel:101" style={{ color: '#dc2626' }}>101</a></div>
                <div style={{ color: '#6b7280', marginTop: 2 }}>Source: {f.source}</div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}

      {/* Police Station markers */}
      {showPoliceStations && policeStations.map((p) => (
        <Marker key={p.facility_id} position={[p.latitude, p.longitude]} icon={POLICE_ICON}>
          <Tooltip direction="top">
            <div style={{ fontSize: 11, maxWidth: 220 }}>
              <strong style={{ color: '#2563eb' }}>🚓 {p.name}</strong>
              <div style={{ color: '#6b7280', fontSize: 10 }}>{p.zone || p.jurisdiction || ''}</div>
            </div>
          </Tooltip>
          <Popup maxWidth={300}>
            <div style={{ fontSize: 12, fontFamily: 'system-ui', lineHeight: 1.6 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: '#2563eb', marginBottom: 6, borderBottom: '2px solid #2563eb', paddingBottom: 4 }}>🚓 {p.name}</div>
              {p.zone && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Zone:</strong> <span style={{ color: '#1d4ed8', fontWeight: 600 }}>{p.zone}</span></div>}
              {p.sub_division && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Sub Division:</strong> <span style={{ color: '#1d4ed8' }}>{p.sub_division}</span></div>}
              {p.jurisdiction && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Jurisdiction:</strong> {p.jurisdiction}</div>}
              {p.phone && p.phone !== 'NA' && (
                <div style={{ marginBottom: 2 }}>
                  <strong style={{ color: '#374151' }}>📞 Phone:</strong> 
                  <a href={`tel:${p.phone.replace(/[^0-9]/g, '')}`} style={{ color: '#2563eb', fontWeight: 600, marginLeft: 4 }}>{p.phone}</a>
                </div>
              )}
              {p.phone_secondary && (
                <div style={{ marginBottom: 2 }}>
                  <strong style={{ color: '#374151' }}>📞 Alternate:</strong> 
                  <a href={`tel:${p.phone_secondary.replace(/[^0-9]/g, '')}`} style={{ color: '#2563eb', fontWeight: 600, marginLeft: 4 }}>{p.phone_secondary}</a>
                </div>
              )}
              <div style={{ marginTop: 8, padding: '6px 8px', background: '#eff6ff', borderRadius: 4, fontSize: 11 }}>
                <div style={{ color: '#1e40af', fontWeight: 600 }}>Emergency: <a href="tel:100" style={{ color: '#dc2626' }}>100</a></div>
                <div style={{ color: '#6b7280', marginTop: 2 }}>Source: {p.source}</div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}

      {/* Traffic Police markers */}
      {showTrafficPolice && trafficPolice.map((t) => (
        <Marker key={t.facility_id} position={[t.latitude, t.longitude]} icon={TRAFFIC_ICON}>
          <Tooltip direction="top">
            <div style={{ fontSize: 11, maxWidth: 220 }}>
              <strong style={{ color: '#d97706' }}>🚦 {t.name}</strong>
              <div style={{ color: '#6b7280', fontSize: 10 }}>{t.jurisdiction || ''}</div>
            </div>
          </Tooltip>
          <Popup maxWidth={300}>
            <div style={{ fontSize: 12, fontFamily: 'system-ui', lineHeight: 1.6 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: '#d97706', marginBottom: 6, borderBottom: '2px solid #d97706', paddingBottom: 4 }}>🚦 {t.name}</div>
              <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Type:</strong> {t.type}</div>
              {t.jurisdiction && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Jurisdiction:</strong> <span style={{ color: '#b45309', fontWeight: 600 }}>{t.jurisdiction}</span></div>}
              {t.address && <div style={{ marginBottom: 2 }}><strong style={{ color: '#374151' }}>Address:</strong> {t.address}</div>}
              {t.phone && t.phone !== 'NA' && (
                <div style={{ marginBottom: 2 }}>
                  <strong style={{ color: '#374151' }}>📞 Phone:</strong> 
                  <a href={`tel:${t.phone.replace(/[^0-9]/g, '')}`} style={{ color: '#d97706', fontWeight: 600, marginLeft: 4 }}>{t.phone}</a>
                </div>
              )}
              <div style={{ marginTop: 8, padding: '6px 8px', background: '#fffbeb', borderRadius: 4, fontSize: 11 }}>
                <div style={{ color: '#92400e', fontWeight: 600 }}>Traffic Helpline: <a href="tel:04423452345" style={{ color: '#dc2626' }}>044-23452345</a></div>
                <div style={{ color: '#6b7280', marginTop: 2 }}>Source: {t.source}</div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}

      {/* Bus markers */}
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
              <div>driver: {b.driver?.name || b.driver?.state || '—'}</div>
              <div>passengers: {b.occupancy?.passengers ?? '—'}</div>
              <div>speed: {(b.speed_kmh ?? 0).toFixed(0)} km/h</div>
            </Popup>
          </Marker>
        )
      })}
      </MapContainer>
    </>
  )
}

// Lazy-loaded route line component (fetches polyline on demand)
function MtcRouteLine({ route, isSelected, onSelect }) {
  const [polyline, setPolyline] = useState(null)

  useEffect(() => {
    if (isSelected && !polyline) {
      api.gtfsRouteDetail(route.route_id).then(d => {
        if (d?.polyline) setPolyline(d.polyline)
      }).catch(() => {})
    }
  }, [isSelected, polyline, route.route_id])

  if (!isSelected && !polyline) return null

  const positions = polyline || []
  if (positions.length < 2) return null

  return (
    <Polyline
      positions={positions}
      pathOptions={{
        color: isSelected ? '#4f46e5' : '#94a3b8',
        weight: isSelected ? 4 : 2,
        opacity: isSelected ? 0.9 : 0.4,
      }}
      eventHandlers={onSelect ? { click: () => onSelect(route.route_id) } : undefined}
    />
  )
}

// Pre-fetched clickable route polyline (used by the Route Map page where the
// polylines are loaded in bulk from /api/gtfs/routes/polylines).
function RoutePolyline({ route, isSelected, onSelect }) {
  const positions = route.polyline
  if (!positions || positions.length < 2) return null
  return (
    <>
      {/* fat invisible hit area so thin route lines are easy to click */}
      <Polyline
        positions={positions}
        pathOptions={{ color: 'transparent', weight: 12, opacity: 0 }}
        eventHandlers={{ click: () => onSelect?.(route.route_id) }}
      />
      <Polyline
        positions={positions}
        pathOptions={{
          color: isSelected ? '#dc2626' : '#94a3b8',
          weight: isSelected ? 5 : 2,
          opacity: isSelected ? 0.95 : 0.45,
        }}
        eventHandlers={{ click: () => onSelect?.(route.route_id) }}
      />
    </>
  )
}

// Draws every route polyline on a single Leaflet canvas renderer. A canvas
// renderer handles thousands of lines efficiently (an SVG per route would
// freeze the browser). The selected route is NOT drawn here — it is drawn as
// a regular SVG polyline on top so selection changes don't rebuild the canvas.
function AllRoutesCanvas({ routes, onSelectRoute }) {
  const map = useMap()
  // Keep the callback in a ref so changing it doesn't rebuild thousands of
  // canvas lines (the parent re-creates the arrow function on each render).
  const onSelectRef = useRef(onSelectRoute)
  useEffect(() => { onSelectRef.current = onSelectRoute }, [onSelectRoute])

  useEffect(() => {
    if (!map || !routes || routes.length === 0) return
    if (!map.getPane('routes-canvas')) {
      map.createPane('routes-canvas')
      map.getPane('routes-canvas').style.zIndex = 390 // below SVG overlay pane (400)
    }
    const pane = map.getPane('routes-canvas')
    const renderer = L.canvas({ pane: 'routes-canvas', padding: 0.3 })
    const layers = []
    for (const r of routes) {
      const pts = r.polyline
      if (!pts || pts.length < 2) continue
      const line = L.polyline(pts, {
        renderer,
        color: '#64748b',
        weight: 1.5,
        opacity: 0.35,
        interactive: true,
      })
      line.on('click', () => onSelectRef.current?.(r.route_id))
      line.addTo(map)
      layers.push(line)
    }
    return () => {
      layers.forEach((l) => map.removeLayer(l))
      pane.querySelectorAll('canvas').forEach((c) => c.remove())
    }
  }, [map, routes])
  return null
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
