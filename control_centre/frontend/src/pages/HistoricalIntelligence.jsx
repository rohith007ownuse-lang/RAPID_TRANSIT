import React from 'react'
import { api } from '../api'
import { HistoricalHotspotsPatternsPanel } from '../components/BackendOnlyPanels'

// NOTE: this page is rendered INSIDE <Layout> by App.jsx. It must not import
// or nest <Layout> again — nesting it re-renders the entire app shell (sidebar,
// topbar, dashboard content) inside the page, which made opening Historical
// look like the whole dashboard opening a second time.

const WINDOWS = ['24h', '7d', '30d']

function HotspotCard({ hotspot }) {
  return (
    <div style={{
      padding: '10px 12px',
      border: '1px solid #e5e7eb',
      borderRadius: '8px',
      marginBottom: '6px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '12px', fontWeight: 600 }}>
          {hotspot.location?.lat?.toFixed(4)}, {hotspot.location?.lon?.toFixed(4)}
        </span>
        <span style={{
          padding: '2px 8px',
          borderRadius: '12px',
          fontSize: '10px',
          fontWeight: 600,
          color: '#fff',
          background: hotspot.pattern === 'RECURRING' ? '#dc2626' : '#d97706',
        }}>
          {hotspot.pattern}
        </span>
      </div>
      <div style={{ marginTop: '4px', fontSize: '11px', color: '#6b7280' }}>
        {hotspot.incident_count} incidents over {hotspot.unique_days} day(s)
      </div>
      <div style={{ marginTop: '2px', fontSize: '11px', color: '#6b7280' }}>
        First: {hotspot.first_seen?.split('T')[0]} | Last: {hotspot.last_seen?.split('T')[0]}
      </div>
      {hotspot.event_types && (
        <div style={{ marginTop: '4px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          {Object.entries(hotspot.event_types).map(([type, count]) => (
            <span key={type} style={{
              fontSize: '10px',
              padding: '1px 6px',
              background: '#f3f4f6',
              borderRadius: '4px',
            }}>
              {type} ({count})
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function PeakPeriodCard({ peak }) {
  return (
    <div style={{
      padding: '8px 12px',
      background: '#f9fafb',
      borderRadius: '6px',
      marginBottom: '4px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
    }}>
      <span style={{ fontSize: '12px', fontWeight: 500 }}>
        {typeof peak.hour === 'number' ? `${peak.hour}:00` : peak.date || peak.day}
      </span>
      <span style={{ fontSize: '12px', fontWeight: 700, color: '#dc2626' }}>
        {peak.count} events
      </span>
    </div>
  )
}

function VehicleTrendCard({ trend }) {
  const trendColors = {
    DEGRADING: '#dc2626',
    STABLE: '#d97706',
    IMPROVING: '#16a34a',
  }
  return (
    <div style={{
      padding: '8px 12px',
      border: `1px solid ${trendColors[trend.health_trend] || '#e5e7eb'}`,
      borderRadius: '6px',
      marginBottom: '4px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
    }}>
      <div>
        <span style={{ fontSize: '12px', fontWeight: 600 }}>{trend.bus_id}</span>
        <span style={{ fontSize: '11px', color: '#6b7280', marginLeft: '8px' }}>
          Risk: {trend.current_risk}/100
        </span>
      </div>
      <span style={{
        padding: '2px 8px',
        borderRadius: '12px',
        fontSize: '10px',
        fontWeight: 600,
        color: '#fff',
        background: trendColors[trend.health_trend] || '#6b7280',
      }}>
        {trend.health_trend}
      </span>
    </div>
  )
}

export default function HistoricalIntelligence() {
  const [window, setWindow] = React.useState('7d')
  const [data, setData] = React.useState(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        setLoading(true)
        const result = await api.historicalComprehensive(window)
        if (alive) {
          setData(result)
          setLoading(false)
        }
      } catch (e) {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => { alive = false }
  }, [window])

  const hotspots = data?.recurring_hotspots?.recurring_hotspots || []
  const patterns = data?.route_delay_patterns?.patterns || []
  const peaks = data?.peak_periods?.peak_hours || []
  const trends = data?.vehicle_health_trends?.bus_trends || []
  const peakStats = data?.peak_periods || {}
  const trendStats = data?.vehicle_health_trends || {}

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 700 }}>Historical Intelligence</h2>
      <p style={{ margin: '0 0 16px', fontSize: 12, color: '#6b7280' }}>
        What keeps happening — patterns, trends, and recurring issues
        {data?.simulation && (
          <span className="chip" style={{ marginLeft: 8, fontSize: 10, background: '#dbeafe', color: '#1d4ed8' }}>
            ◈ ESTIMATED — simulated from live fleet state (no persisted logs yet)
          </span>
        )}
      </p>

        {/* Time Window Selector */}
        <div style={{ display: 'flex', gap: '6px', marginBottom: '16px' }}>
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              style={{
                padding: '6px 16px',
                borderRadius: '6px',
                border: '1px solid #d1d5db',
                background: window === w ? '#111827' : '#fff',
                color: window === w ? '#fff' : '#374151',
                fontSize: '12px',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              {w}
            </button>
          ))}
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>Loading...</div>
        ) : (
          <>
          <HistoricalHotspotsPatternsPanel window={window} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {/* Recurring Hotspots */}
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                Recurring Hotspots ({hotspots.length})
              </h3>
              <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                {hotspots.length === 0 ? (
                  <div style={{ padding: 16, color: '#6b7280', fontSize: 12, textAlign: 'center' }}>
                    No recurring hotspots in this window
                  </div>
                ) : (
                  hotspots.map((h, i) => <HotspotCard key={i} hotspot={h} />)
                )}
              </div>
            </div>

            {/* Peak Periods */}
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                Peak Problem Hours
              </h3>
              {peakStats.total_events > 0 && (
                <div style={{ marginBottom: '8px', fontSize: '11px', color: '#6b7280' }}>
                  {peakStats.total_events} total events | Trend: {peakStats.daily_trend}
                </div>
              )}
              {peaks.length === 0 ? (
                <div style={{ padding: 16, color: '#6b7280', fontSize: 12, textAlign: 'center' }}>
                  No peak data available
                </div>
              ) : (
                peaks.map((p, i) => <PeakPeriodCard key={i} peak={p} />)
              )}
            </div>

            {/* Route Delay Patterns */}
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                Route Delay Patterns
              </h3>
              {patterns.length === 0 ? (
                <div style={{ padding: 16, color: '#6b7280', fontSize: 12, textAlign: 'center' }}>
                  No delay patterns detected
                </div>
              ) : (
                patterns.map((p, i) => (
                  <div key={i} style={{
                    padding: '8px 12px',
                    border: '1px solid #e5e7eb',
                    borderRadius: '6px',
                    marginBottom: '4px',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: '12px', fontWeight: 600 }}>{p.route_code}</span>
                      <span style={{ fontSize: '12px', color: '#dc2626', fontWeight: 600 }}>
                        Peak: {p.peak_delay_hour}:00 ({p.peak_delay_minutes} min)
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Vehicle Health Trends */}
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                Vehicle Health Trends
              </h3>
              {trendStats.total_buses > 0 && (
                <div style={{ marginBottom: '8px', fontSize: '11px', color: '#6b7280' }}>
                  {trendStats.degrading} degrading | {trendStats.stable} stable | {trendStats.improving} improving
                </div>
              )}
              <div style={{ maxHeight: '250px', overflowY: 'auto' }}>
                {trends.length === 0 ? (
                  <div style={{ padding: 16, color: '#6b7280', fontSize: 12, textAlign: 'center' }}>
                    No vehicle trend data available
                  </div>
                ) : (
                  trends.map((t, i) => <VehicleTrendCard key={i} trend={t} />)
                )}
              </div>
            </div>
          </div>
          </>
        )}
      </div>
  )
}
