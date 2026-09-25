// callCenter.js — shared, in-app intercom for the control room.
//
// One call at a time, either direction:
//   - operator -> bus  : outboundCall(busId, label)  (the operator dials a bus)
//   - bus -> operator  : simulateIncoming(busId, label) (the driver pressed the
//                          in-bus CALL button on the hardware unit)
//   - answerCall / declineCall / hangup control the active/ringing call.
//
// A tiny pub-sub store so the call state is shared across every page in the SPA
// (bus detail headers, the Intercom page and the global incoming-call banner).

const state = {
  status: 'idle', // idle | calling | ringing | active
  busId: null,
  label: '',
  direction: null, // 'out' = operator dialled, 'in' = the bus called the operator
  startedAt: null,
  transcript: [], // { kind: 'you' | 'driver', text, ts }
}

const listeners = new Set()
function emit() {
  for (const l of listeners) l(state)
}

export function subscribe(fn) {
  fn(state)
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function getCall() {
  return state
}

export function setCall(patch) {
  Object.assign(state, patch)
  emit()
}

function reset() {
  setCall({ status: 'idle', busId: null, label: '', direction: null, startedAt: null, transcript: [] })
}

export function outboundCall(busId, label) {
  if (state.status !== 'idle') return
  // Direct connect — the operator dials and the cabin picks up immediately,
  // no ringing / accept step on the bus side.
  setCall({ status: 'active', busId, label, direction: 'out', startedAt: Date.now() })
}

export function simulateIncoming(busId, label) {
  if (state.status !== 'idle') return
  setCall({ status: 'ringing', busId, label, direction: 'in' })
  setTimeout(() => {
    if (getCall().status === 'ringing') reset()
  }, 20000)
}

export function answerCall() {
  if (state.status !== 'ringing') return
  setCall({ status: 'active', startedAt: Date.now() })
}

export function declineCall() {
  if (state.status !== 'ringing') return
  reset()
}

export function hangup() {
  reset()
}

export function addLine(kind, text) {
  state.transcript.push({ kind, text, ts: new Date().toLocaleTimeString() })
  emit()
}