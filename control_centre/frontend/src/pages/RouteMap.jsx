import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import FleetMap from '../components/FleetMap.jsx'
import SuggestSearch from '../components/SuggestSearch.jsx'

const ROUTE_COLORS = [
  '#dc2626', '#2563eb', '#059669', '#d97706', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#ea580c', '#0d9488',
]

function colorForIndex(i) {
  return ROUTE_COLORS[i % ROUTE_COLORS.length]
}

const FACILITY_META = {
  hospital: { label: 'Hospital', emoji: '🏥' },
  fire: { label: 'Fire station', emoji: '🚒' },
  police: { label: 'Police station', emoji: '🚓' },
  traffic_police: { label: 'Traffic police', emoji: '🚦' },
}

export default function RouteMap() {
  const [summary, setSummary] = useState(null)
  const [allRoutes, setAllRoutes] = useState([])          // full catalog (no polylines)
  const [query, setQuery] = useState('')
  const [polylines, setPolylines] = useState([])          // visible polylines (with geometry)
  const [selectedRouteId, setSelectedRouteId] = useState(null)
  const [selectedDetail, setSelectedDetail] = useState(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingMap, setLoadingMap] = useState(false)
  const [error, setError] = useState(null)

  // “All routes” mode: draw every route path on one map (canvas layer)
  const [showAllRoutes, setShowAllRoutes] = useState(false)
  const [allPolylines, setAllPolylines] = useState(null)  // null = not loaded yet
  const [loadingAll, setLoadingAll] = useState(false)

  // Emergency facility layers (each toggles an independent map layer)
  const [showHospitals, setShowHospitals] = useState(false)
  const [showFireStations, setShowFireStations] = useState(false)
  const [showPoliceStations, setShowPoliceStations] = useState(false)
  const [showTrafficPolice, setShowTrafficPolice] = useState(false)

  // Facility catalogue for the suggestion search (loaded once)
  const [facilities, setFacilities] = useState([])

  // Route catalog + GTFS summary + facility catalog
  useEffect(() => {
    api.gtfsSummary().then(setSummary).catch(() => {})
    setLoadingList(true)
    api.gtfsRoutes()
      .then(d => setAllRoutes(d?.routes || []))
      .catch(e => setError(String(e.message || e)))
      .finally(() => setLoadingList(false))
    // Load all four facility types once so the suggestion search can offer
    // hospitals / fire / police / traffic stations by name.
    Promise.all([
      api.emergencyFacilities('hospital').catch(() => null),
      api.emergencyFacilities('fire').catch(() => null),
      api.emergencyFacilities('police').catch(() => null),
      api.emergencyFacilities('traffic_police').catch(() => null),
    ]).then(([h, f, p, t]) => {
      setFacilities([
        ...(h?.facilities || []).map(x => ({ ...x, _type: 'hospital' })),
        ...(f?.facilities || []).map(x => ({ ...x, _type: 'fire' })),
        ...(p?.facilities || []).map(x => ({ ...x, _type: 'police' })),
        ...(t?.facilities || []).map(x => ({ ...x, _type: 'traffic_police' })),
      ])
    })
  }, [])

  // SUGGESTION SEARCH — one catalogue of everything searchable above the map:
  // every MTC route (number + destination) and every hospital / fire /
  // police / traffic station. Typing the first characters suggests matches;
  // each extra character narrows the list.
  const searchItems = useMemo(() => {
    const items = []
    for (const r of allRoutes) {
      items.push({
        key: `route-${r.route_id}`,
        kind: 'route',
        label: r.route_short_name || r.route_id,
        sublabel: r.route_long_name || 'MTC route',
        keywords: `${r.route_id || ''} ${r.route_long_name || ''}`,
        routeId: r.route_id,
      })
    }
    for (const f of facilities) {
      const meta = FACILITY_META[f._type] || { label: f._type, emoji: '📍' }
      items.push({
        key: `fac-${f._type}-${f.facility_id}`,
        kind: 'facility',
        label: f.name || f.facility_id,
        sublabel: `${meta.emoji} ${meta.label}`,
        keywords: `${meta.label} ${f._type}`,
        facility: f,
      })
    }
    return items
  }, [allRoutes, facilities])

  // When a suggestion is picked:
  //   route    → select it (path + stops drawn, map flies to it)
  //   facility → turn on its layer and drop a focus pin
  const [focusFacility, setFocusFacility] = useState(null)
  const onPickSuggestion = (it) => {
    if (it.kind === 'route') {
      setFocusFacility(null)
      setSelectedRouteId(it.routeId)
      const r = allRoutes.find(x => x.route_id === it.routeId)
      if (r) setQuery(r.route_short_name || r.route_id)
    } else if (it.kind === 'facility') {
      const t = it.facility._type
      if (t === 'hospital') setShowHospitals(true)
      else if (t === 'fire') setShowFireStations(true)
      else if (t === 'police') setShowPoliceStations(true)
      else if (t === 'traffic_police') setShowTrafficPolice(true)
      setFocusFacility(it.facility)
    }
  }

  // Routes matching the search box (catalog metadata, instant)
  const filteredRoutes = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return allRoutes
    return allRoutes.filter(r =>
      (r.route_short_name || '').toLowerCase().includes(q) ||
      (r.route_long_name || '').toLowerCase().includes(q) ||
      (r.route_id || '').toLowerCase().includes(q)
    )
  }, [allRoutes, query])

  // Fetch polylines for the filtered routes (debounced).
  // Skipped while “All routes” mode is on — the whole network is drawn then.
  useEffect(() => {
    if (showAllRoutes) return
    let alive = true
    setLoadingMap(true)
    const t = setTimeout(() => {
      api.gtfsRoutePolylines(query.trim(), 60)
        .then(d => {
          if (!alive) return
          setPolylines(d?.polylines || [])
          // Drop selection if it's no longer visible in the filtered set
          setSelectedRouteId(prev => {
            if (!prev) return prev
            return (d?.polylines || []).some(p => p.route_id === prev) ? prev : null
          })
        })
        .catch(() => { if (alive) setPolylines([]) })
        .finally(() => { if (alive) setLoadingMap(false) })
    }, 350)
    return () => { alive = false; clearTimeout(t) }
  }, [query, showAllRoutes])

  // Load the full network once when “All routes” is switched on
  useEffect(() => {
    if (!showAllRoutes || allPolylines) return
    let alive = true
    setLoadingAll(true)
    api.gtfsRoutePolylines('', 5000)
      .then(d => { if (alive) setAllPolylines(d?.polylines || []) })
      .catch(() => { if (alive) { setAllPolylines([]); setShowAllRoutes(false) } })
      .finally(() => { if (alive) setLoadingAll(false) })
    return () => { alive = false }
  }, [showAllRoutes, allPolylines])

  // Load detail (stops etc.) whenever the selection changes. The detail's
  // stop-to-stop polyline is ALWAYS available for the selected route, so the
  // path connecting every stop dot is drawn even if the bulk polyline list
  // hasn't loaded or the route fell out of the filtered set.
  useEffect(() => {
    if (!selectedRouteId) { setSelectedDetail(null); return }
    let alive = true
    api.gtfsRouteDetail(selectedRouteId)
      .then(d => { if (alive) setSelectedDetail(d) })
      .catch(() => { if (alive) setSelectedDetail(null) })
    return () => { alive = false }
  }, [selectedRouteId])

  const selectedFromList = useMemo(
    () => filteredRoutes.find(r => r.route_id === selectedRouteId),
    [filteredRoutes, selectedRouteId]
  )
  const selectedName = selectedDetail?.route_short_name
    || selectedFromList?.route_short_name
    || selectedRouteId
  const selectedLongName = selectedDetail?.route_long_name
    || selectedFromList?.route_long_name
    || ''

  // In “All routes” mode the red highlight comes from the full-network data;
  // in search mode it comes from the per-search polylines. The selected
  // route's own detail polyline is the guaranteed fallback either way.
  const highlightRoutes = useMemo(() => {
    const base = showAllRoutes
      ? (allPolylines || []).filter(r => r.route_id === selectedRouteId)
      : polylines
    // Guarantee the selected route always has a drawn, connected path.
    if (selectedRouteId && selectedDetail?.polyline?.length >= 2
        && !base.some(p => p.route_id === selectedRouteId)) {
      return [...base, {
        route_id: selectedRouteId,
        route_short_name: selectedName,
        route_long_name: selectedLongName,
        polyline: selectedDetail.polyline,
      }]
    }
    return base
  }, [showAllRoutes, allPolylines, polylines, selectedRouteId, selectedDetail, selectedName, selectedLongName])

  return (
    <>
      <PageHeader
        title="Route Map · MTC Bus Routes"
        sub={summary?.loaded
          ? `${summary.routes?.toLocaleString()} routes · ${summary.stops?.toLocaleString()} stops · ${summary.agency || 'MTC'}`
          : 'Chennai Metropolitan Transport Corporation (GTFS)'}
        right={<SimBadge />}
      />

      {error && (
        <div className="card mb-16" style={{ color: 'var(--red)' }}>
          Cannot reach backend: {error}
        </div>
      )}

      {/* SUGGESTION SEARCH — above the map. Searches MTC routes by number or
          destination AND hospital / fire / police / traffic station names.
          First characters suggest; every extra character narrows the list. */}
      <div className="card mb-16">
        <SuggestSearch
          items={searchItems}
          placeholder="Search route (e.g. 72C, Koyambedu) or hospital / fire / police / traffic station…"
          onSelect={onPickSuggestion}
          maxResults={9}
          style={{ maxWidth: 640 }}
        />
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
          Routes fly the map to their path · facilities turn on their layer and drop a pin
        </div>
      </div>

      <div className="grid route-map-grid">
        {/* ── Route list / search panel ── */}
        <div className="card" style={{ maxHeight: 640, display: 'flex', flexDirection: 'column' }}>
          <div className="card-header">
            <h3 className="card-title">Routes</h3>
            <span className="badge badge-blue" style={{ fontSize: 10 }}>
              {loadingList ? '…' : `${filteredRoutes.length} routes`}
            </span>
          </div>

          {/* Layer controls */}
          <div style={{ padding: '8px 12px 0' }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
              Map Layers
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              <button
                onClick={() => setShowAllRoutes(v => !v)}
                disabled={loadingAll}
                style={{
                  fontSize: 11, padding: '5px 12px', borderRadius: 14, cursor: 'pointer',
                  border: showAllRoutes ? '1.5px solid #dc2626' : '1px solid var(--border)',
                  background: showAllRoutes ? 'rgba(220,38,38,.1)' : 'var(--bg)',
                  color: showAllRoutes ? '#dc2626' : 'var(--text)', fontWeight: 600,
                }}
                title="Draw every MTC route path on the map at once"
              >
                {loadingAll ? '⏳ loading…' : showAllRoutes ? '🌐 All Routes ✓' : '🌐 All Routes'}
              </button>
              <button
                onClick={() => setShowHospitals(v => !v)}
                style={{
                  fontSize: 11, padding: '5px 12px', borderRadius: 14, cursor: 'pointer',
                  border: showHospitals ? '1.5px solid #dc2626' : '1px solid var(--border)',
                  background: showHospitals ? 'rgba(220,38,38,.15)' : 'var(--bg)',
                  color: showHospitals ? '#dc2626' : 'var(--text)', fontWeight: showHospitals ? 600 : 400,
                }}
                title="Toggle government hospitals layer (20 facilities)"
              >
                🏥 Medical <span style={{ opacity: 0.7, fontSize: 10 }}>(20)</span>
              </button>
              <button
                onClick={() => setShowFireStations(v => !v)}
                style={{
                  fontSize: 11, padding: '5px 12px', borderRadius: 14, cursor: 'pointer',
                  border: showFireStations ? '1.5px solid #ea580c' : '1px solid var(--border)',
                  background: showFireStations ? 'rgba(234,88,12,.15)' : 'var(--bg)',
                  color: showFireStations ? '#ea580c' : 'var(--text)', fontWeight: showFireStations ? 600 : 400,
                }}
                title="Toggle fire stations layer (33 stations)"
              >
                🚒 Fire Safety <span style={{ opacity: 0.7, fontSize: 10 }}>(33)</span>
              </button>
              <button
                onClick={() => setShowPoliceStations(v => !v)}
                style={{
                  fontSize: 11, padding: '5px 12px', borderRadius: 14, cursor: 'pointer',
                  border: showPoliceStations ? '1.5px solid #2563eb' : '1px solid var(--border)',
                  background: showPoliceStations ? 'rgba(37,99,235,.15)' : 'var(--bg)',
                  color: showPoliceStations ? '#2563eb' : 'var(--text)', fontWeight: showPoliceStations ? 600 : 400,
                }}
                title="Toggle police stations layer (136 stations)"
              >
                🚓 Police <span style={{ opacity: 0.7, fontSize: 10 }}>(136)</span>
              </button>
              <button
                onClick={() => setShowTrafficPolice(v => !v)}
                style={{
                  fontSize: 11, padding: '5px 12px', borderRadius: 14, cursor: 'pointer',
                  border: showTrafficPolice ? '1.5px solid #d97706' : '1px solid var(--border)',
                  background: showTrafficPolice ? 'rgba(217,119,6,.15)' : 'var(--bg)',
                  color: showTrafficPolice ? '#d97706' : 'var(--text)', fontWeight: showTrafficPolice ? 600 : 400,
                }}
                title="Toggle traffic police layer (8 stations)"
              >
                🚦 Traffic <span style={{ opacity: 0.7, fontSize: 10 }}>(8)</span>
              </button>
            </div>
          </div>
          {showAllRoutes && (
            <div className="muted" style={{ fontSize: 10, padding: '6px 12px 0' }}>
              Showing the full route network — search &amp; click still work. Turn All Routes off to go back to the filtered view.
            </div>
          )}

          <div style={{ padding: '8px 12px 4px' }}>
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Filter the route list below…"
              className="input"
              style={{ width: '100%', fontSize: 12, padding: '6px 10px' }}
            />
            <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>
              {showAllRoutes
                ? `Full network: ${allPolylines?.length ?? '…'} route paths on map`
                : loadingMap
                  ? 'Loading route lines…'
                  : `${polylines.length} route lines shown on map${filteredRoutes.length > polylines.length ? ` (of ${filteredRoutes.length} matches)` : ''}`}
            </div>
          </div>

          <div style={{ overflowY: 'auto', flex: 1, padding: '4px 8px 10px' }}>
            {filteredRoutes.length === 0 && !loadingList && (
              <div className="muted" style={{ fontSize: 12, padding: 10 }}>
                No routes match “{query}”.
              </div>
            )}
            {filteredRoutes.slice(0, 300).map((r, i) => {
              const isSel = r.route_id === selectedRouteId
              return (
                <button
                  key={r.route_id}
                  onClick={() => setSelectedRouteId(isSel ? null : r.route_id)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '7px 10px', margin: '2px 0', borderRadius: 6,
                    border: isSel ? '1.5px solid #dc2626' : '1px solid transparent',
                    background: isSel ? 'rgba(220,38,38,.07)' : 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      width: 10, height: 10, borderRadius: 2, flexShrink: 0,
                      background: isSel ? '#dc2626' : colorForIndex(i),
                      opacity: isSel ? 1 : 0.75,
                    }} />
                    <strong style={{ fontSize: 13 }}>{r.route_short_name || r.route_id}</strong>
                    <span className="muted" style={{ fontSize: 10, marginLeft: 'auto', flexShrink: 0 }}>
                      {r.stop_count ?? '?'} stops
                    </span>
                  </div>
                  {(r.route_long_name || isSel) && (
                    <div className="muted" style={{
                      fontSize: 11, marginTop: 2, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {r.route_long_name}
                    </div>
                  )}
                </button>
              )
            })}
            {filteredRoutes.length > 300 && (
              <div className="muted" style={{ fontSize: 10, padding: '6px 10px' }}>
                +{filteredRoutes.length - 300} more — refine the search to see them
              </div>
            )}
          </div>
        </div>

        {/* ── Map ── */}
        <div className="card map-card">
          <div className="card-header">
            <h3 className="card-title">Map</h3>
            {selectedRouteId ? (
              <span className="badge badge-red" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
                Route: {selectedName}
                {selectedLongName && <span style={{ fontWeight: 400 }}>· {selectedLongName}</span>}
                <button
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: 11, padding: 0 }}
                  onClick={() => setSelectedRouteId(null)}
                  title="Clear selection"
                >
                  ✕
                </button>
              </span>
            ) : (
              <span className="muted" style={{ fontSize: 11 }}>
                Click a route in the list — or on the map — to highlight it
              </span>
            )}
          </div>

          <FleetMap
            height={560}
            routePolylines={highlightRoutes}
            allRoutesPolylines={showAllRoutes ? allPolylines : null}
            selectedRouteId={selectedRouteId}
            onSelectRoute={(id) => setSelectedRouteId(prev => (prev === id ? null : id))}
            showHospitals={showHospitals}
            showFireStations={showFireStations}
            showPoliceStations={showPoliceStations}
            showTrafficPolice={showTrafficPolice}
          />

          <div className="map-legend" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: '#64748b' }}>— route</span>
            <span style={{ fontSize: 10, color: '#dc2626', fontWeight: 700 }}>━ selected route</span>
            <span style={{ fontSize: 10, color: '#003366' }}>● route stops</span>
            {showHospitals && <span style={{ fontSize: 10 }}>🏥 hospital</span>}
            {showFireStations && <span style={{ fontSize: 10 }}>🚒 fire</span>}
            {showPoliceStations && <span style={{ fontSize: 10 }}>🚓 police</span>}
            {showTrafficPolice && <span style={{ fontSize: 10 }}>🚦 traffic</span>}
            {selectedDetail?.stops?.length > 0 && (
              <span className="muted" style={{ fontSize: 10 }}>
                {selectedName}: {selectedDetail.stops[0]?.stop_name} → {selectedDetail.stops[selectedDetail.stops.length - 1]?.stop_name} ({selectedDetail.stops.length} stops)
              </span>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
