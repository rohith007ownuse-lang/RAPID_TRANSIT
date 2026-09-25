import { useEffect, useState } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge } from '../components/UI.jsx'
import { eventLabel } from '../components/AlertFeed.jsx'
import { ReviewState, BulkReviewEditor } from '../components/ReviewStatus.jsx'
import { useAuth } from '../lib/authContext.jsx'

const FILTERS = ['ALL', 'CRITICAL', 'WARNING', 'INFO']

const EDIT_OPTIONS = [
  { value: 'ACTIVE', label: 'Not reviewed', hint: 'nothing / nobody has looked at this yet', cls: 'rs-opt-new', symbol: '○' },
  { value: 'REVIEWING', label: 'Reviewing', hint: 'an operator is on the live feed right now', cls: 'rs-opt-reviewing', symbol: '●' },
  { value: 'ACKNOWLEDGED', label: 'Acknowledged', hint: 'checked, no real problem — everyone sees it is handled', cls: 'rs-opt-acked', symbol: '✓' },
]

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
  ACKNOWLEDGED: 'var(--amber)',
  INVESTIGATING: 'var(--accent)',
  RESOLVED: 'var(--green)',
  CLOSED: '#94a3b8',
}

function IncidentCard({ incident, canEdit, operator, onAction }) {
  const [expanded, setExpanded] = useState(false)

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
        {incident.resolved_by && <div><strong>Resolved by:</strong> {incident.resolved_by}</div>}
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

        {incident.status === 'OPEN' && (
          <>
            <button
              className="btn btn-ack"
              style={{ fontSize: 12 }}
              onClick={() => handleAction(() => api.acknowledgeIncident(incident.incident_id, { operator }))}
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
      </div>
    </div>
  )
}

export default function Incidents() {
  const { user } = useAuth()
  const [filter, setFilter] = useState('ALL')
  const [editingId, setEditingId] = useState(null)
  const [draft, setDraft] = useState('ACTIVE')
  const [viewMode, setViewMode] = useState('events') // 'events' or 'incidents'
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

  const filtered = filter === 'ALL' ? events : events.filter((e) => e.severity === filter)

  const openLiveFeed = (e) => {
    api.review(e.event_id, { operator: operator() }).catch(() => {})
    window.open('/fleet/' + encodeURIComponent(e.bus_id), '_blank')
  }

  const acknowledge = (e) => {
    api.acknowledge(e.event_id, { operator: operator() }).catch(() => {})
  }

  const resolve = (e) => {
    api.resolve(e.event_id, { operator: operator() }).catch(() => {})
  }

  const startEdit = (e) => {
    setDraft(e.status === 'RESOLVED' ? 'ACKNOWLEDGED' : e.status)
    setEditingId(e.event_id)
  }

  const submitEdit = (e) => {
    api.setStatus(e.event_id, { status: draft, operator: operator() }).then(() => setEditingId(null)).catch(() => {})
  }

  const cancelEdit = () => {
    setEditingId(null)
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

      {/* View mode toggle */}
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
              <span className="chip">✎ <strong>Edit status</strong> — operator manually sets the review state</span>
            </div>
            <div className="mt-16">
              <BulkReviewEditor events={filtered} buttonLabel="✎ Edit status for all incidents at once" />
            </div>
          </>
        )}
      </div>

      {/* Events grid */}
      {viewMode === 'events' && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
          {filtered.length === 0 && <div className="card empty">No incidents match the filter.</div>}
          {filtered.map((e) => (
            <div className="card" key={e.event_id} style={{ borderTop: `4px solid ${e.severity === 'CRITICAL' ? 'var(--red)' : e.severity === 'WARNING' ? 'var(--amber)' : 'var(--accent)'}` }}>
              <div className="flex justify-between align-center mb-8">
                <strong>{eventLabel(e.event_type)}</strong>
                <div className="flex align-center" style={{ gap: 8 }}>
                  <ReviewState status={e.status} />
                  <button
                    className="btn-ghost rs-edit-btn"
                    title={canEdit ? 'Edit review status' : 'Requires Supervisor or Admin role'}
                    onClick={() => canEdit && startEdit(e)}
                    style={canEdit ? undefined : { opacity: 0.45, cursor: 'not-allowed' }}
                  >
                    ✎ Edit status
                  </button>
                </div>
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

              {editingId === e.event_id ? (
                <div className="mt-16 rs-edit-form">
                  <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                    <strong>Set review status</strong> — which state should this incident be in?
                  </div>
                  <div className="grid" style={{ gap: 8 }}>
                    {EDIT_OPTIONS.map((opt) => (
                      <label
                        key={opt.value}
                        className={`rs-option ${opt.cls} ${draft === opt.value ? 'rs-option-sel' : ''}`}
                      >
                        <input
                          type="radio"
                          name={`status-${e.event_id}`}
                          value={opt.value}
                          checked={draft === opt.value}
                          onChange={() => setDraft(opt.value)}
                        />
                        <span><span className="rs-opt-symbol">{opt.symbol}</span> <strong>{opt.label}</strong></span>
                        <span className="rs-opt-hint">{opt.hint}</span>
                      </label>
                    ))}
                  </div>
                  <div className="flex gap-8 mt-16">
                    <button className="btn btn-primary" style={{ fontSize: 12, flex: 1 }} onClick={() => submitEdit(e)}>
                      Submit status
                    </button>
                    <button className="btn" style={{ fontSize: 12, flex: 1 }} onClick={cancelEdit}>
                      ← Back
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-8 mt-16 wrap">
                  <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => openLiveFeed(e)}>
                    ▶ Open Live Feed
                  </button>
                  {(e.status === 'ACTIVE' || e.status === 'REVIEWING') && (
                    <button className="btn btn-ack" style={{ fontSize: 12 }} onClick={() => acknowledge(e)}>
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

              {e.simulation && <div className="muted mt-8" style={{ fontSize: 11 }}>simulated demo</div>}
            </div>
          ))}
        </div>
      )}

      {/* Incidents grid */}
      {viewMode === 'incidents' && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: 16 }}>
          {incidents.length === 0 && <div className="card empty">No incidents created yet.</div>}
          {incidents.map((inc) => (
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
    </>
  )
}
