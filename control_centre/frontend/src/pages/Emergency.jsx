import { useEffect, useMemo, useState } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatCard } from '../components/UI.jsx'
import SuggestSearch from '../components/SuggestSearch.jsx'

/**
 * Emergency Intelligence — dedicated operations page for the emergency_engine.
 * Backend live (11x /api/emergency/*); operator surface: facility counts,
 * nearby search, facility directory with grouped suggestions
 * (hospital / police / fire / traffic / bus route / stop), incident
 * response recommendation, transport impact, emergency contacts.
 */

/* ─── icons per catalogue kind / facility type ─── */
const KIND_ICON = {
  hospital: '🏥',
  police: '🚔',
  fire: '🚒',
  traffic_police: '🚦',
  route: '🚌',
  stop: '📍',
}
const KIND_LABEL = {
  hospital: 'Hospital',
  police: 'Police',
  fire: 'Fire',
  traffic_police: 'Traffic Police',
  route: 'Bus Route',
  stop: 'Stop',
}
function facilityIcon(f) {
  const t = String(f?.type || '').toLowerCase()
  const c = String(f?.category || '').toLowerCase()
  if (t.includes('police') || c.includes('police')) return t.includes('traffic') || c.includes('traffic') ? '🚦' : '🚔'
  if (t.includes('fire') || c.includes('fire')) return '🚒'
  return '🏥'
}
function facilityKind(f) {
  const t = String(f?.type || '').toLowerCase()
  const c = String(f?.category || '').toLowerCase()
  if (t.includes('traffic') || c.includes('traffic')) return 'traffic_police'
  if (t.includes('police') || c.includes('police')) return 'police'
  if (t.includes('fire') || c.includes('fire')) return 'fire'
  return 'hospital'
}

export default function Emergency() {
  const { data: summary } = usePoll(api.emergencySummary, 30000)
  const { data: contactsData } = usePoll(api.emergencyContacts, 60000)
  const { data: facilitiesData } = usePoll(() => api.emergencyFacilities(), 60000)

  const [lat, setLat] = useState('13.0827')
  const [lon, setLon] = useState('80.2707')
  const [nearby, setNearby] = useState(null)
  const [nearbyLoading, setNearbyLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [severity, setSeverity] = useState('CRITICAL')
  const [incidentType, setIncidentType] = useState('CRASH')
  const [response, setResponse] = useState(null)
  const [responseLoading, setResponseLoading] = useState(false)
  const [impact, setImpact] = useState(null)
  const [picked, setPicked] = useState(null)

  /* ─── suggestion catalogue: facilities + bus routes + stops ─── */
  const [gtfsRoutes, setGtfsRoutes] = useState([])
  const [gtfsStops, setGtfsStops] = useState([])
  useEffect(() => {
    api.gtfsRoutes().then((d) => { if (d?.routes) setGtfsRoutes(d.routes.slice(0, 400)) }).catch(() => {})
    api.gtfsStops().then((d) => { if (d?.stops) setGtfsStops(d.stops.slice(0, 800)) }).catch(() => {})
  }, [])

  const facilities = facilitiesData?.facilities || []
  const suggestionItems = useMemo(() => {
    const fac = facilities.map((f) => {
      const kind = facilityKind(f)
      return {
        key: `fac-${f.facility_id}`,
        kind,
        label: f.name,
        sublabel: `${KIND_LABEL[kind]} · ${f.address || f.jurisdiction || ''}`,
        keywords: `${f.facility_id || ''} ${f.type || ''} ${f.address || ''} ${f.jurisdiction || ''}`,
        raw: f,
      }
    })
    const routes = gtfsRoutes.map((r) => ({
      key: `route-${r.route_id}`,
      kind: 'route',
      label: String(r.route_short_name || r.route_id),
      sublabel: `Bus Route · ${r.route_long_name || ''}`,
      keywords: `${r.route_id || ''} ${r.route_long_name || ''}`,
      raw: r,
    }))
    const stops = gtfsStops.map((s) => ({
      key: `stop-${s.stop_id}`,
      kind: 'stop',
      label: s.stop_name,
      sublabel: `Stop · ${(s.routes || []).slice(0, 4).join(', ') || s.stop_id || ''}`,
      keywords: `${s.stop_id || ''} ${(s.routes || []).join(' ')}`,
      raw: s,
    }))
    return [...fac, ...routes, ...stops]
  }, [facilities, gtfsRoutes, gtfsStops])

  async function findNearby(la = lat, lo = lon) {
    setNearbyLoading(true)
    try {
      const d = await api.emergencyNearby(parseFloat(la), parseFloat(lo), null, 5)
      setNearby(d)
    } catch (e) { setNearby({ error: String(e.message || e) }) }
    finally { setNearbyLoading(false) }
  }

  async function search(q = query) {
    if (!String(q).trim()) return
    try {
      const d = await api.emergencySearch(String(q).trim())
      setSearchResults(d)
    } catch (e) { setSearchResults({ error: String(e.message || e) }) }
  }

  /* picking a suggestion centres the op: facilities jump the lat/lon + nearby,
     routes/stops filter the directory + show their info banner */
  function onPick(item) {
    setPicked(item)
    if (['hospital', 'police', 'fire', 'traffic_police'].includes(item.kind)) {
      const f = item.raw
      setQuery(f.name)
      if (f.latitude && f.longitude) {
        setLat(String(f.latitude))
        setLon(String(f.longitude))
        findNearby(String(f.latitude), String(f.longitude))
      }
      search(f.name)
    } else {
      setQuery(item.label)
      setSearchResults(null)
    }
  }

  async function getResponse() {
    setResponseLoading(true)
    try {
      const d = await api.emergencyIncidentResponse({
        lat: parseFloat(lat), lon: parseFloat(lon),
        severity, incident_type: incidentType,
      })
      setResponse(d)
    } catch (e) { setResponse({ error: String(e.message || e) }) }
    finally { setResponseLoading(false) }
  }

  async function getImpact() {
    try {
      const d = await api.emergencyTransportImpact(parseFloat(lat), parseFloat(lon), 3)
      setImpact(d)
    } catch (e) { setImpact({ error: String(e.message || e) }) }
  }

  const nearbyList = nearby?.facilities || []
  const contacts = contactsData?.contacts || []
  const grouped = searchResults && !searchResults.error
    ? [
      ...(searchResults.hospitals || []).map((f) => ({ ...f, _g: 'hospital' })),
      ...(searchResults.police_stations || []).map((f) => ({ ...f, _g: 'police' })),
      ...(searchResults.fire_stations || []).map((f) => ({ ...f, _g: 'fire' })),
      ...(searchResults.traffic_police || []).map((f) => ({ ...f, _g: 'traffic_police' })),
      ...((searchResults.facilities || searchResults.results || []).map((f) => ({ ...f, _g: f._g || facilityKind(f) }))),
    ]
    : null
  // live local filter of the full directory as the operator types
  const q = query.trim().toLowerCase()
  const localFiltered = !searchResults && q
    ? facilities.filter((f) => `${f.name} ${f.type} ${f.address || ''} ${f.facility_id}`.toLowerCase().includes(q))
    : facilities
  const directoryList = (grouped || localFiltered).slice(0, 8)

  return (
    <>
      <PageHeader
        title="🆘 Emergency Intelligence"
        sub="Nearby facilities · incident response · transport impact · contacts (rule-based, Chennai facilities)"
        right={<SimBadge />}
      />

      {/* Summary counts — engine is live */}
      <div className="grid grid-4 mb-16">
        <StatCard label="🏥 Hospitals" value={summary?.hospitals ?? '…'} tone="red" />
        <StatCard label="🚒 Fire Stations" value={summary?.fire_stations ?? '…'} tone="amber" />
        <StatCard label="🚔 Police Stations" value={summary?.police_stations ?? '…'} tone="blue" />
        <StatCard label="🚦 Total Facilities" value={summary?.total_facilities ?? '…'} tone="green" />
      </div>
      <div className="muted mb-16" style={{ fontSize: 11 }}>
        {summary?.source ? `Source: ${summary.source} · ` : ''}Scope: {summary?.scope || 'Chennai Metropolitan Area'} · rule-based engine, straight-line distances.
      </div>

      {/* Nearby + incident response */}
      <div className="card mb-16">
        <div className="card-header"><h3 className="card-title">📍 Nearby Facilities &amp; Incident Response</h3></div>
        <div className="flex gap-8 wrap" style={{ marginBottom: 8 }}>
          <label className="muted" style={{ fontSize: 12 }}>Lat <input value={lat} onChange={(e) => setLat(e.target.value)} style={{ width: 90 }} /></label>
          <label className="muted" style={{ fontSize: 12 }}>Lon <input value={lon} onChange={(e) => setLon(e.target.value)} style={{ width: 90 }} /></label>
          <label className="muted" style={{ fontSize: 12 }}>Severity
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option>CRITICAL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option>
            </select>
          </label>
          <label className="muted" style={{ fontSize: 12 }}>Type
            <select value={incidentType} onChange={(e) => setIncidentType(e.target.value)}>
              <option>CRASH</option><option>CABIN_FIRE</option><option>DRIVER_DROWSINESS</option><option>OVERLOAD</option><option>POTHOLE</option><option>EMERGENCY_SIREN</option>
            </select>
          </label>
          <button className="btn btn-sm" onClick={() => findNearby()} disabled={nearbyLoading}>{nearbyLoading ? 'Searching…' : 'Find Nearby'}</button>
          <button className="btn btn-sm" onClick={getResponse} disabled={responseLoading}>{responseLoading ? 'Working…' : 'Get Response Plan'}</button>
          <button className="btn btn-sm btn-ghost" onClick={getImpact}>Transport Impact</button>
        </div>

        {nearbyList.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
            {nearbyList.slice(0, 6).map((f) => (
              <div key={f.facility_id} style={{ fontSize: 12, padding: '5px 8px', background: '#f8fafc', borderRadius: 4 }}>
                <span style={{ marginRight: 6 }}>{facilityIcon(f)}</span>
                <strong>{f.name}</strong> <span className="muted">· {f.type} · {f.distance_km?.toFixed?.(1) ?? '?'} km · {f.phone}</span>
              </div>
            ))}
          </div>
        )}
        {response && !response.error && (
          <div style={{ fontSize: 12, background: '#fef2f2', borderLeft: '3px solid #dc2626', borderRadius: 4, padding: '8px 10px', marginBottom: 8 }}>
            <strong>🚨 Response plan ({response.severity || severity})</strong>
            {response.recommended_facilities?.length > 0 && (
              <div className="muted">Recommended: {response.recommended_facilities.slice(0, 3).map((f) => f.name || f.facility_id).join(' · ')}</div>
            )}
            {response.actions?.length > 0 && (
              <div className="muted">Actions: {response.actions.slice(0, 3).join(' · ')}</div>
            )}
            {!response.recommended_facilities && !response.actions && (
              <div className="muted">{JSON.stringify(response).slice(0, 300)}</div>
            )}
          </div>
        )}
        {(nearby?.error || response?.error) && (
          <div style={{ fontSize: 12, color: '#dc2626' }}>{nearby?.error || response?.error}</div>
        )}
        {impact && !impact.error && (
          <div className="muted" style={{ fontSize: 12 }}>
            🚌 Affected routes: {(impact.affected_routes || []).slice(0, 5).join(', ') || 'none'} · Affected buses: {(impact.affected_buses || []).length ?? 0}
          </div>
        )}
      </div>

      {/* Directory search with grouped suggestions */}
      <div className="card mb-16">
        <div className="card-header"><h3 className="card-title">🏥 Facility Directory</h3><span className="badge badge-blue" style={{ fontSize: 10 }}>{facilitiesData?.count ?? facilities.length} LOADED</span></div>
        <SuggestSearch
          items={suggestionItems}
          placeholder="Type to get suggestions — hospital · police · fire · bus route · stop…"
          onQuery={(v) => { setQuery(v); setSearchResults(null) }}
          onSelect={onPick}
          maxResults={9}
        />
        <div className="muted" style={{ fontSize: 10, margin: '4px 0 8px' }}>
          Suggestions are grouped: {['hospital', 'police', 'fire', 'traffic_police', 'route', 'stop'].map((k) => `${KIND_ICON[k]} ${KIND_LABEL[k]}`).join(' · ')}
        </div>
        {picked && (
          <div style={{ fontSize: 12, background: '#eff6ff', borderLeft: '3px solid #2563eb', borderRadius: 4, padding: '6px 10px', marginBottom: 8 }}>
            <span style={{ marginRight: 6 }}>{KIND_ICON[picked.kind] || '🔍'}</span>
            <strong>{picked.label}</strong> <span className="muted">· {KIND_LABEL[picked.kind]} · {picked.sublabel}</span>
            {picked.kind === 'route' && picked.raw?.route_long_name && (
              <span className="muted"> · {picked.raw.route_long_name}</span>
            )}
            <button className="btn btn-sm btn-ghost" style={{ marginLeft: 8 }} onClick={() => { setPicked(null); setQuery(''); setSearchResults(null) }}>Clear</button>
          </div>
        )}
        <div className="flex gap-8" style={{ marginBottom: 8 }}>
          <button className="btn btn-sm" onClick={() => search()}>Search Directory</button>
        </div>
        {directoryList.map((f) => (
          <div key={f.facility_id || f.key} style={{ fontSize: 12, padding: '5px 8px', borderBottom: '1px solid var(--border)' }}>
            <span style={{ marginRight: 6 }}>{facilityIcon(f)}</span>
            <strong>{f.name}</strong> <span className="muted">· {f.type} · {f.address || f.jurisdiction || ''} · {f.phone}</span>
          </div>
        ))}
        {directoryList.length === 0 && (
          <div className="muted" style={{ fontSize: 12 }}>No matches — try a hospital name, police station, area (Guindy), or bus route number.</div>
        )}
      </div>

      {/* Contacts */}
      <div className="card mb-16">
        <div className="card-header"><h3 className="card-title">☎️ Emergency Contacts</h3></div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {contacts.map((c) => (
            <span key={c.phone + c.name} className="badge badge-red" style={{ fontSize: 11 }}>☎️ {c.name}: {c.phone}</span>
          ))}
        </div>
      </div>
    </>
  )
}
