/**
 * SystemHealth.jsx - Phase 19: System Health Status Component
 *
 * Displays the health status of all subsystems with:
 * - Overall system health indicator
 * - Per-subsystem health status
 * - Data freshness indicators
 * - Error counts and last errors
 * - Degraded mode warnings
 *
 * Key principle: A missing subsystem must never silently appear healthy.
 */

import { useState, useEffect } from 'react'
import { useAuth } from '../lib/authContext.jsx'

const HEALTH_CONFIG = {
  HEALTHY: { color: '#16a34a', icon: '●', label: 'Healthy' },
  DEGRADED: { color: '#d97706', icon: '⚠', label: 'Degraded' },
  DISCONNECTED: { color: '#dc2626', icon: '○', label: 'Disconnected' },
  STARTING: { color: '#2563eb', icon: '◌', label: 'Starting' },
  STOPPING: { color: '#6b7280', icon: '◌', label: 'Stopping' },
  FAILED: { color: '#dc2626', icon: '✗', label: 'Failed' },
  RECOVERING: { color: '#d97706', icon: '↻', label: 'Recovering' },
  UNKNOWN: { color: '#6b7280', icon: '?', label: 'Unknown' },
}

const FRESHNESS_CONFIG = {
  FRESH: { color: '#16a34a', label: 'Fresh' },
  STALE: { color: '#d97706', label: 'Stale' },
  UNAVAILABLE: { color: '#dc2626', label: 'Unavailable' },
  UNKNOWN: { color: '#6b7280', label: 'Unknown' },
}

function HealthBadge({ state, compact = false }) {
  const config = HEALTH_CONFIG[state] || HEALTH_CONFIG.UNKNOWN
  return (
    <span
      className="chip"
      style={{
        margin: 0,
        fontSize: compact ? 10 : 11,
        color: config.color,
        backgroundColor: `${config.color}15`,
      }}
    >
      {config.icon} {config.label}
    </span>
  )
}

function FreshnessBadge({ freshness }) {
  const config = FRESHNESS_CONFIG[freshness] || FRESHNESS_CONFIG.UNKNOWN
  return (
    <span
      className="chip"
      style={{
        margin: 0,
        fontSize: 10,
        color: config.color,
        backgroundColor: `${config.color}15`,
      }}
    >
      {config.label}
    </span>
  )
}

function SubsystemRow({ name, health }) {
  const healthConfig = HEALTH_CONFIG[health.state] || HEALTH_CONFIG.UNKNOWN
  const freshnessConfig = FRESHNESS_CONFIG[health.freshness] || FRESHNESS_CONFIG.UNKNOWN

  // Format last success time
  const lastSuccess = health.last_success
    ? new Date(health.last_success * 1000).toLocaleTimeString()
    : 'Never'

  // Format last error time (from last_state_change if error exists)
  const lastError = health.last_error || 'None'

  return (
    <div
      className="flex justify-between align-center"
      style={{
        padding: '8px 12px',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <div className="flex align-center" style={{ gap: 8, flex: 1 }}>
        <span style={{ color: healthConfig.color, fontSize: 12 }}>
          {healthConfig.icon}
        </span>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            {name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
          </div>
          {health.error_count > 0 && (
            <div className="muted" style={{ fontSize: 10 }}>
              {health.error_count} error{health.error_count !== 1 ? 's' : ''}
            </div>
          )}
        </div>
      </div>

      <div className="flex align-center" style={{ gap: 8 }}>
        <HealthBadge state={health.state} compact />
        <FreshnessBadge freshness={health.freshness} />
        <span className="muted" style={{ fontSize: 10, minWidth: 60, textAlign: 'right' }}>
          {lastSuccess}
        </span>
      </div>
    </div>
  )
}

export function SystemHealthPanel({ compact = false }) {
  const { user } = useAuth()
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!user?.token) return

    const fetchHealth = async () => {
      try {
        const response = await fetch('/api/system/health', {
          headers: {
            'Authorization': `Bearer ${user.token}`,
          },
        })
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const data = await response.json()
        setHealth(data)
        setError(null)
      } catch (err) {
        setError(err.message)
        setHealth(null)
      } finally {
        setLoading(false)
      }
    }

    fetchHealth()
    const interval = setInterval(fetchHealth, 10000) // Refresh every 10s
    return () => clearInterval(interval)
  }, [user?.token])

  if (loading) {
    return (
      <div className="card" style={{ padding: 16 }}>
        <div className="muted">Loading system health...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card" style={{ padding: 16 }}>
        <div className="flex align-center" style={{ gap: 8 }}>
          <span style={{ color: '#dc2626' }}>✗</span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#dc2626' }}>
              Health Check Failed
            </div>
            <div className="muted" style={{ fontSize: 10 }}>{error}</div>
          </div>
        </div>
      </div>
    )
  }

  if (!health) {
    return (
      <div className="card" style={{ padding: 16 }}>
        <div className="muted">No health data available</div>
      </div>
    )
  }

  const overallConfig = HEALTH_CONFIG[health.overall] || HEALTH_CONFIG.UNKNOWN
  const subsystems = health.subsystems || {}
  const subsystemCount = Object.keys(subsystems).length
  const healthyCount = Object.values(subsystems).filter(s => s.state === 'HEALTHY').length
  const degradedCount = Object.values(subsystems).filter(s =>
    s.state === 'DEGRADED' || s.state === 'FAILED' || s.state === 'DISCONNECTED'
  ).length

  if (compact) {
    return (
      <div className="flex align-center" style={{ gap: 8 }}>
        <HealthBadge state={health.overall} compact />
        <span className="muted" style={{ fontSize: 10 }}>
          {healthyCount}/{subsystemCount} healthy
        </span>
        {degradedCount > 0 && (
          <span style={{ fontSize: 10, color: '#d97706' }}>
            {degradedCount} degraded
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="card">
      <div className="flex justify-between align-center" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <div className="flex align-center" style={{ gap: 8 }}>
          <span style={{ color: overallConfig.color, fontSize: 16 }}>
            {overallConfig.icon}
          </span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>
              System Health
            </div>
            <div className="muted" style={{ fontSize: 10 }}>
              {healthyCount}/{subsystemCount} subsystems healthy
              {degradedCount > 0 && ` • ${degradedCount} degraded`}
            </div>
          </div>
        </div>
        <HealthBadge state={health.overall} />
      </div>

      <div style={{ maxHeight: 400, overflowY: 'auto' }}>
        {Object.entries(subsystems).map(([name, subHealth]) => (
          <SubsystemRow key={name} name={name} health={subHealth} />
        ))}
      </div>

      {health.timestamp && (
        <div className="muted" style={{ padding: '8px 16px', fontSize: 10, borderTop: '1px solid var(--border)' }}>
          Last updated: {new Date(health.timestamp).toLocaleTimeString()}
        </div>
      )}
    </div>
  )
}

export default SystemHealthPanel
