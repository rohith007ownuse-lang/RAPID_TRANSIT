import { useEffect, useRef } from 'react'

/**
 * BusRouteTracker — a clean vertical timeline of a route's stops.
 *
 * States (derived from currentStopIndex):
 *  - passed   (i < currentStopIndex): solid gray dot, dimmed name
 *  - current  (i === currentStopIndex): accent dot + glow ring, bold name,
 *             "bus is here" label
 *  - upcoming (i > currentStopIndex): hollow dot, normal weight name
 *
 * currentStopIndex is intentionally a plain prop so it can later be driven by
 * live GPS map-matching. When it changes the highlighted stop re-centres in
 * the view automatically (no reload).
 */
export default function BusRouteTracker({ name, start, end, stops = [], currentStopIndex = 0, state }) {
  const listRef = useRef(null)
  const currentRowRef = useRef(null)

  useEffect(() => {
    const row = currentRowRef.current
    const list = listRef.current
    if (!row || !list) return
    const rowTop = row.offsetTop - list.offsetTop
    const target = rowTop - list.clientHeight / 2 + row.clientHeight / 2
    list.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
  }, [currentStopIndex])

  const label = state === 'AT_STOP' ? '🛑 At stop' : state === 'ARRIVING' ? '⏳ Arriving' : '🚌 Moving'

  return (
    <div className="route-tracker">
      <div className="route-tracker-header">
        <div className="route-tracker-title">{name}</div>
        <div className="route-tracker-line-head">
          <span className="muted">{start}</span>
          <span className="route-arrow">→</span>
          <span className="muted">{end}</span>
        </div>
        <div className="route-tracker-status">
          <span className="chip">{label}</span>
          <span className="chip">📍 {stops[currentStopIndex]?.stop}</span>
        </div>
      </div>
      <div className="route-tracker-scroll" ref={listRef}>
        <div className="route-tracker-list">
          <div className="route-tracker-line" />
          {stops.map((s, i) => {
            const passed = i < currentStopIndex
            const current = i === currentStopIndex
            const mid = i > currentStopIndex
            const cls = ['route-stop']
            if (passed) cls.push('passed')
            if (current) cls.push('current')
            if (mid) cls.push('upcoming')
            return (
              <div
                key={`${s.stop}-${i}`}
                ref={current ? currentRowRef : undefined}
                className={cls.join(' ')}
              >
                <span className="route-stop-dot" />
                <div className="route-stop-body">
                  <span className="route-stop-name">
                    {s.stop}
                    {s.major && <em className="route-stop-major">major</em>}
                  </span>
                  <span className="route-stop-meta">
                    {s.boarded > 0 ? `${s.boarded} boarded` : 'no boarding'}
                  </span>
                  {current && <span className="route-stop-here">bus is here</span>}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}