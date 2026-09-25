import { useMemo, useState } from 'react'
import { usePoll, api } from '../api.js'
import { ReviewState } from './ReviewStatus.jsx'
import AcknowledgeModal from './AcknowledgeModal.jsx'

/**
 * RecentIncidents — minimalised list of this bus's recent incidents shown
 * beside the live map: incident name + when it started + operator watch
 * state, plus Acknowledge (popup) / Acknowledge All.
 *
 * Status dot legend (exactly per the operator spec):
 *   🔴 red    — critical incident, no one is watching yet
 *   🟠 amber  — operator is watching / reviewing
 *   🟢 green  — acknowledged (operator handled it)
 *   🔵 blue   — no active incidents (shows the last historical one)
 *
 * The dot combines severity (red vs non-red) with review state:
 *   ACTIVE + CRITICAL → red (needs watching, nobody on it)
 *   ACTIVE + other    → amber only when an operator is reviewing
 *   ACKNOWLEDGED/RESOLVED → green
 *   nothing recent    → blue (no incidents)
 */
function incidentDot(inc) {
  if (!inc) return 'blue'
  if (inc.status === 'ACKNOWLEDGED' || inc.status === 'RESOLVED' || inc.status === 'CLOSED') return 'green'
  if (inc.status === 'REVIEWING' || inc.status === 'INVESTIGATING' || inc.status === 'ASSIGNED' || inc.status === 'RESPONDING') return 'amber'
  // still ACTIVE / OPEN / DETECTED / CONFIRMED
  return inc.severity === 'CRITICAL' ? 'red' : 'amber'
}

const DOT_COLORS = {
  red: '#dc2626',
  amber: '#f59e0b',
  green: '#16a34a',
  blue: '#2563eb',
}

const DOT_HINT = {
  red: 'critical · no one watching yet',
  amber: 'operator is watching',
  green: 'acknowledged',
  blue: 'no incidents',
}

function whenText(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export default function RecentIncidents({ busId, busName, operator = 'Operator 1' }) {
  const { data, refetch } = usePoll(() => api.busIncidents(busId, 10), 6000, [busId])
  const incidents = useMemo(() => data?.incidents || [], [data])
  const [ackTarget, setAckTarget] = useState(null) // incident | 'ALL' | null

  const active = incidents.filter((i) => !['RESOLVED', 'CLOSED'].includes(i.status))
  const dot = incidents.length > 0 ? incidentDot(incidents[0]) : 'blue'
  const unacked = active.filter((i) => i.status !== 'ACKNOWLEDGED').length

  const submitAck = async (payload) => {
    try {
      if (ackTarget === 'ALL') {
        await Promise.all(
          unackedTargets().map((inc) =>
            api.acknowledgeIncident(inc.incident_id, { operator, ...payload }).catch(() => {})
          )
        )
      } else if (ackTarget) {
        await api.acknowledgeIncident(ackTarget.incident_id, { operator, ...payload })
      }
      refetch?.()
    } catch (err) {
      console.error('Acknowledge failed:', err)
    }
    setAckTarget(null)
  }

  const unackedTargets = () => active.filter((i) => i.status !== 'ACKNOWLEDGED')

  return (
    <div className="card mb-16">
      <div className="card-header">
        <h3 className="card-title">📋 Recent Incidents — {busName || busId}</h3>
        <div className="flex align-center gap-8">
          <span
            title={DOT_HINT[dot]}
            style={{
              width: 12, height: 12, borderRadius: '50%', background: DOT_COLORS[dot],
              display: 'inline-block', boxShadow: `0 0 6px ${DOT_COLORS[dot]}`,
            }}
          />
          <span className="muted" style={{ fontSize: 11 }}>{DOT_HINT[dot]}</span>
        </div>
      </div>

      {/* legend */}
      <div className="flex wrap gap-8" style={{ fontSize: 10.5, color: '#66727E', marginBottom: 8 }}>
        {Object.entries(DOT_HINT).map(([k, v]) => (
          <span key={k} className="flex align-center gap-4" style={{ gap: 4 }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: DOT_COLORS[k], display: 'inline-block' }} />
            {v}
          </span>
        ))}
      </div>

      {unacked > 1 && (
        <div style={{ marginBottom: 8 }}>
          <button
            className="btn btn-sm btn-ack"
            style={{ fontSize: 11 }}
            onClick={() => setAckTarget('ALL')}
          >
            ✓ Acknowledge all ({unacked})
          </button>
        </div>
      )}

      {incidents.length === 0 ? (
        <div className="empty" style={{ color: 'var(--accent)' }}>
          ● No incidents recorded recently for this bus.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {incidents.slice(0, 5).map((inc) => {
            const d = incidentDot(inc)
            const finished = inc.status === 'ACKNOWLEDGED' || inc.status === 'RESOLVED' || inc.status === 'CLOSED'
            return (
              <div
                key={inc.incident_id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '6px 10px', borderRadius: 6,
                  background: d === 'red' ? '#fef2f2' : d === 'amber' ? '#fffbeb' : '#f0fdf4',
                  borderLeft: `3px solid ${DOT_COLORS[d]}`,
                  fontSize: 12,
                }}
              >
                <span
                  title={DOT_HINT[d]}
                  style={{ width: 10, height: 10, borderRadius: '50%', background: DOT_COLORS[d], display: 'inline-block', flexShrink: 0 }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {inc.title || inc.category}
                  </div>
                  <div className="muted" style={{ fontSize: 10.5 }}>
                    started {whenText(inc.created_at)} · {inc.severity} · {inc.status.toLowerCase()}
                    {inc.status === 'REVIEWING' && inc.reviewed_by ? ` · ${inc.reviewed_by}` : ''}
                  </div>
                </div>
                {finished ? (
                  <ReviewState status={inc.status} />
                ) : (
                  <button
                    className="btn btn-sm btn-ack"
                    style={{ fontSize: 11, flexShrink: 0 }}
                    onClick={() => setAckTarget(inc)}
                  >
                    ✓ Acknowledge
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Acknowledge popup — issue type / cause / operator / note */}
      <AcknowledgeModal
        open={!!ackTarget}
        onClose={() => setAckTarget(null)}
        onSubmit={submitAck}
        operator={operator}
        allMode={ackTarget === 'ALL'}
        context={{
          busId,
          title: ackTarget === 'ALL' ? `all unfinished incidents` : (ackTarget?.title || ackTarget?.category || ''),
        }}
      />
    </div>
  )
}
