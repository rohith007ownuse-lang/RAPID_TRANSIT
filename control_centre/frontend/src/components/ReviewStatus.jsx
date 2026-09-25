import { useState } from 'react'
import { api } from '../api.js'

export function ReviewState({ status }) {
  if (status === 'ACKNOWLEDGED') {
    return (
      <span className="review-state rs-acked">
        <span className="rs-dot" />✓ Acknowledged
      </span>
    )
  }
  if (status === 'REVIEWING') {
    return (
      <span className="review-state rs-reviewing">
        <span className="rs-dot" />● Reviewing
      </span>
    )
  }
  if (status === 'RESOLVED') {
    return (
      <span className="review-state rs-resolved">
        <span className="rs-dot" />✓ Resolved
      </span>
    )
  }
  return (
    <span className="review-state rs-new">
      <span className="rs-dot" />○ New
    </span>
  )
}

const operator = () => 'Operator ' + (Math.floor(Math.random() * 20) + 1)

export function BulkReviewEditor({ events = [], busId = null }) {
  const [busy, setBusy] = useState(false)

  const handleAcknowledgeAll = () => {
    setBusy(true)
    api.setStatusMany({
      status: 'ACKNOWLEDGED',
      operator: operator(),
      ...(busId ? { bus_id: busId } : {}),
    })
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  const unacked = events.filter((e) => e.status === 'ACTIVE').length
  if (unacked === 0) return null

  return (
    <button
      className="btn btn-sm btn-ghost"
      style={{ fontSize: 11 }}
      onClick={handleAcknowledgeAll}
      disabled={busy}
    >
      {busy ? 'Acknowledging...' : `Acknowledge all (${unacked})`}
    </button>
  )
}

export default function ReviewEditor({ event }) {
  const [busy, setBusy] = useState(false)

  const handleAcknowledge = () => {
    setBusy(true)
    api.setStatus(event.event_id, { status: 'ACKNOWLEDGED', operator: operator() })
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  if (event.status === 'ACKNOWLEDGED' || event.status === 'RESOLVED') {
    return <ReviewState status={event.status} />
  }

  return (
    <div className="flex align-center" style={{ gap: 8 }}>
      <ReviewState status={event.status} />
      <button
        className="btn btn-sm btn-ghost"
        style={{ fontSize: 11, padding: '2px 8px' }}
        onClick={handleAcknowledge}
        disabled={busy}
      >
        {busy ? '...' : 'Acknowledge'}
      </button>
    </div>
  )
}
