import { useEffect, useRef, useState } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { subscribe, getCall, outboundCall, simulateIncoming, hangup, addLine } from '../lib/callCenter.js'

const DRIVER_REPLIES = [
  'Copy that, driver here. Everything is fine, proceeding on schedule.',
  '{bus} driver responding — I have noted that, will do sir.',
  'Received, moving on to the next stop now.',
  'Okay understood. Cabin is clear, no issues this side.',
]

// Control Centre kill-switch: TTS is OFF until re-enabled (user: "sound on").
const SOUND_ENABLED = false

function say(text) {
  if (!SOUND_ENABLED) return
  try {
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 1.05
    window.speechSynthesis.speak(u)
  } catch { /* speech synthesis unavailable */ }
}

const hasRecognition = () => !!(window.SpeechRecognition || window.webkitSpeechRecognition)

export default function CallCenter() {
  const { data } = usePoll(api.buses, 6000)
  const buses = data?.buses || []
  const [call, setCall] = useState(getCall())
  const [interim, setInterim] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => subscribe(setCall), [])

  const recRef = useRef(null)
  const activeRef = useRef(false)
  const busRef = useRef(null)
  useEffect(() => {
    activeRef.current = call.status === 'active'
    busRef.current = call.busId
  }, [call])

  // Full-duplex console while a call is active: operator speaks (heard on the
  // cabin speaker) and the driver's replies come back through the cabin mic.
  useEffect(() => {
    if (call.status !== 'active' || !hasRecognition()) return

    const mkRec = () => {
      const W = window.SpeechRecognition || window.webkitSpeechRecognition
      const rec = new W()
      rec.lang = 'en-IN'
      rec.continuous = true
      rec.interimResults = true
      rec.onresult = (e) => {
        const latest = e.resultIndex
        const t = e.results[latest][0].transcript.trim()
        if (e.results[latest].isFinal) {
          if (!t.toLowerCase().includes('end call')) {
            setInterim('')
            addLine('you', t)
            say(`Attention driver of ${busRef.current}. ${t}`)
            // driver answers through the cabin mic
            setTimeout(() => {
              if (!activeRef.current) return
              const reply = DRIVER_REPLIES[
                Math.floor(Math.random() * DRIVER_REPLIES.length)
              ].replace('{bus}', busRef.current)
              addLine('driver', reply)
              say(reply)
            }, 1600)
          }
        } else {
          setInterim(t)
        }
      }
      rec.onend = () => {
        if (activeRef.current) {
          try { rec.start() } catch { /* ignore */ }
        }
      }
      rec.start()
      return rec
    }

    recRef.current = mkRec()
    return () => {
      try { recRef.current?.stop() } catch { /* ignore */ }
    }
  }, [call.status, call.busId])

  const onCall = call.status === 'active'

  const filtered = buses.filter((b) => {
    if (!query.trim()) return true
    const q = query.toLowerCase()
    return `${b.bus_id} ${b.route_code || ''} ${b.reg_no || ''}`.toLowerCase().includes(q)
  })

  const label = (b) => `${b.route_code || b.route || ''} · ${b.reg_no || ''}`
  const onThisCall = onCall && call.busId

  return (
    <>
      <PageHeader
        title="Intercom — Call any Bus Driver"
        sub="Full-duplex voice with the driver. Operator dials → driver answers directly. The driver can also call you from the in-bus unit."
        right={<SimBadge />}
      />

      {/* call console */}
      <div className="card mb-16 call-console">
        {!onCall ? (
          <div className="call-idle">
            <div className="call-idle-icon">📞</div>
            <div>
              <strong>No active call</strong>
              <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
                Dial a bus on the left, or simulate the <em>driver pressing the in-bus CALL button</em> below
                (when real hardware is installed, that button rings this room directly).
              </div>
            </div>
            <button
              className="btn"
              onClick={() => {
                const r = buses[Math.floor(Math.random() * buses.length)]
                if (r) simulateIncoming(r.bus_id, label(r))
              }}
              disabled={!buses.length}
            >
              📲 Simulate: driver calls the operator
            </button>
          </div>
        ) : (
          <div className="call-active">
            <div className="call-active-top">
              <span className="call-live"><span className="cc-pulse" /> LIVE · cabin {call.busId}</span>
              <span className="muted mono" style={{ fontSize: 12 }}>
                {call.direction === 'in' ? 'driver → operator' : 'operator → driver'} · since {new Date(call.startedAt).toLocaleTimeString()}
              </span>
            </div>
            <div className="call-transcript">
              {call.transcript.length === 0 && (
                <div className="muted" style={{ fontSize: 13 }}>Say something — it goes straight to the driver&apos;s speaker.</div>
              )}
              {call.transcript.map((l, i) => (
                <div key={i} className={`call-line call-line-${l.kind}`}>
                  <span className="call-who">{l.kind === 'you' ? 'You' : call.busId}</span>
                  <span className="call-text">{l.text}</span>
                  <span className="muted" style={{ fontSize: 11 }}>{l.ts}</span>
                </div>
              ))}
              {interim && <div className="call-line call-interim muted">… {interim}</div>}
            </div>
            <div className="call-active-bottom">
              {hasRecognition() ? (
                <div className="muted" style={{ fontSize: 12 }}>
                  🎙 your mic is open — the cabin speaker is live both ways
                </div>
              ) : (
                <button
                  className="btn call-answer"
                  onClick={() => {
                    const reply = DRIVER_REPLIES[Math.floor(Math.random() * DRIVER_REPLIES.length)].replace('{bus}', call.busId)
                    addLine('driver', reply)
                    say(reply)
                  }}
                >
                  🎙 Driver reply (demo)
                </button>
              )}
              <button className="btn call-hangup" onClick={hangup}>⏹ End call</button>
            </div>
          </div>
        )}
      </div>

      {/* bus list */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Buses</h3>
          <input
            className="call-search"
            placeholder="Search bus / route / reg…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="call-rows">
          {filtered.length === 0 && <div className="empty">No buses match.</div>}
          {filtered.map((b) => {
            const isOn = onThisCall === b.bus_id
            const busyOther = onCall && !isOn
            return (
              <div key={b.bus_id} className={`call-row ${isOn ? 'call-row-on' : ''} ${busyOther ? 'call-row-busy' : ''}`}>
                <div className="call-row-id">
                  <strong>{b.bus_id}</strong>
                  <span className="muted" style={{ fontSize: 12 }}>{label(b)}</span>
                </div>
                {isOn ? (
                  <button className="btn call-connected" onClick={hangup}>☎ On call · End</button>
                ) : (
                  <>
                    <button
                      className="btn call-dial"
                      disabled={busyOther}
                      onClick={() => outboundCall(b.bus_id, label(b))}
                    >
                      📞 Call
                    </button>
                    <button
                      className="btn call-ring"
                      disabled={busyOther}
                      title="Simulate the driver pressing the in-bus CALL button — rings the control room"
                      onClick={() => simulateIncoming(b.bus_id, label(b))}
                    >
                      📲 Driver calls you
                    </button>
                  </>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}