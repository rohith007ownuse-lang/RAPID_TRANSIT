export function StatusBadge({ status }) {
  const map = {
    NORMAL: ['green', 'badge-green'],
    'HIGH LOAD': ['amber', 'badge-amber'],
    OVERLOAD: ['red', 'badge-red'],
    'CRITICAL OVERLOAD': ['red', 'badge-red'],
    WARNING: ['amber', 'badge-amber'],
    'INSPECTION REQUIRED': ['red', 'badge-red'],
    WATCH: ['green', 'badge-green'],
    ALERT: ['amber', 'badge-amber'],
    'CRITICAL FATIGUE': ['red', 'badge-red'],
    ACTIVE: ['red', 'badge-red'],
    ACKNOWLEDGED: ['amber', 'badge-amber'],
    RESOLVED: ['green', 'badge-green'],
    ATTENTION: ['amber', 'badge-amber'],
    DROWSY: ['red', 'badge-red'],
    CRITICAL: ['red', 'badge-red'],
    'CRITICAL CROWDING': ['red', 'badge-red'],
    MODERATE: ['amber', 'badge-amber'],
    HIGH: ['amber', 'badge-amber'],
    LOW: ['green', 'badge-green'],
    MEDIUM: ['amber', 'badge-amber'],
    MAJOR: ['red', 'badge-red'],
    MINOR: ['amber', 'badge-amber'],
  }
  const cls = map[status] || map[status?.toUpperCase()] || ['blue', 'badge-blue']
  return <span className={`badge ${cls[1]}`}>{status || '—'}</span>
}

export function riskTone(level) {
  if (level === 'CRITICAL' || level === 'HIGH') return 'var(--red)'
  if (level === 'MEDIUM') return 'var(--amber)'
  return 'var(--green)'
}

export function RiskBadge({ level, className = '' }) {
  return (
    <span
      className={`risk-badge ${className}`}
      style={{ background: riskTone(level) }}
      title={`Risk level ${level}`}
    >
      {level}
    </span>
  )
}

export function Dot({ color }) {
  return <span className={`dot dot-${color}`} />
}

export function StatCard({ label, value, icon, tone = 'blue', hint }) {
  const tones = {
    blue: { bg: 'var(--accent-soft)', color: 'var(--accent)' },
    green: { bg: 'var(--green-soft)', color: 'var(--green)' },
    amber: { bg: 'var(--amber-soft)', color: 'var(--amber)' },
    red: { bg: 'var(--red-soft)', color: 'var(--red)' },
  }
  const t = tones[tone] || tones.blue
  return (
    <div className="stat-card">
      <div
        className="stat-icon"
        style={{
          width: 38,
          height: 38,
          borderRadius: 10,
          display: 'grid',
          placeItems: 'center',
          background: t.bg,
          color: t.color,
        }}
      >
        {icon}
      </div>
      <div className="stat-label" style={{ marginTop: 8 }}>{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{hint}</div>}
    </div>
  )
}