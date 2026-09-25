import { useEffect, useState } from 'react'
import { subscribe, getCall, outboundCall, hangup } from '../lib/callCenter.js'

// Compact call control for the bus detail header — one tap dials the bus and
// it connects directly (no accept step). Tap again to end.
export default function CallButton({ busId, label }) {
  const [call, setCall] = useState(getCall())
  useEffect(() => subscribe(setCall), [])

  const isThis = call.busId === busId
  const busyElsewhere = call.status !== 'idle' && !isThis

  if (isThis && call.status !== 'idle') {
    return (
      <button className="btn call-connected" onClick={hangup} title={`On call with ${busId} — tap to end`}>
        <span className="cc-pulse" /> ☎ {call.direction === 'in' ? 'Driver called you' : 'On call'} · {busId} · End
      </button>
    )
  }

  return (
    <button
      className="btn call-dial"
      disabled={busyElsewhere}
      onClick={() => outboundCall(busId, label || busId)}
      title={busyElsewhere ? `Already on a call with ${call.busId}` : `Call ${busId} — driver answers directly`}
    >
      📞 Call {busId}
    </button>
  )
}