import { useEffect, useState } from 'react'
import { api, usePoll } from '../api.js'

/* Shared styles for the decision/explainability UI (matches V2 cards). */
const levelColor = (level) =>
  level === 'CRITICAL' ? '#dc2626'
  : level === 'HIGH' ? '#f59e0b'
  : level === 'MEDIUM' ? '#2563eb' : '#16a34a'

function LevelBadge({ level }) {
  if (!level) return null
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 12,
      background: levelColor(level), color: '#fff', fontWeight: 700,
    }}>
      {level}
    </span>
  )
}

/* ─── Per-bus decision intelligence + risk explanation ───
   Polls the live decision_intelligence + explainability_engine endpoints
   for one bus. Returns null until data arrives (same convention as V2 cards). */
export function BusDecisionCard({ busId }) {
  const { data: decision } = usePoll(() => api.v2DecisionBus(busId), 20000, [busId])
  const { data: explained } = usePoll(() => api.v2ExplainRisk(busId), 20000, [busId])

  if (!decision && !explained) return null

  const top = decision?.top_recommendation
  const analyses = decision?.recent_analyses || []

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #8b5cf6' }}>
      <div className="card-header">
        <h3 className="card-title">🧠 Decision Intelligence — why this bus matters</h3>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {decision?.overall_risk_level && <LevelBadge level={decision.overall_risk_level} />}
          {decision?.incident_probability > 0 && (
            <span className="badge badge-amber" style={{ fontSize: 10 }}>
              {decision.incident_probability?.toFixed(0)}% INCIDENT PROB
            </span>
          )}
          {decision?.needs_attention && (
            <span className="badge badge-red" style={{ fontSize: 10 }}>NEEDS ATTENTION</span>
          )}
        </div>
      </div>

      {explained?.explanation && (
        <div style={{ fontSize: 12, color: '#374151', marginBottom: 8, lineHeight: 1.6 }}>
          {explained.explanation}
        </div>
      )}

      {top && (
        <div style={{
          padding: '6px 10px', background: '#f5f3ff',
          borderLeft: '3px solid #8b5cf6', borderRadius: 4,
          fontSize: 12, marginBottom: 8,
        }}>
          <strong>Recommended: </strong>{top.primary_action}
          {(top.actions || []).length > 1 && (
            <ul style={{ margin: '4px 0 0', paddingLeft: 16, color: '#6b7280' }}>
              {top.actions.slice(1, 4).map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          )}
        </div>
      )}

      {analyses.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {analyses.slice(0, 3).map((a, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '5px 8px', background: '#f8fafc',
              borderRadius: 4, fontSize: 11,
            }}>
              <LevelBadge level={a.risk_assessment?.level} />
              <span style={{ fontWeight: 600 }}>
                {a.event_summary?.type || a.event_type || 'Event'}
              </span>
              <span className="muted" style={{ flex: 1 }}>
                {a.prediction?.primary_scenario?.description
                  || a.event_summary?.description || ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {decision && (decision.total_events ?? 0) === 0 && !top && (
        <div style={{ fontSize: 12, color: '#16a34a', padding: '4px 0' }}>
          No significant events on this bus — nothing for decision intelligence to escalate.
        </div>
      )}
    </div>
  )
}

/* ─── Per-event decision + explanation (on-demand) ───
   Fetches once when the operator expands it, so long event lists don't
   fan out dozens of requests. Handles 404 (event aged out of the store). */
export function EventDecisionExpander({ eventId }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [decision, setDecision] = useState(null)
  const [explained, setExplained] = useState(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    if (!open || decision || missing || !eventId) return
    let alive = true
    setLoading(true)
    Promise.all([
      api.v2DecisionEvent(eventId).catch(() => null),
      api.v2ExplainEvent(eventId).catch(() => null),
    ]).then(([d, x]) => {
      if (!alive) return
      if (!d && !x) setMissing(true)
      else { setDecision(d); setExplained(x) }
      setLoading(false)
    })
    return () => { alive = false }
  }, [open, eventId]) // eslint-disable-line react-hooks/exhaustive-deps

  const risk = decision?.risk_assessment
  const rec = decision?.recommendation
  const resources = decision?.response?.resources || []

  return (
    <div className="mt-8">
      <button
        className="btn btn-ghost"
        style={{ fontSize: 11 }}
        onClick={() => setOpen(!open)}
      >
        {open ? '▾ Hide decision' : '🧠 Why this matters — decision + explanation'}
      </button>
      {open && (
        <div style={{
          marginTop: 6, padding: '8px 10px', background: '#faf5ff',
          border: '1px solid #e9d5ff', borderRadius: 6, fontSize: 12,
        }}>
          {loading && <span className="muted">Loading decision intelligence…</span>}
          {missing && (
            <span className="muted">Event aged out of the live store — decision unavailable.</span>
          )}
          {!loading && !missing && (
            <>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
                <LevelBadge level={risk?.level} />
                {risk?.score != null && (
                  <span className="muted">score {risk.score}/100</span>
                )}
                {risk?.escalation_required && (
                  <span className="badge badge-red" style={{ fontSize: 10 }}>ESCALATION</span>
                )}
              </div>
              {(explained?.explanation || decision?.event_summary?.description) && (
                <div style={{ color: '#374151', lineHeight: 1.6, marginBottom: 6 }}>
                  {explained?.explanation || decision.event_summary.description}
                </div>
              )}
              {(risk?.contributing_factors || []).length > 0 && (
                <div className="muted" style={{ marginBottom: 6 }}>
                  <strong>Factors: </strong>{risk.contributing_factors.join(' · ')}
                </div>
              )}
              {decision?.prediction?.primary_scenario && (
                <div className="muted" style={{ marginBottom: 6 }}>
                  <strong>Likely next: </strong>
                  {decision.prediction.primary_scenario.description || ''}
                  {decision.prediction.timeframe && ` (${decision.prediction.timeframe})`}
                </div>
              )}
              {(rec?.actions || []).length > 0 && (
                <div style={{ marginBottom: 4 }}>
                  <strong>Actions: </strong>{rec.actions.join(' → ')}
                </div>
              )}
              {resources.length > 0 && (
                <div className="muted">
                  <strong>Resources: </strong>
                  {resources.map((r) => r.name || r.type).join(', ')}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
