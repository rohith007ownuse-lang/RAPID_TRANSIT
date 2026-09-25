import { StatusBadge } from './UI.jsx'
import ReviewEditor from './ReviewStatus.jsx'

const TYPE_LABEL = {
  DRIVER_DROWSINESS: 'Driver Drowsiness',
  DRIVER_ALERT: 'Driver Alert (cabin)',
  POTHOLE: 'Pothole / Road Defect',
  CRASH: 'Possible Crash / Impact',
  CABIN_FIRE: 'Cabin Fire',
  CABIN_SMOKE: 'Cabin Smoke',
  CABIN_INCIDENT: 'Cabin Incident',
  EMERGENCY_SIREN: 'Emergency Siren',
  OVERLOAD: 'Overload',
  VEHICLE_ANOMALY: 'Vehicle Anomaly',
}

export function eventLabel(type) {
  return TYPE_LABEL[type] || type
}

function timeText(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

export default function AlertFeed({ events = [], max = 40, onAcknowledge, header = 'Live Alerts', editable = false, onItemClick, busNames = {} }) {
  return (
    <div className="card">
      <div className="card-header">
        <h3 className="card-title">{header}</h3>
        <span className="muted" style={{ fontSize: 12 }}>{events.length} shown · click any alert to open the bus</span>
      </div>
      <div className="alert-feed">
        {events.length === 0 && <div className="empty">No active alerts.</div>}
        {events.slice(0, max).map((e) => (
          <div
            key={e.event_id}
            className={`alert-item sev-${e.severity}${onItemClick ? ' alert-click' : ''}`}
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
            {editable ? (
              <div className="mt-8" onClick={(ev) => ev.stopPropagation()}>
                <ReviewEditor event={e} />
              </div>
            ) : onAcknowledge && e.status === 'ACTIVE' ? (
              <div className="mt-8">
                <button className="btn" style={{ fontSize: 12, padding: '4px 10px' }} onClick={() => onAcknowledge(e.event_id)}>
                  Acknowledge
                </button>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}