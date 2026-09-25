import { StatusBadge } from './UI.jsx'
import ReviewEditor from './ReviewStatus.jsx'

const TYPE_LABEL = {
  DRIVER_DROWSINESS: 'Driver Drowsiness',
  DRIVER_ALERT: 'Driver Alert (cabin)',
  DRIVER_REFRESH_REQUIRED: 'Driver Refresh Required',
  POTHOLE: 'Pothole / Road Hazard',
  CRASH: 'Possible Crash / Impact',
  CABIN_FIRE: 'Cabin Fire',
  CABIN_SMOKE: 'Cabin Smoke',
  CABIN_INCIDENT: 'Cabin Incident',
  EMERGENCY_SIREN: 'Emergency Siren',
  OVERLOAD: 'Overload',
  POTHOLE_CLUSTER: 'Pothole / Road Hazard',
  ROAD_DEFECT: 'Road Defect',
  RISK_ESCALATION: 'Risk Escalation Prediction',
  CRITICAL_RISK: 'Critical Risk',
  RISK_STATE_CHANGE: 'Risk State Change',
}

// Live Alerts tiers (mirrors backend alerts.py policy):
//   CRITICAL — crash, driver drowsiness, smoke, fire. Pinned at the top and
//              only removed once acknowledged.
//   WARNING  — road hazards, overload, risk escalation predictions.
//   VEHICLE_ANOMALY and INFO items are never shown.
const CRITICAL_TYPES = new Set(['CRASH', 'DRIVER_DROWSINESS', 'CABIN_SMOKE', 'CABIN_FIRE'])
const HIDDEN_TYPES = new Set(['VEHICLE_ANOMALY'])

export function eventLabel(type) {
  return TYPE_LABEL[type] || type
}

export function alertTier(event) {
  if (!event) return 'WARNING'
  if (CRITICAL_TYPES.has((event.event_type || '').toUpperCase())) return 'CRITICAL'
  if (HIDDEN_TYPES.has((event.event_type || '').toUpperCase())) return 'HIDDEN'
  // an explicit backend tier wins for anything else
  if (event.tier === 'CRITICAL') return 'CRITICAL'
  return 'WARNING'
}

function timeText(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

function timeAgo(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

/**
 * Live Alerts feed.
 *
 *  - Only CRITICAL and WARNING tier items are rendered; VEHICLE_ANOMALY and
 *    INFO events never appear.
 *  - CRITICAL items are pinned at the top and STAY there (with a red
 *    "ACKNOWLEDGE REQUIRED" state) until they are acknowledged. Acknowledging
 *    is the only way they leave the pinned block.
 *  - Clicking an alert opens the vehicle's live feed page where the operator
 *    watches the feed and can acknowledge it there.
 *  - Every alert carries an "AI SUGGESTED" response banner: the suggested
 *    action the operator should take for that alert type.
 */
export default function AlertFeed({ events = [], max = 40, header = 'Live Alerts', editable = false, onItemClick, busNames = {} }) {
  const visible = events.filter((e) => {
    if (HIDDEN_TYPES.has((e.event_type || '').toUpperCase())) return false
    if ((e.severity || '').toUpperCase() === 'INFO') return false
    return true
  })

  const unackedCritical = visible.filter((e) => alertTier(e) === 'CRITICAL' && e.status === 'ACTIVE')
  const rest = visible.filter((e) => !(alertTier(e) === 'CRITICAL' && e.status === 'ACTIVE'))

  const renderItem = (e, pinned = false) => {
    const isCritical = alertTier(e) === 'CRITICAL'
    const acked = e.status === 'ACKNOWLEDGED' || e.status === 'RESOLVED'
    return (
      <div
        key={e.event_id}
        className={`alert-item sev-${e.severity}${onItemClick ? ' alert-click' : ''}`}
        style={pinned ? { borderLeft: '4px solid var(--red)', background: '#fff7f7' } : undefined}
        onClick={() => onItemClick && onItemClick(e)}
      >
        <div className="flex justify-between align-center">
          <span className="alert-title">{eventLabel(e.event_type)}</span>
          <StatusBadge status={e.severity} />
        </div>
        <div className="alert-meta">
          {busNames[e.bus_id] ? `driver ${busNames[e.bus_id]} · ` : ''}{e.bus_id} · {timeText(e.timestamp)}
          {e.status !== 'ACTIVE' && (
            <span className="muted"> · {e.status.toLowerCase()}</span>
          )}
        </div>
        {isCritical && !acked && (
          <div
            style={{
              marginTop: 6, fontSize: 10, fontWeight: 800, letterSpacing: '0.04em',
              color: '#b91c1c', display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            <span className="cc-pulse" /> ACKNOWLEDGE REQUIRED — stays pinned until acknowledged
          </div>
        )}
        {/* AI-suggested response banner */}
        <div
          className="ai-suggestion-banner"
          style={{
            marginTop: 6, fontSize: 11, lineHeight: 1.5,
            background: '#eef2ff', borderLeft: '3px solid #6366f1',
            borderRadius: 4, padding: '5px 8px', color: '#3730a3',
          }}
        >
          <span style={{ fontWeight: 700 }}>🤖 AI suggested:</span> {aiSuggestion(e)}
          <span className="muted" style={{ marginLeft: 6, fontSize: 10 }}>{timeAgo(e.timestamp)}</span>
        </div>
        {editable && (
          <div className="mt-8" onClick={(ev) => ev.stopPropagation()}>
            <ReviewEditor event={e} />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="card-title">{header}</h3>
        <span className="muted" style={{ fontSize: 12 }}>
          {unackedCritical.length > 0 && (
            <span className="badge badge-red" style={{ marginRight: 6 }}>{unackedCritical.length} critical</span>
          )}
          {rest.length} shown · click any alert to open the vehicle live feed
        </span>
      </div>
      <div className="alert-feed">
        {visible.length === 0 && <div className="empty">No active alerts.</div>}
        {/* pinned criticals — removed only via acknowledgement */}
        {unackedCritical.slice(0, max).map((e) => renderItem(e, true))}
        {unackedCritical.length > 0 && rest.length > 0 && (
          <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 4px' }}>
            — warnings —
          </div>
        )}
        {rest.slice(0, Math.max(0, max - Math.min(unackedCritical.length, max))).map((e) => renderItem(e))}
      </div>
    </div>
  )
}

/* Rule-based AI-suggested response per alert type (what the operator should do). */
function aiSuggestion(e) {
  const type = (e.event_type || '').toUpperCase()
  switch (type) {
    case 'CRASH':
      return 'Call the driver now, confirm passenger safety, and dispatch emergency response if confirmed.'
    case 'DRIVER_DROWSINESS':
      return 'Watch the live camera feed; if drowsiness is confirmed, order the driver to pull over at a safe stop and swap in a relief driver.'
    case 'CABIN_SMOKE':
      return 'Instruct the driver to stop and evacuate the cabin; notify fire services (101) and verify via cabin camera.'
    case 'CABIN_FIRE':
      return 'Immediate stop and evacuation; alert fire services (101) and track the nearest fire station on the map.'
    case 'POTHOLE':
    case 'POTHOLE_CLUSTER':
    case 'ROAD_DEFECT':
      return 'Flag the road segment for maintenance and check whether other buses on this route are exposed.'
    case 'OVERLOAD':
      return 'Deploy an additional bus on this route to ease the load and verify ticket-machine capacity data.'
    case 'RISK_ESCALATION':
    case 'CRITICAL_RISK':
    case 'RISK_STATE_CHANGE':
      return 'Open the bus risk breakdown, review the degrading factors, and assign an operator to monitor the vehicle.'
    default:
      return 'Open the vehicle live feed, verify the situation, and acknowledge once reviewed.'
  }
}
