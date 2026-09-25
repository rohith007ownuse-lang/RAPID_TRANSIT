import React from 'react'
import { usePoll, api } from '../api'

const SEV_COLORS = {
  CRITICAL: '#dc2626',
  HIGH: '#ea580c',
  MEDIUM: '#d97706',
  LOW: '#2563eb',
  INFO: '#6b7280',
}

const CONF_COLORS = {
  HIGH: '#16a34a',
  MEDIUM: '#d97706',
  LOW: '#dc2626',
}

function ConfidenceBadge({ confidence }) {
  const level = confidence >= 0.85 ? 'HIGH' : confidence >= 0.65 ? 'MEDIUM' : 'LOW'
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: '12px',
      fontSize: '11px',
      fontWeight: 600,
      color: '#fff',
      background: CONF_COLORS[level] || '#6b7280',
    }}>
      {Math.round(confidence * 100)}% {level}
    </span>
  )
}

function SourceBadge({ source }) {
  const colors = {
    camera_pothole: '#7c3aed',
    camera_cabin: '#dc2626',
    camera_driver: '#2563eb',
    gps: '#16a34a',
    traffic: '#d97706',
    vehicle_health: '#ea580c',
    vehicle_load: '#dc2626',
    road_risk: '#9333ea',
    event: '#6b7280',
  }
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 6px',
      borderRadius: '4px',
      fontSize: '10px',
      fontWeight: 500,
      color: '#fff',
      background: colors[source] || '#6b7280',
      marginRight: '4px',
    }}>
      {source}
    </span>
  )
}

function FusedEventCard({ event }) {
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div style={{
      border: `2px solid ${SEV_COLORS[event.severity] || '#d97706'}`,
      borderRadius: '8px',
      padding: '12px',
      marginBottom: '8px',
      background: '#fff',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontWeight: 600, fontSize: '13px' }}>{event.title}</span>
          <span style={{ marginLeft: '8px', fontSize: '11px', color: '#6b7280' }}>
            {event.event_type}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <span style={{
            padding: '2px 8px',
            borderRadius: '12px',
            fontSize: '11px',
            fontWeight: 600,
            color: '#fff',
            background: SEV_COLORS[event.severity] || '#d97706',
          }}>
            {event.severity}
          </span>
          <ConfidenceBadge confidence={event.confidence} />
        </div>
      </div>

      <div style={{ marginTop: '6px', fontSize: '12px', color: '#374151' }}>
        {event.description}
      </div>

      <div style={{ marginTop: '6px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
        {event.sources?.map((s, i) => (
          <SourceBadge key={i} source={s.type} />
        ))}
        <span style={{ fontSize: '10px', color: '#6b7280', alignSelf: 'center', marginLeft: '4px' }}>
          {event.source_count} source{event.source_count !== 1 ? 's' : ''}
        </span>
      </div>

      <div style={{ marginTop: '6px', fontSize: '11px', color: '#6b7280' }}>
        Bus: {event.bus_id} | {event.latitude?.toFixed(4)}, {event.longitude?.toFixed(4)}
      </div>

      {event.evidence_chain?.length > 0 && (
        <div style={{ marginTop: '8px' }}>
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              background: 'none',
              border: '1px solid #d1d5db',
              borderRadius: '4px',
              padding: '2px 8px',
              fontSize: '11px',
              cursor: 'pointer',
              color: '#374151',
            }}
          >
            {expanded ? 'Hide' : 'Show'} Evidence Chain ({event.evidence_chain.length} steps)
          </button>

          {expanded && (
            <div style={{ marginTop: '6px', padding: '8px', background: '#f9fafb', borderRadius: '4px' }}>
              {event.evidence_chain.map((e, i) => (
                <div key={i} style={{ fontSize: '11px', marginBottom: '4px', display: 'flex', gap: '8px' }}>
                  <span style={{ fontWeight: 600, color: '#6b7280' }}>Step {e.step}:</span>
                  <span style={{ fontWeight: 500 }}>{e.source}</span>
                  <span style={{ color: '#374151' }}>{e.detection}</span>
                  {e.confidence && (
                    <span style={{ color: '#6b7280' }}>({Math.round(e.confidence * 100)}%)</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function FusionPanel() {
  const [events, setEvents] = React.useState([])
  const [stats, setStats] = React.useState(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [evts, st] = await Promise.all([api.fusionEvents(), api.fusionStats()])
        if (alive) {
          setEvents(evts?.events || [])
          setStats(st)
          setLoading(false)
        }
      } catch (e) {
        if (alive) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (loading) return <div style={{ padding: 16 }}>Loading fusion data...</div>

  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>
        Multi-Source Fusion Events
      </h3>

      {stats && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '8px',
          marginBottom: '16px',
        }}>
          {[
            { label: 'Total Signals', value: stats.total_signals || 0 },
            { label: 'Total Fusions', value: stats.total_fusions || 0 },
            { label: 'Active Events', value: stats.active_fused_events || 0 },
            { label: 'Recent Signals', value: stats.recent_signals || 0 },
          ].map((item, i) => (
            <div key={i} style={{
              padding: '8px 12px',
              background: '#f3f4f6',
              borderRadius: '6px',
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '18px', fontWeight: 700 }}>{item.value}</div>
              <div style={{ fontSize: '11px', color: '#6b7280' }}>{item.label}</div>
            </div>
          ))}
        </div>
      )}

      {events.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: '#6b7280', fontSize: 13 }}>
          No fused events yet. Fusion engine activates when multiple data sources converge.
        </div>
      ) : (
        events.map((evt) => (
          <FusedEventCard key={evt.fusion_id} event={evt} />
        ))
      )}
    </div>
  )
}
