/**
 * ConnectionStatus.jsx - Phase 18: WebSocket Connection Status Indicator
 *
 * Displays the current WebSocket connection state and provides
 * reconnection controls. Shows:
 * - Connected (green)
 * - Reconnecting (amber)
 * - Disconnected (red)
 * - Stale data warning
 */

import { useState, useEffect } from 'react'
import { useWebSocket, ConnectionState } from '../websocket.js'
import { useAuth } from '../lib/authContext.jsx'

const STATE_CONFIG = {
  [ConnectionState.DISCONNECTED]: {
    label: 'Disconnected',
    color: '#dc2626',
    icon: '○',
    description: 'Not connected to real-time updates',
  },
  [ConnectionState.CONNECTING]: {
    label: 'Connecting',
    color: '#d97706',
    icon: '◌',
    description: 'Establishing connection...',
  },
  [ConnectionState.CONNECTED]: {
    label: 'Connected',
    color: '#16a34a',
    icon: '●',
    description: 'Connected, authenticating...',
  },
  [ConnectionState.AUTHENTICATING]: {
    label: 'Authenticating',
    color: '#d97706',
    icon: '◌',
    description: 'Verifying credentials...',
  },
  [ConnectionState.READY]: {
    label: 'Live',
    color: '#16a34a',
    icon: '●',
    description: 'Receiving real-time updates',
  },
  [ConnectionState.RECONNECTING]: {
    label: 'Reconnecting',
    color: '#d97706',
    icon: '↻',
    description: 'Attempting to reconnect...',
  },
  [ConnectionState.ERROR]: {
    label: 'Error',
    color: '#dc2626',
    icon: '✗',
    description: 'Connection error',
  },
}

export function ConnectionStatusIndicator({ compact = false }) {
  const { user } = useAuth()
  const token = user?.token || localStorage.getItem('aiuc_token')
  const { state, isConnected, lastMessage, connect, disconnect } = useWebSocket(token)
  const [staleWarning, setStaleWarning] = useState(false)

  const config = STATE_CONFIG[state] || STATE_CONFIG[ConnectionState.DISCONNECTED]

  // Check for stale data
  useEffect(() => {
    if (!isConnected || !lastMessage) return

    const checkStale = () => {
      const elapsed = Date.now() - lastMessage
      setStaleWarning(elapsed > 60000) // 60 seconds
    }

    checkStale()
    const interval = setInterval(checkStale, 10000)
    return () => clearInterval(interval)
  }, [isConnected, lastMessage])

  if (compact) {
    return (
      <span
        className="chip"
        style={{
          margin: 0,
          fontSize: 11,
          color: config.color,
          cursor: 'pointer',
        }}
        title={config.description}
        onClick={() => isConnected ? disconnect() : connect()}
      >
        {config.icon} {config.label}
        {staleWarning && <span style={{ marginLeft: 4 }}>⚠ Stale</span>}
      </span>
    )
  }

  return (
    <div className="card" style={{ padding: 12 }}>
      <div className="flex justify-between align-center">
        <div className="flex align-center" style={{ gap: 8 }}>
          <span style={{ color: config.color, fontSize: 16 }}>{config.icon}</span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: config.color }}>
              {config.label}
            </div>
            <div className="muted" style={{ fontSize: 10 }}>
              {config.description}
            </div>
          </div>
        </div>
        <div className="flex align-center" style={{ gap: 8 }}>
          {staleWarning && (
            <span className="chip" style={{ margin: 0, fontSize: 10, color: '#d97706' }}>
              ⚠ Stale Data
            </span>
          )}
          <button
            className="btn btn-ghost"
            style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => isConnected ? disconnect() : connect()}
          >
            {isConnected ? 'Disconnect' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConnectionStatusIndicator
