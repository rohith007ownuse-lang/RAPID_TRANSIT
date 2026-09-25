import { useEffect, useState } from 'react'
import { subscribe, getCall, answerCall, declineCall } from '../lib/callCenter.js'

// Floating banner shown on every page when a bus's hardware CALL button rings
// the control room. Whichever operator is free accepts and talks directly.
export default function IncomingCall() {
  const [call, setCall] = useState(getCall())
  useEffect(() => subscribe(setCall), [])

  if (call.status !== 'ringing') return null

  return (
    <div className="incoming-call">
      <div className="ic-card">
        <div className="ic-ring">📲</div>
        <div className="ic-info">
          <strong>Incoming call — {call.label || call.busId}</strong>
          <div className="muted" style={{ fontSize: 12 }}>
            The driver pressed the in-bus CALL button · wants the operator
          </div>
        </div>
        <div className="flex gap-8">
          <button className="btn call-answer" onClick={answerCall}>
            ✓ Accept
          </button>
          <button className="btn call-decline" onClick={declineCall}>
            ✕ Decline
          </button>
        </div>
      </div>
    </div>
  )
}