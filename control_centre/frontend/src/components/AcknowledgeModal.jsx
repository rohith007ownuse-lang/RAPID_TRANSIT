import { useMemo, useState } from 'react'

/**
 * AcknowledgeModal — the popup that appears when an operator clicks
 * "Acknowledge" anywhere in the alert system (live alerts, incidents page,
 * bus live feed).
 *
 * Flow (operator spec): pick the issue type → pick the real cause from the
 * option list (one option is "False alert") → operator name is prefilled →
 * optional free-text note → Acknowledge & Submit.
 *
 * `onSubmit(payload)` receives:
 *   { issue_type, cause, note }
 * The caller attaches the operator identity and performs the API call.
 */

const ISSUE_TYPES = [
  { value: 'REAL_ISSUE', label: 'Real issue', hint: 'something actually happened on this bus' },
  { value: 'FALSE_ALERT', label: 'False alert', hint: 'the system fired, but nothing is wrong' },
  { value: 'RESOLVED_ON_SITE', label: 'Resolved on site', hint: 'the crew already handled it before acknowledgement' },
  { value: 'DUPLICATE', label: 'Duplicate', hint: 'same incident already reported/tracked elsewhere' },
]

// Cause options — covers the six critical + warning alert families.
const CAUSE_OPTIONS = [
  { value: 'POSSIBLE_CRASH_CONFIRMED', label: 'Crash / impact confirmed', hint: 'critical' },
  { value: 'POSSIBLE_CRASH_FALSE', label: 'Crash sensor false trigger (rough road / hard braking)', hint: 'critical' },
  { value: 'DROWSINESS_CONFIRMED', label: 'Driver drowsiness confirmed', hint: 'critical' },
  { value: 'DROWSINESS_FALSE', label: 'Driver was alert — camera misread', hint: 'critical' },
  { value: 'SMOKE_CONFIRMED', label: 'Smoke in cabin confirmed', hint: 'critical' },
  { value: 'FIRE_CONFIRMED', label: 'Fire in cabin confirmed', hint: 'critical' },
  { value: 'ROAD_HAZARD_CONFIRMED', label: 'Road hazard / pothole confirmed', hint: 'warning' },
  { value: 'OVERLOAD_CONFIRMED', label: 'Overload confirmed', hint: 'warning' },
  { value: 'RISK_ESCALATION_CONFIRMED', label: 'Risk escalation prediction confirmed', hint: 'warning' },
  { value: 'FALSE_ALERT', label: 'False alert — no real issue found', hint: 'any type' },
  { value: 'OTHER', label: 'Other (describe in the note)', hint: 'any type' },
]

export default function AcknowledgeModal({ open, onClose, onSubmit, operator = 'Operator 1', context = {}, allMode = false }) {
  const [issueType, setIssueType] = useState('REAL_ISSUE')
  const [cause, setCause] = useState('')
  const [note, setNote] = useState('')

  const causes = useMemo(() => CAUSE_OPTIONS, [])

  if (!open) return null

  const submit = (e) => {
    e.preventDefault()
    if (!issueType || !cause) return
    onSubmit({
      issue_type: issueType,
      cause,
      note: note.trim() || undefined,
      // flat convenience copies
      issueType,
      ackCause: cause,
      ackNote: note.trim() || undefined,
    })
    setIssueType('REAL_ISSUE')
    setCause('')
    setNote('')
  }

  return (
    <div
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(15,23,42,0.55)', display: 'flex',
        alignItems: 'center', justifyContent: 'center', padding: 16,
      }}
    >
      <form
        onSubmit={submit}
        style={{
          background: '#fff', borderRadius: 12, width: 480, maxWidth: '100%',
          boxShadow: '0 20px 50px rgba(0,0,0,0.25)', padding: 18,
          maxHeight: '90vh', overflowY: 'auto',
        }}
      >
        <div className="flex justify-between align-center mb-8">
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            ✓ Acknowledge {allMode ? 'all incidents' : 'incident'}
          </h3>
          <button type="button" className="btn btn-ghost" style={{ fontSize: 14, padding: '2px 8px' }} onClick={onClose}>✕</button>
        </div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
          {context.busId ? `${context.busId} · ` : ''}{context.title || 'incident'} — report what you found, then submit.
        </div>

        {/* Issue type */}
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Issue type</div>
        <div style={{ display: 'grid', gap: 6, marginBottom: 14 }}>
          {ISSUE_TYPES.map((t) => (
            <label
              key={t.value}
              className="rs-option rs-opt-acked"
              style={{
                display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                border: `1.5px solid ${issueType === t.value ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 8, padding: '7px 10px', background: issueType === t.value ? 'var(--accent-soft)' : '#fff',
              }}
            >
              <input type="radio" name="ack-issue-type" checked={issueType === t.value} onChange={() => setIssueType(t.value)} />
              <span style={{ fontSize: 13 }}>
                <strong>{t.label}</strong>
                <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>{t.hint}</span>
              </span>
            </label>
          ))}
        </div>

        {/* Cause — includes the false-alert option and the six alert families */}
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
          What is the real issue / what caused it?
        </div>
        <select
          value={cause}
          onChange={(e) => setCause(e.target.value)}
          required
          className="input"
          style={{ width: '100%', fontSize: 13, padding: '8px 10px', marginBottom: 14 }}
        >
          <option value="" disabled>Choose the cause…</option>
          {causes.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>

        {/* Operator */}
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Operator</div>
        <input
          className="input"
          value={operator}
          readOnly
          style={{ width: '100%', fontSize: 13, padding: '8px 10px', marginBottom: 14, background: '#f9fafb', color: '#374151' }}
        />

        {/* Optional note */}
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Note (optional)</div>
        <textarea
          className="input"
          rows={2}
          placeholder="Anything the operator wants to record…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ width: '100%', fontSize: 13, padding: '8px 10px', marginBottom: 14, resize: 'vertical' }}
        />

        <div className="flex gap-8">
          <button
            type="submit"
            className="btn btn-primary"
            style={{ flex: 1, fontSize: 13 }}
            disabled={!cause}
          >
            ✓ Acknowledge &amp; Submit
          </button>
          <button type="button" className="btn" style={{ flex: 1, fontSize: 13 }} onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
