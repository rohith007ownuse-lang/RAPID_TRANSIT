/**
 * websocket.js - Phase 18: WebSocket Client with Hardening
 *
 * Provides reliable WebSocket connection with:
 * - Connection lifecycle management
 * - Exponential backoff reconnection
 * - Message deduplication
 * - Heartbeat/ping mechanism
 * - State resynchronization after reconnect
 * - Connection status indicator support
 *
 * Architecture:
 * - Single shared WebSocket connection for all pages
 * - REST APIs remain the source of truth
 * - WebSocket is the real-time delivery mechanism
 * - After reconnect, state is recovered from REST APIs
 */

import { useState, useEffect, useCallback, useRef } from 'react'

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const WS_PORT = 8765

// Build a WebSocket URL that survives an HTTPS deployment.
//
// - VITE_WS_URL (set at build time) pins the API host explicitly, for the
//   common split where the frontend is served by one host and the API by
//   another. It may be absolute ("https://api.example.com") or a
//   same-origin path ("/"); https/http are upgraded to wss/ws so the browser
//   never blocks the socket as mixed content.
// - Without it, the socket is derived from the page origin, so serving the
//   SPA and the API behind one host (or an nginx proxy) needs no config.
export function wsUrl(path = '/', port) {
  const configured = (import.meta.env && import.meta.env.VITE_WS_URL) || ''
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1'

  let url
  if (configured) {
    url = new URL(configured, origin)
  } else {
    const secure = typeof window !== 'undefined' && window.location.protocol === 'https:'
    url = new URL(`${secure ? 'wss' : 'ws'}://${typeof window !== 'undefined' ? window.location.host : '127.0.0.1'}${path}`)
    if (port) url.port = String(port)
    return url.toString()
  }

  url.protocol = url.protocol === 'https:' ? 'wss:' : url.protocol === 'http:' ? 'ws:' : url.protocol
  if (port) url.port = String(port)
  const base = url.pathname.replace(/\/+$/, '')
  url.pathname = `${base}${path.startsWith('/') ? path : `/${path}`}`
  return url.toString()
}

const RECONNECT_BASE_DELAY = 1000  // 1 second
const RECONNECT_MAX_DELAY = 30000  // 30 seconds
const RECONNECT_MAX_ATTEMPTS = 0   // 0 = infinite

const HEARTBEAT_INTERVAL = 15000   // 15 seconds
const STALE_TIMEOUT = 60000        // 60 seconds

const DEDUP_WINDOW_MS = 300000     // 5 minutes

// ---------------------------------------------------------------------------
// Connection states
// ---------------------------------------------------------------------------

export const ConnectionState = {
  DISCONNECTED: 'DISCONNECTED',
  CONNECTING: 'CONNECTING',
  CONNECTED: 'CONNECTED',
  AUTHENTICATING: 'AUTHENTICATING',
  READY: 'READY',
  RECONNECTING: 'RECONNECTING',
  ERROR: 'ERROR',
}

// ---------------------------------------------------------------------------
// Message deduplication
// ---------------------------------------------------------------------------

class MessageDeduplicator {
  constructor(windowMs = DEDUP_WINDOW_MS) {
    this._window = windowMs
    this._seen = new Map()  // event_id -> timestamp
  }

  isDuplicate(eventId) {
    if (!eventId) return false

    const now = Date.now()
    const cutoff = now - this._window

    // Clean old entries
    for (const [id, ts] of this._seen) {
      if (ts < cutoff) this._seen.delete(id)
      else break  // Map maintains insertion order
    }

    // Check if seen
    if (this._seen.has(eventId)) return true

    // Record new event
    this._seen.set(eventId, now)
    return false
  }

  clear() {
    this._seen.clear()
  }
}

// ---------------------------------------------------------------------------
// Exponential backoff calculator
// ---------------------------------------------------------------------------

function calculateBackoff(attempt, base = RECONNECT_BASE_DELAY, maxDelay = RECONNECT_MAX_DELAY) {
  const delay = Math.min(base * Math.pow(2, attempt), maxDelay)
  // Add jitter: 50-100% of calculated delay
  return delay * (0.5 + Math.random() * 0.5)
}

// ---------------------------------------------------------------------------
// WebSocket client class
// ---------------------------------------------------------------------------

class FleetWebSocketClient {
  constructor() {
    this._ws = null
    this._state = ConnectionState.DISCONNECTED
    this._token = null
    this._reconnectAttempts = 0
    this._reconnectTimer = null
    this._heartbeatTimer = null
    this._lastMessage = null
    this._lastConnected = null
    this._deduplicator = new MessageDeduplicator()
    this._listeners = new Map()  // event_type -> Set<callback>
    this._stateListeners = new Set()
    this._messageQueue = []
  }

  // --- Connection lifecycle ---

  connect(token) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      return  // Already connected
    }

    this._token = token
    this._setState(ConnectionState.CONNECTING)

    const url = wsUrl('/', WS_PORT)
    try {
      this._ws = new WebSocket(url)
    } catch (err) {
      console.error('[ws] Failed to create WebSocket:', err)
      this._setState(ConnectionState.ERROR)
      this._scheduleReconnect()
      return
    }

    this._ws.onopen = () => {
      console.log('[ws] Connected')
      this._setState(ConnectionState.CONNECTED)
      this._lastConnected = Date.now()
      this._reconnectAttempts = 0
      this._authenticate()
    }

    this._ws.onmessage = (event) => {
      this._handleMessage(event.data)
    }

    this._ws.onerror = (error) => {
      console.error('[ws] Error:', error)
      this._setState(ConnectionState.ERROR)
    }

    this._ws.onclose = (event) => {
      console.log('[ws] Disconnected:', event.code, event.reason)
      this._cleanup()
      this._setState(ConnectionState.DISCONNECTED)

      // Auto-reconnect unless intentionally closed
      if (event.code !== 1000) {
        this._scheduleReconnect()
      }
    }
  }

  disconnect() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }
    this._stopHeartbeat()
    if (this._ws) {
      this._ws.close(1000, 'Client disconnect')
    }
    this._setState(ConnectionState.DISCONNECTED)
  }

  // --- Authentication ---

  _authenticate() {
    if (!this._token) {
      console.error('[ws] No token for authentication')
      return
    }

    this._setState(ConnectionState.AUTHENTICATING)
    this._send({
      type: 'subscribe_alerts',
      token: this._token,
    })
  }

  // --- Message handling ---

  _handleMessage(raw) {
    try {
      const msg = JSON.parse(raw)
      this._lastMessage = Date.now()

      // Handle different message types
      switch (msg.type) {
        case 'subscribe_ok':
          console.log('[ws] Authenticated as:', msg.user, msg.role)
          this._setState(ConnectionState.READY)
          this._startHeartbeat()
          this._flushQueue()
          this._emit('connected', msg)
          break

        case 'alert':
          if (!this._deduplicator.isDuplicate(msg.alert?.event_id)) {
            this._emit('alert', msg.alert)
          }
          break

        case 'road_event':
          if (!this._deduplicator.isDuplicate(msg.event?.event_id)) {
            this._emit('road_event', msg.event)
          }
          break

        case 'road_risk_update':
          this._emit('road_risk_update', msg)
          break

        case 'state_snapshot':
          console.log('[ws] State snapshot received:', msg.bus_count, 'buses,', msg.event_count, 'events')
          this._emit('state_snapshot', msg)
          break

        case 'pong':
          // Server-initiated pong - connection is alive
          break

        case 'pong_alerts':
          // Response to our ping
          break

        case 'error':
          console.error('[ws] Server error:', msg.reason)
          this._emit('error', msg)
          break

        default:
          console.log('[ws] Unknown message type:', msg.type)
      }
    } catch (err) {
      console.error('[ws] Failed to parse message:', err)
    }
  }

  // --- Reconnection ---

  _scheduleReconnect() {
    if (RECONNECT_MAX_ATTEMPTS > 0 && this._reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
      console.log('[ws] Max reconnect attempts reached')
      return
    }

    const delay = calculateBackoff(this._reconnectAttempts)
    console.log(`[ws] Reconnecting in ${Math.round(delay)}ms (attempt ${this._reconnectAttempts + 1})`)

    this._setState(ConnectionState.RECONNECTING)
    this._reconnectAttempts++

    this._reconnectTimer = setTimeout(() => {
      this.connect(this._token)
    }, delay)
  }

  // --- Heartbeat ---

  _startHeartbeat() {
    this._stopHeartbeat()
    this._heartbeatTimer = setInterval(() => {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        this._send({ type: 'ping_alerts' })
      }
    }, HEARTBEAT_INTERVAL)
  }

  _stopHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer)
      this._heartbeatTimer = null
    }
  }

  // --- State resynchronization ---

  requestStateSnapshot() {
    if (this._state === ConnectionState.READY) {
      this._send({ type: 'request_state' })
    }
  }

  // --- Event listeners ---

  on(eventType, callback) {
    if (!this._listeners.has(eventType)) {
      this._listeners.set(eventType, new Set())
    }
    this._listeners.get(eventType).add(callback)
    return () => this.off(eventType, callback)
  }

  off(eventType, callback) {
    const listeners = this._listeners.get(eventType)
    if (listeners) {
      listeners.delete(callback)
    }
  }

  _emit(eventType, data) {
    const listeners = this._listeners.get(eventType)
    if (listeners) {
      for (const callback of listeners) {
        try {
          callback(data)
        } catch (err) {
          console.error('[ws] Listener error:', err)
        }
      }
    }
  }

  // --- State listeners ---

  onStateChange(callback) {
    this._stateListeners.add(callback)
    return () => this._stateListeners.delete(callback)
  }

  _setState(newState) {
    const oldState = this._state
    this._state = newState
    for (const callback of this._stateListeners) {
      try {
        callback(oldState, newState)
      } catch (err) {
        console.error('[ws] State listener error:', err)
      }
    }
  }

  // --- Utilities ---

  _send(data) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(data))
    } else {
      this._messageQueue.push(data)
    }
  }

  _flushQueue() {
    while (this._messageQueue.length > 0) {
      const msg = this._messageQueue.shift()
      this._send(msg)
    }
  }

  _cleanup() {
    this._stopHeartbeat()
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }
  }

  // --- Public getters ---

  get state() { return this._state }
  get isConnected() { return this._state === ConnectionState.READY }
  get lastMessage() { return this._lastMessage }
  get lastConnected() { return this._lastConnected }
  get reconnectAttempts() { return this._reconnectAttempts }
}

// ---------------------------------------------------------------------------
// Singleton instance
// ---------------------------------------------------------------------------

let _client = null

export function getWebSocketClient() {
  if (!_client) {
    _client = new FleetWebSocketClient()
  }
  return _client
}

// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------

/**
 * Hook to use WebSocket connection with automatic lifecycle management.
 *
 * @param {string} token - Authentication token
 * @returns {{ state, isConnected, lastMessage, connect, disconnect }}
 */
export function useWebSocket(token) {
  const clientRef = useRef(null)
  const [state, setState] = useState(ConnectionState.DISCONNECTED)
  const [lastMessage, setLastMessage] = useState(null)

  useEffect(() => {
    const client = getWebSocketClient()
    clientRef.current = client

    // Subscribe to state changes
    const unsubState = client.onStateChange((_, newState) => {
      setState(newState)
    })

    // Connect if token is provided
    if (token) {
      client.connect(token)
    }

    return () => {
      unsubState()
      // Don't disconnect on unmount - keep connection alive for other components
    }
  }, [token])

  useEffect(() => {
    const client = clientRef.current
    if (!client) return

    const unsub = client.on('alert', () => {
      setLastMessage(Date.now())
    })

    return unsub
  }, [])

  const connect = useCallback(() => {
    if (clientRef.current && token) {
      clientRef.current.connect(token)
    }
  }, [token])

  const disconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect()
    }
  }, [])

  return {
    state,
    isConnected: state === ConnectionState.READY,
    lastMessage,
    connect,
    disconnect,
  }
}

/**
 * Hook to subscribe to WebSocket events with automatic cleanup.
 *
 * @param {string} eventType - Event type to subscribe to
 * @param {Function} callback - Callback function
 * @param {boolean} enabled - Whether to enable the subscription
 */
export function useWebSocketEvent(eventType, callback, enabled = true) {
  useEffect(() => {
    if (!enabled) return

    const client = getWebSocketClient()
    const unsub = client.on(eventType, callback)

    return unsub
  }, [eventType, callback, enabled])
}

export default {
  ConnectionState,
  getWebSocketClient,
  useWebSocket,
  useWebSocketEvent,
}
