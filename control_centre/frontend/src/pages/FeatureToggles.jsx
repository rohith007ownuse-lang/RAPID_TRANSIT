import { useState, useEffect } from 'react'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { api } from '../api.js'

// Default feature states
const DEFAULT_FEATURES = {
  // Camera & AI
  camera_driver: { enabled: true, label: 'Driver Camera', icon: '🎥', category: 'Camera & AI', desc: 'Driver drowsiness monitoring via webcam' },
  camera_cabin: { enabled: false, label: 'Cabin Camera', icon: '🚌', category: 'Camera & AI', desc: 'Passenger occupancy detection (needs hardware)' },
  camera_road: { enabled: false, label: 'Road Camera', icon: '🛣️', category: 'Camera & AI', desc: 'Pothole detection (needs hardware)' },
  ai_driver_dds: { enabled: true, label: 'Driver DDS Engine', icon: '👁️', category: 'Camera & AI', desc: 'EAR/MAR/drowsiness detection algorithm' },
  ai_pothole: { enabled: false, label: 'Pothole Detection', icon: '⚠️', category: 'Camera & AI', desc: 'YOLO/contour pothole detection' },
  ai_cabin: { enabled: false, label: 'Cabin AI', icon: '🔍', category: 'Camera & AI', desc: 'Passenger counting AI (needs model)' },
  camera_websocket: { enabled: true, label: '30 FPS WebSocket Stream', icon: '📡', category: 'Camera & AI', desc: 'Real-time camera streaming via WebSocket' },

  // Sensors & Hardware
  sensor_gps: { enabled: false, label: 'GPS Module', icon: '📍', category: 'Sensors & Hardware', desc: 'Real GPS coordinates from hardware' },
  sensor_imu: { enabled: false, label: 'IMU Sensor', icon: '📳', category: 'Sensors & Hardware', desc: 'Acceleration/crash detection sensor' },
  sensor_load: { enabled: false, label: 'Load Cell', icon: '⚖️', category: 'Sensors & Hardware', desc: 'Passenger weight measurement' },
  sensor_mic: { enabled: false, label: 'Microphone', icon: '🎤', category: 'Sensors & Hardware', desc: 'Siren/emergency sound detection' },
  arduino_control: { enabled: false, label: 'Arduino Motor Control', icon: '🔌', category: 'Sensors & Hardware', desc: 'Vehicle control (DISABLED for safety)' },
  serial_comm: { enabled: false, label: 'Serial Communicator', icon: '🔗', category: 'Sensors & Hardware', desc: 'Bus node ↔ Arduino communication' },

  // Safety Features
  auto_braking: { enabled: false, label: 'Automatic Braking', icon: '🛑', category: 'Safety Features', desc: 'DISABLED - Brake recommendation only' },
  audio_alerts: { enabled: true, label: 'Audio Alerts', icon: '🔊', category: 'Safety Features', desc: 'Sound warnings for drowsiness detection' },
  crash_detection: { enabled: true, label: 'Crash Detection', icon: '💥', category: 'Safety Features', desc: 'IMU-based impact detection (simulated)' },
  overload_alert: { enabled: true, label: 'Overload Alert', icon: '⚠️', category: 'Safety Features', desc: 'Passenger overload warning' },

  // Communication
  ws_alerts: { enabled: true, label: 'WebSocket Alerts', icon: '🔔', category: 'Communication', desc: 'Real-time incident notifications' },
  intercom: { enabled: true, label: 'Driver Intercom', icon: '📞', category: 'Communication', desc: 'Operator ↔ Driver communication' },
  bus_node_ws: { enabled: false, label: 'Bus Node WebSocket', icon: '📡', category: 'Communication', desc: 'ESP32/Arduino real hardware link' },

  // Fleet Simulation
  fleet_sim: { enabled: true, label: 'Fleet Simulator', icon: '🚌', category: 'Fleet Simulation', desc: '300-vehicle Chennai MTC simulation' },
  event_fusion: { enabled: true, label: 'Event Fusion Engine', icon: '🧠', category: 'Fleet Simulation', desc: 'Multi-rule event correlation' },
  risk_engine: { enabled: true, label: 'Risk Engine', icon: '📊', category: 'Fleet Simulation', desc: 'Bus risk scoring and prediction' },
  eta_prediction: { enabled: true, label: 'ETA Prediction', icon: '⏱️', category: 'Fleet Simulation', desc: 'Arrival time estimation' },

  // Emergency Services
  emergency_data: { enabled: true, label: 'Emergency Facility Data', icon: '🏥', category: 'Emergency Services', desc: '197 Chennai facilities (police/fire/hospital)' },
  emergency_map: { enabled: true, label: 'Emergency Map Layer', icon: '🗺️', category: 'Emergency Services', desc: 'Show facilities on route map' },
  emergency_response: { enabled: true, label: 'Incident Response AI', icon: '🚨', category: 'Emergency Services', desc: 'Auto-recommend nearby facilities' },

  // Analytics
  analytics_dashboard: { enabled: true, label: 'Analytics Dashboard', icon: '📈', category: 'Analytics', desc: 'Boardings, fares, incidents analytics' },
  predictive_health: { enabled: true, label: 'Predictive Health', icon: '🔧', category: 'Analytics', desc: 'Vehicle maintenance prediction' },
  demand_forecast: { enabled: true, label: 'Demand Forecasting', icon: '📊', category: 'Analytics', desc: 'Passenger demand prediction' },
}

function ToggleSwitch({ enabled, onChange, disabled = false }) {
  return (
    <button
      onClick={() => !disabled && onChange(!enabled)}
      disabled={disabled}
      style={{
        width: 44,
        height: 24,
        borderRadius: 12,
        border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: enabled ? '#16a34a' : '#d1d5db',
        position: 'relative',
        transition: 'background 0.2s',
        opacity: disabled ? 0.5 : 1,
        flexShrink: 0,
      }}
    >
      <div style={{
        width: 18,
        height: 18,
        borderRadius: '50%',
        background: '#fff',
        position: 'absolute',
        top: 3,
        left: enabled ? 23 : 3,
        transition: 'left 0.2s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </button>
  )
}

function FeatureCard({ feature, enabled, onChange }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      padding: '10px 14px',
      borderRadius: 8,
      border: `1px solid ${enabled ? '#bbf7d0' : '#e5e7eb'}`,
      background: enabled ? '#f0fdf4' : '#fff',
      transition: 'all 0.2s',
    }}>
      <span style={{ fontSize: 20, flexShrink: 0 }}>{feature.icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#1f2937' }}>
            {feature.label}
          </span>
        </div>
        <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
          {feature.desc}
        </div>
      </div>
      <ToggleSwitch enabled={enabled} onChange={onChange} />
    </div>
  )
}

export default function FeatureToggles() {
  const [features, setFeatures] = useState(DEFAULT_FEATURES)
  const [filter, setFilter] = useState('all')
  const [savedMsg, setSavedMsg] = useState('')
  const [loading, setLoading] = useState(true)

  // Load from backend on mount
  useEffect(() => {
    let alive = true
    const loadFeatures = async () => {
      try {
        const data = await api.getFeatures()
        if (!alive) return
        // Merge backend states with frontend metadata
        const merged = { ...DEFAULT_FEATURES }
        for (const [key, enabled] of Object.entries(data)) {
          if (merged[key]) {
            merged[key] = { ...merged[key], enabled }
          }
        }
        setFeatures(merged)
      } catch (e) {
        console.error('Failed to load features:', e)
        // Fall back to localStorage
        try {
          const saved = localStorage.getItem('rapid_feature_toggles')
          if (saved) {
            const parsed = JSON.parse(saved)
            setFeatures({ ...DEFAULT_FEATURES, ...parsed })
          }
        } catch (e2) { /* ignore */ }
      } finally {
        setLoading(false)
      }
    }
    loadFeatures()
    return () => { alive = false }
  }, [])

  const toggleFeature = async (key) => {
    const newEnabled = !features[key].enabled
    
    // Optimistic update
    setFeatures(prev => ({
      ...prev,
      [key]: { ...prev[key], enabled: newEnabled }
    }))
    
    try {
      // Sync with backend
      await api.toggleFeature(key, newEnabled)
      setSavedMsg(`✓ ${features[key].label} ${newEnabled ? 'enabled' : 'disabled'}`)
      setTimeout(() => setSavedMsg(''), 2000)
    } catch (e) {
      console.error('Failed to toggle feature:', e)
      // Revert on error
      setFeatures(prev => ({
        ...prev,
        [key]: { ...prev[key], enabled: !newEnabled }
      }))
      setSavedMsg(`✗ Failed to update ${features[key].label}`)
      setTimeout(() => setSavedMsg(''), 3000)
    }
    
    // Also save to localStorage as backup
    localStorage.setItem('rapid_feature_toggles', JSON.stringify(features))
  }

  // Group features by category
  const categories = {}
  for (const [key, feature] of Object.entries(features)) {
    if (!categories[feature.category]) categories[feature.category] = []
    categories[feature.category].push({ key, ...feature })
  }

  const filteredCategories = filter === 'all'
    ? categories
    : { [filter]: categories[filter] || [] }

  const enabledCount = Object.values(features).filter(f => f.enabled).length
  const totalCount = Object.keys(features).length

  return (
    <>
      <PageHeader
        title="Feature Toggles"
        sub={`Enable or disable system features · ${enabledCount}/${totalCount} active`}
        right={<SimBadge />}
      />

      {/* Summary bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '12px 16px',
        background: '#f8fafc',
        border: '1px solid #e2e8f0',
        borderRadius: 10,
        marginBottom: 16,
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {['all', ...Object.keys(categories)].map(cat => (
              <button
                key={cat}
                onClick={() => setFilter(cat)}
                style={{
                  padding: '4px 12px',
                  borderRadius: 14,
                  border: filter === cat ? '1.5px solid #2563eb' : '1px solid #e2e8f0',
                  background: filter === cat ? '#eff6ff' : '#fff',
                  color: filter === cat ? '#2563eb' : '#64748b',
                  fontSize: 11,
                  fontWeight: filter === cat ? 600 : 400,
                  cursor: 'pointer',
                  fontFamily: 'system-ui, sans-serif',
                }}
              >
                {cat === 'all' ? 'All' : cat}
              </button>
            ))}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#16a34a', fontFamily: 'monospace' }}>
            {enabledCount}
          </div>
          <div style={{ fontSize: 10, color: '#6b7280' }}>of {totalCount} enabled</div>
        </div>
        {savedMsg && (
          <div style={{ fontSize: 12, color: '#16a34a', fontWeight: 600 }}>
            ✓ {savedMsg}
          </div>
        )}
      </div>

      {/* Feature categories */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {Object.entries(filteredCategories).map(([category, items]) => (
          <div key={category} className="card">
            <div className="card-header">
              <h3 className="card-title">{category}</h3>
              <span className="badge badge-blue" style={{ fontSize: 10 }}>
                {items.filter(f => f.enabled).length}/{items.length}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {items.map(feature => (
                <FeatureCard
                  key={feature.key}
                  feature={feature}
                  enabled={feature.enabled}
                  onChange={() => toggleFeature(feature.key)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Reset button */}
      <div style={{ marginTop: 20, display: 'flex', gap: 12 }}>
        <button
          className="btn"
          onClick={() => {
            if (confirm('Reset all features to defaults?')) {
              setFeatures(DEFAULT_FEATURES)
              setSavedMsg('Reset to defaults')
              setTimeout(() => setSavedMsg(''), 2000)
            }
          }}
        >
          ↺ Reset to Defaults
        </button>
        <button
          className="btn"
          onClick={() => {
            const allEnabled = {}
            for (const [key, feature] of Object.entries(features)) {
              allEnabled[key] = { ...feature, enabled: true }
            }
            setFeatures(allEnabled)
            // Sync all to backend
            const flat = {}
            for (const [key] of Object.entries(features)) flat[key] = true
            api.updateFeatures(flat).catch(() => {})
            setSavedMsg('All features enabled')
            setTimeout(() => setSavedMsg(''), 2000)
          }}
        >
          ✓ Enable All
        </button>
        <button
          className="btn"
          onClick={() => {
            // Disable all except core
            const core = ['fleet_sim', 'emergency_data', 'analytics_dashboard']
            const minimal = {}
            for (const [key, feature] of Object.entries(features)) {
              minimal[key] = { ...feature, enabled: core.includes(key) }
            }
            setFeatures(minimal)
            setSavedMsg('Minimal mode enabled')
            setTimeout(() => setSavedMsg(''), 2000)
          }}
        >
          ● Minimal Mode
        </button>
        <button
          className="btn btn-primary"
          onClick={async () => {
            try {
              const res = await fetch('/api/test-audio', { method: 'POST' })
              const data = await res.json()
              if (data.ok) {
                setSavedMsg('🔊 Playing test sound...')
              } else {
                setSavedMsg('✗ Audio error: ' + data.error)
              }
              setTimeout(() => setSavedMsg(''), 3000)
            } catch (e) {
              setSavedMsg('✗ Could not reach server')
              setTimeout(() => setSavedMsg(''), 3000)
            }
          }}
        >
          🔊 Test Sound
        </button>
      </div>

      {/* Info box */}
      <div style={{
        marginTop: 16,
        padding: '12px 16px',
        background: '#f0f9ff',
        border: '1px solid #bae6fd',
        borderRadius: 8,
        fontSize: 12,
        color: '#0369a1',
        lineHeight: 1.6,
      }}>
        <strong>ℹ️ How it works:</strong>
        <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
          <li>Click any toggle to turn features ON or OFF</li>
          <li>Changes are saved to the server automatically</li>
          <li>Some features need hardware to work when enabled</li>
        </ul>
      </div>
    </>
  )
}
