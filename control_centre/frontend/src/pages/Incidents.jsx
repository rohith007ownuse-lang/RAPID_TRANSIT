import { useEffect, useMemo, useState } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge } from '../components/UI.jsx'
import { eventLabel } from '../components/AlertFeed.jsx'
import AcknowledgeModal from '../components/AcknowledgeModal.jsx'
import { EventDecisionExpander } from '../components/DecisionExplain.jsx'
import { IncidentSlaPanel } from '../components/BackendOnlyPanels.jsx'
import { ReviewState } from '../components/ReviewStatus.jsx'
import { useAuth } from '../lib/authContext.jsx'

const FILTERS = ['ALL', 'CRITICAL', 'WARNING', 'INFO']

const INCIDENT_SEVERITY_COLORS = {
  CRITICAL: 'var(--red)',
  HIGH: '#f97316',
  MEDIUM: 'var(--amber)',
  LOW: '#22c55e',
  INFO: 'var(--accent)',
}

const INCIDENT_PRIORITY_COLORS = {
  URGENT: 'var(--red)',
  HIGH: '#f97316',
  MEDIUM: 'var(--amber)',
  LOW: '#22c55e',
}

const INCIDENT_STATUS_COLORS = {
  OPEN: 'var(--red)',
  DETECTED: 'var(--red)',
  CONFIRMED: '#f97316',
  ACKNOWLEDGED: 'var(--amber)',
  INVESTIGATING: 'var(--accent)',
  ASSIGNED: '#a855f7',
  RESPONDING: '#0ea5e9',
  RESOLVED: 'var(--green)',
  CLOSED: '#94a3b8',
}

const ASSIGNABLE_STATUSES = ['OPEN', 'DETECTED', 'CONFIRMED']

function IncidentCard({ incident, canEdit, operator, onAction }) {
  const [expanded, setExpanded] = useState(false)
  const [ackOpen, setAckOpen] = useState(false)
  const [assignee, setAssignee] = useState(operator || '')

  const submitAck = async (payload) => {
    try {
      await api.acknowledgeIncident(incident.incident_id, { operator, ...payload })
      onAction?.()
    } catch (err) {
      console.error('Acknowledge failed:', err)
    }
    setAckOpen(false)
  }

  const handleAction = async (action) => {
    try {
      await action()
      onAction?.()
    } catch (err) {
      console.error('Action failed:', err)
    }
  }

  return (
    <div className="card" style={{
      borderTop: `4px solid ${INCIDENT_SEVERITY_COLORS[incident.severity] || 'var(--accent)'}`,
      borderLeft: incident.priority === 'URGENT' ? `3px solid ${INCIDENT_PRIORITY_COLORS.URGENT}` : undefined,
    }}>
      <div className="flex justify-between align-center mb-8">
        <strong style={{ fontSize: 14 }}>{incident.title}</strong>
        <div className="flex align-center" style={{ gap: 8 }}>
          <span style={{
            padding: '2px 8px',
            borderRadius: 12,
            fontSize: 11,
            fontWeight: 600,
            background: `${INCIDENT_SEVERITY_COLORS[incident.severity] || 'var(--accent)'}22`,
            color: INCIDENT_SEVERITY_COLORS[incident.severity] || 'var(--accent)',
          }}>
            {incident.severity}
          </span>
          <span style={{
            padding: '2px 8px',
            borderRadius: 12,
            fontSize: 11,
            fontWeight: 600,
            background: `${INCIDENT_PRIORITY_COLORS[incident.priority] || '#94a3b8'}22`,
            color: INCIDENT_PRIORITY_COLORS[incident.priority] || '#94a3b8',
          }}>
            {incident.priority}
          </span>
        </div>
      </div>

      <div className="muted" style={{ fontSize: 13, lineHeight: 1.7 }}>
        <div><strong>ID:</strong> <span className="mono">{incident.incident_id}</span></div>
        <div><strong>Bus:</strong> {incident.bus_id}</div>
        {incident.route && <div><strong>Route:</strong> {incident.route}</div>}
        <div><strong>Category:</strong> {incident.category?.replace('_', ' ')}</div>
        <div><strong>Status:</strong> <StatusBadge status={incident.status} /></div>
        <div><strong>Events:</strong> {incident.event_count} related event(s)</div>
        <div><strong>Source:</strong> {incident.source}</div>
        <div><strong>Data:</strong> <StatusBadge status={incident.data_source} /></div>
        <div><strong>Created:</strong> {new Date(incident.created_at).toLocaleString()}</div>
        {incident.acknowledged_by && <div><strong>Acknowledged by:</strong> {incident.acknowledged_by}</div>}
        {incident.ack_issue_type && <div><strong>Issue type:</strong> {incident.ack_issue_type}</div>}
        {incident.ack_cause && <div><strong>Cause:</strong> {incident.ack_cause}</div>}
        {incident.ack_note && <div><strong>Note:</strong> {incident.ack_note}</div>}
        {incident.resolved_by && <div><strong>Resolved by:</strong> {incident.resolved_by}</div>}
        {incident.assigned_to && <div><strong>Assigned to:</strong> {incident.assigned_to}</div>}
        {(incident.escalation_level || 0) > 0 && <div><strong>Escalation:</strong> ×{incident.escalation_level} ({incident.assign_attempts} attempt(s))</div>}
      </div>

      {incident.evidence?.length > 0 && (
        <div className="mt-8" style={{ fontSize: 12 }}>
          <strong>Evidence ({incident.evidence.length}):</strong>
          <ul style={{ margin: '4px 0', paddingLeft: 16 }}>
            {incident.evidence.slice(0, 3).map((ev, i) => (
              <li key={i} className="muted">{ev.detail || ev.type}</li>
            ))}
          </ul>
        </div>
      )}

      {expanded && incident.timeline?.length > 0 && (
        <div className="mt-8" style={{ fontSize: 12 }}>
          <strong>Timeline:</strong>
          <ul style={{ margin: '4px 0', paddingLeft: 16 }}>
            {incident.timeline.map((t, i) => (
              <li key={i} className="muted">
                {t.action} — {new Date(t.timestamp).toLocaleTimeString()}
                {t.operator && ` by ${t.operator}`}
                {t.details && ` (${t.details})`}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-8 mt-16 wrap">
        <button
          className="btn btn-ghost"
          style={{ fontSize: 11 }}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Collapse' : 'Expand'}
        </button>

        {incident.status === 'DETECTED' && (
          <button
            className="btn btn-primary"
            style={{ fontSize: 12 }}
            onClick={() => handleAction(() => api.confirmIncident(incident.incident_id, { operator }))}
          >
            Confirm
          </button>
        )}

        {incident.status === 'OPEN' && (
          <>
            {/* Acknowledge opens the popup (issue type / cause / operator / note) */}
            <button
              className="btn btn-ack"
              style={{ fontSize: 12 }}
              onClick={() => setAckOpen(true)}
            >
              ✓ Acknowledge
            </button>
            {canEdit && (
              <button
                className="btn"
                style={{ fontSize: 12 }}
                onClick={() => handleAction(() => api.resolveIncident(incident.incident_id, { operator }))}
              >
                Resolve
              </button>
            )}
          </>
        )}

        {incident.status === 'ACKNOWLEDGED' && (
          <button
            className="btn btn-primary"
            style={{ fontSize: 12 }}
            onClick={() => handleAction(() => api.investigateIncident(incident.incident_id, { operator }))}
          >
            Investigate
          </button>
        )}

        {incident.status === 'INVESTIGATING' && canEdit && (
          <button
            className="btn"
            style={{ fontSize: 12 }}
            onClick={() => handleAction(() => api.resolveIncident(incident.incident_id, { operator }))}
          >
            Resolve
          </button>
        )}

        {incident.status === 'RESOLVED' && canEdit && (
          <button
            className="btn"
            style={{ fontSize: 12 }}
            onClick={() => handleAction(() => api.closeIncident(incident.incident_id, { operator }))}
          >
            Close
          </button>
        )}

        {ASSIGNABLE_STATUSES.includes(incident.status) && (
          <>
            <input
              className="input"
              style={{ fontSize: 12, maxWidth: 140 }}
              placeholder="Assign to operator"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            />
            <button
              className="btn btn-primary"
              style={{ fontSize: 12 }}
              onClick={() => handleAction(() => api.assignIncident(incident.incident_id, { operator, assignee })) }
            >
              Assign
            </button>
          </>
        )}

        {incident.status === 'ASSIGNED' && (
          <>
            <button
              className="btn btn-primary"
              style={{ fontSize: 12 }}
              onClick={() => handleAction(() => api.respondIncident(incident.incident_id, { operator }))}
            >
              Respond
            </button>
            <button
              className="btn btn-ghost"
              style={{ fontSize: 12 }}
              onClick={() => handleAction(() => api.rejectIncident(incident.incident_id, { operator }))}
            >
              Reject
            </button>
          </>
        )}
      </div>

      <AcknowledgeModal
        open={ackOpen}
        onClose={() => setAckOpen(false)}
        onSubmit={submitAck}
        operator={operator}
        context={{ busId: incident.bus_id, title: incident.title }}
      />
    </div>
  )
}

export default function Incidents() {
  const { user } = useAuth()
  const [filter, setFilter] = useState('ALL')
  const [viewMode, setViewMode] = useState('events') // 'events' or 'incidents'
  // Acknowledge popup target — an event, or { all: true } for acknowledge-all.
  const [ackTarget, setAckTarget] = useState(null)
  const { data: eventsData, refetch: refetchEvents } = usePoll(api.events, 4000)
  const { data: incidentsData, refetch: refetchIncidents } = usePoll(api.incidents, 4000)
  const { data: incidentSummaryData } = usePoll(api.incidentSummary, 8000)

  const events = eventsData?.events || []
  const incidents = incidentsData?.incidents || []
  const summary = incidentSummaryData?.summary || {}

  const opName = user?.username || 'Operator 1'
  const opRole = user?.role || 'operator'
  const canEdit = opRole === 'supervisor' || opRole === 'admin'
  const operator = () => `${opName} (${opRole})`

  const filtered = filter === 'ALL'
    ? events.filter((e) => (e.event_type || '').toUpperCase() !== 'VEHICLE_ANOMALY' && (e.severity || '').toUpperCase() !== 'INFO')
    : events.filter((e) => (e.severity || '').toUpperCase() === filter)
  // CRITICAL always first, then WARNING, then the rest; unfinished work outranks finished.
  const tierRank = (e) => (e.severity === 'CRITICAL' ? 0 : e.severity === 'WARNING' || e.severity === 'HIGH' ? 1 : 2)
  const statusRank = (e) => (e.status === 'ACTIVE' ? 0 : e.status === 'REVIEWING' ? 1 : e.status === 'ACKNOWLEDGED' ? 2 : 3)
  const sortedEvents = useMemo(() =>
    [...filtered].sort((a, b) =>
      tierRank(a) - tierRank(b)
      || statusRank(a) - statusRank(b)
      || new Date(b.timestamp) - new Date(a.timestamp)
    ),
    [events, filter]
  )

  const unresolved = incidents.filter((i) => !['RESOLVED', 'CLOSED'].includes(i.status)).length
  const resolved = incidents.length - unresolved
  const acknowledgedCount = incidents.filter((i) => i.status === 'ACKNOWLEDGED' || i.acknowledged_by).length

  const openLiveFeed = (e) => {
    api.review(e.event_id, { operator: operator() }).catch(() => {})
    window.open('/fleet/' + encodeURIComponent(e.bus_id), '_blank')
  }

  const submitAck = async (payload) => {
    const t = ackTarget
    if (!t) return
    try {
      if (t.all) {
        const targets = events.filter((e) => e.status === 'ACTIVE' || e.status === 'REVIEWING')
        await Promise.all(targets.map((e) => api.acknowledge(e.event_id, { operator: operator(), ...payload }).catch(() => {})))
      } else {
        await api.acknowledge(t.event_id, { operator: operator(), ...payload })
      }
      refetchEvents()
      refetchIncidents()
    } catch (err) {
      console.error('Acknowledge failed:', err)
    }
    setAckTarget(null)
  }

  const resolve = (e) => {
    api.resolve(e.event_id, { operator: operator() }).then(() => {
      refetchEvents()
      refetchIncidents()
    }).catch(() => {})
  }

  return (
    <>
      <PageHeader
        title="Incident Management"
        sub="Crash · fire/smoke · drowsiness · road hazard · siren · overload · vehicle health · risk escalation"
        right={<SimBadge />}
      />
      <div className="card mb-16" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span className="chip" style={{ margin: 0 }}>
          <strong>Operator identity</strong> — <span className="mono">{opName}</span> (
            {opRole === 'operator' ? 'Operator' : opRole === 'supervisor' ? 'Supervisor' : 'Admin'}
          ). Your role comes from the server and tags every action.
        </span>
        {!canEdit && (
          <span className="muted" style={{ fontSize: 11 }}>
            Operator role: resolve &amp; status edits are locked (needs Supervisor/Admin).
          </span>
        )}
      </div>

      {/* Workflow counts — how many are still open vs resolved */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Incident Workflow</h3>
        </div>
        <div className="flex wrap gap-8 align-center">
          <span className="chip" style={{ margin: 0 }}>
            <span className="rs-dot" style={{ background: 'var(--red)' }} />
            <strong>Not finished:</strong> {unresolved}
          </span>
          <span className="chip" style={{ margin: 0 }}>
            <span className="rs-dot" style={{ background: 'var(--green)' }} />
            <strong>Resolved:</strong> {resolved}
          </span>
          <span className="chip" style={{ margin: 0 }}>
            <span className="rs-dot" style={{ background: 'var(--amber)' }} />
            <strong>Acknowledged:</strong> {acknowledgedCount}
          </span>
          <span className="chip" style={{ margin: 0 }}>
            <strong>Total:</strong> {incidents.length}
          </span>
        </div>
      </div>

      {/* View mode toggle */}
      <IncidentSlaPanel />
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">View</h3>
          <div className="filter-row">
            <button
              className={`seg ${viewMode === 'events' ? 'active' : ''}`}
              onClick={() => setViewMode('events')}
            >
              Events ({events.length})
            </button>
            <button
              className={`seg ${viewMode === 'incidents' ? 'active' : ''}`}
              onClick={() => setViewMode('incidents')}
            >
              Incidents ({incidents.length})
            </button>
          </div>
        </div>

        {/* Incident summary */}
        {viewMode === 'incidents' && (
          <div className="flex wrap gap-8 mt-16 align-center">
            {Object.entries(summary.by_severity || {}).map(([sev, count]) => (
              <span key={sev} className="chip" style={{ margin: 0 }}>
                <span className="rs-dot" style={{ background: INCIDENT_SEVERITY_COLORS[sev] || '#94a3b8' }} />
                <strong>{sev}</strong>: {count}
              </span>
            ))}
            {summary.active_count > 0 && (
              <span className="chip" style={{ margin: 0 }}>
                <strong>Active:</strong> {summary.active_count}
              </span>
            )}
            {summary.high_priority_count > 0 && (
              <span className="chip" style={{ margin: 0 }}>
                <strong>High Priority:</strong> {summary.high_priority_count}
              </span>
            )}
          </div>
        )}

        {/* Events view - existing functionality */}
        {viewMode === 'events' && (
          <>
            <div className="card-header">
              <h3 className="card-title">Filter</h3>
              <div className="filter-row">
                {FILTERS.map((f) => (
                  <button key={f} className={`seg ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
                    {f}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex wrap gap-8 mt-16 align-center">
              <span className="chip"><span className="rs-dot" style={{ background: '#cbd5e1' }} /> <strong>white</strong> — operator hasn&apos;t looked at it yet</span>
              <span className="chip"><span className="rs-dot" style={{ background: 'var(--amber)' }} /> <strong>amber</strong> — open live feed · being reviewed</span>
              <span className="chip"><span className="rs-dot" style={{ background: 'var(--green)' }} /> <strong>green</strong> — acknowledged / resolved</span>
              <span className="chip"><strong>Critical first</strong> — acknowledgements open a popup (issue type, cause, operator, note)</span>
            </div>
            {canEdit && (
              <div className="mt-8">
                <button
                  className="btn btn-sm btn-ghost"
                  style={{ fontSize: 11 }}
                  onClick={() => setAckTarget({ all: true })}
                >
                  ✓ Acknowledge all ({events.filter((e) => e.status === 'ACTIVE' || e.status === 'REVIEWING').length})
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Events grid — CRITICAL first, then WARNING, then everything else.
          VEHICLE_ANOMALY and INFO-tier events never render. */}
      {viewMode === 'events' && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
          {sortedEvents.length === 0 && <div className="card empty">No incidents match the filter.</div>}
          {sortedEvents.map((e) => (
            <div className="card" key={e.event_id} style={{ borderTop: `4px solid ${e.severity === 'CRITICAL' ? 'var(--red)' : e.severity === 'WARNING' ? 'var(--amber)' : 'var(--accent)'}` }}>
              <div className="flex justify-between align-center mb-8">
                <strong>{eventLabel(e.event_type)}</strong>
                <ReviewState status={e.status} />
              </div>
              <div className="muted" style={{ fontSize: 13, lineHeight: 1.7 }}>
                <div><strong>Bus:</strong> {e.bus_id}</div>
                <div><strong>Time:</strong> {new Date(e.timestamp).toLocaleString()}</div>
                <div><strong>GPS:</strong> <span className="mono">{e.latitude?.toFixed(4)}, {e.longitude?.toFixed(4)}</span></div>
                <div><strong>Source:</strong> {e.sensor_source}</div>
                <div><strong>Confidence:</strong> {Math.round((e.confidence || 0) * 100)}%</div>
                <div><strong>Severity:</strong> <StatusBadge status={e.severity} /></div>
                {e.reviewed_by && <div className="mt-8" style={{ fontSize: 12 }}>🟡 started review — {e.reviewed_by}</div>}
                {e.acknowledged_by && <div style={{ fontSize: 12 }}>🟢 acknowledged — {e.acknowledged_by}</div>}
                {e.resolved_by && <div style={{ fontSize: 12 }}>⚪ resolved — {e.resolved_by}</div>}
              </div>

              <EventDecisionExpander eventId={e.event_id} />

              {(
                <div className="flex gap-8 mt-16 wrap">
                  <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => openLiveFeed(e)}>
                    ▶ Open Live Feed
                  </button>
                  {(e.status === 'ACTIVE' || e.status === 'REVIEWING') && (
                    <button className="btn btn-ack" style={{ fontSize: 12 }} onClick={() => setAckTarget(e)}>
                      ✓ Acknowledge
                    </button>
                  )}
                  {e.status === 'ACKNOWLEDGED' && canEdit && (
                    <button className="btn" style={{ fontSize: 12 }} onClick={() => resolve(e)}>
                      Mark Resolved
                    </button>
                  )}
                  {e.status === 'ACKNOWLEDGED' && !canEdit && (
                    <span className="muted" style={{ fontSize: 11, alignSelf: 'center' }}>
                      resolve requires Supervisor/Admin
                    </span>
                  )}
                </div>
              )}

              {e.simulation && <div className="muted mt-8" style={{ fontSize: 11 }}>estimated demo</div>}
            </div>
          ))}
        </div>
      )}

      {/* Incidents grid — demo rotation keeps the live pool to ~5 incidents;
          resolved/closed history stays in the workflow chips above. */}
      {viewMode === 'incidents' && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: 16 }}>
          {incidents.length === 0 && <div className="card empty">No incidents created yet.</div>}
          {incidents
            .filter((inc) => !['RESOLVED', 'CLOSED'].includes(inc.status))
            .slice(0, 5)
            .map((inc) => (
            <IncidentCard
              key={inc.incident_id}
              incident={inc}
              canEdit={canEdit}
              operator={operator()}
              onAction={() => {
                refetchIncidents()
                refetchEvents()
              }}
            />
          ))}
        </div>
      )}

      {/* Acknowledge popup — used by both event and incident acknowledge */}
      <AcknowledgeModal
        open={!!ackTarget}
        onClose={() => setAckTarget(null)}
        onSubmit={submitAck}
        operator={operator()}
        allMode={!!ackTarget?.all}
        context={{ busId: ackTarget?.bus_id, title: ackTarget?.all ? 'All unfinished incidents' : eventLabel(ackTarget?.event_type || '') }}
      />
    </>
  )
}
