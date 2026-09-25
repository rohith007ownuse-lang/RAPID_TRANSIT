export default function Gauge({ value, min = 0, max = 100, label, unit = '', color }) {
  const pct = Math.max(0, Math.min(100, (100 * (value - min)) / (max - min)))
  const c = color || (pct > 85 ? 'var(--red)' : pct > 60 ? 'var(--amber)' : 'var(--green)')
  const r = 40
  const circ = 2 * Math.PI * r
  return (
    <div className="gauge-wrap">
      <svg width="110" height="100" viewBox="0 0 110 100">
        <circle cx="55" cy="58" r={r} fill="none" stroke="var(--bg-hover)" strokeWidth="10" />
        <circle
          cx="55"
          cy="58"
          r={r}
          fill="none"
          stroke={c}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${(circ * pct) / 100} ${circ}`}
          transform="rotate(-90 55 58)"
        />
        <text x="55" y="56" textAnchor="middle" fontSize="17" fontWeight="700" fill="var(--text)">
          {value}
          {unit && <tspan fontSize="11">{unit}</tspan>}
        </text>
      </svg>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
    </div>
  )
}