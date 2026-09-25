import React from 'react'
import { usePoll, api } from '../api'
import { TrafficAnalyticsPanel } from '../components/BackendOnlyPanels'

// NOTE: this page is rendered INSIDE <Layout> by App.jsx. It must not import
// or nest <Layout> again — nesting it re-renders the entire app shell (sidebar,
// topbar, dashboard content) inside the page, which made opening Route
// Intelligence look like the whole dashboard opening a second time.
const CLASS_COLORS = {
  GREEN: '#16a34a',
  AMBER: '#d97706',
  RED: '#dc2626',
  CRITICAL: '#991b1b',
}

function HealthBar({ score, classification }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <div style={{
        width: '100px',
        height: '8px',
        background: '#e5e7eb',
        borderRadius: '4px',
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${score}%`,
          height: '100%',
          background: CLASS_COLORS[classification] || '#6b7280',
          borderRadius: '4px',
        }} />
      </div>
      <span style={{ fontSize: '12px', fontWeight: 600, color: CLASS_COLORS[classification] }}>
        {score}/100
      </span>
    </div>
  )
}

function RecommendationCard({ rec }) {
  const priorityColors = {
    URGENT: '#dc2626',
    HIGH: '#ea580c',
    MEDIUM: '#d97706',
    LOW: '#16a34a',
  }
  return (
    <div style={{
      padding: '8px 12px',
      borderLeft: `3px solid ${priorityColors[rec.priority] || '#6b7280'}`,
      background: '#f9fafb',
      borderRadius: '0 6px 6px 0',
      marginBottom: '6px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '12px', fontWeight: 600 }}>{rec.action}</span>
        <span style={{
          fontSize: '10px',
          padding: '1px 6px',
          borderRadius: '8px',
          color: '#fff',
          background: priorityColors[rec.priority] || '#6b7280',
        }}>
          {rec.priority}
        </span>
      </div>
      <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '4px' }}>{rec.detail}</div>
    </div>
  )
}

function RouteCard({ route, onClick, isSelected }) {
  return (
    <div
      onClick={() => onClick(route.route_code)}
      style={{
        padding: '10px 12px',
        border: `2px solid ${isSelected ? CLASS_COLORS[route.classification] : '#e5e7eb'}`,
        borderRadius: '8px',
        cursor: 'pointer',
        marginBottom: '6px',
        background: isSelected ? '#f9fafb' : '#fff',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontWeight: 600, fontSize: '13px' }}>{route.route_code}</span>
          <span style={{ fontSize: '11px', color: '#6b7280', marginLeft: '6px' }}>
            {route.bus_count} bus{route.bus_count !== 1 ? 'es' : ''}
          </span>
        </div>
        <span style={{
          padding: '2px 8px',
          borderRadius: '12px',
          fontSize: '11px',
          fontWeight: 600,
          color: '#fff',
          background: CLASS_COLORS[route.classification] || '#6b7280',
        }}>
          {route.classification}
        </span>
      </div>
      <div style={{ marginTop: '6px' }}>
        <HealthBar score={route.health_score} classification={route.classification} />
      </div>
      {route.incidents && route.incidents.total > 0 && (
        <div style={{ marginTop: '4px', fontSize: '11px', color: '#dc2626' }}>
          {route.incidents.total} incident(s)
          {route.incidents.critical > 0 && ` (${route.incidents.critical} critical)`}
        </div>
      )}
    </div>
  )
}

export default function RouteIntelligence() {
  const [routeData, setRouteData] = React.useState({})
  const [cityOverview, setCityOverview] = React.useState(null)
  const [recommendations, setRecommendations] = React.useState([])
  const [selectedRoute, setSelectedRoute] = React.useState(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [intel, overview, recs] = await Promise.all([
          api.routesIntelligence(),
          api.cityOverview(),
          api.routeRecommendations(),
        ])
        if (alive) {
          setRouteData(intel?.routes || {})
          setCityOverview(overview)
          setRecommendations(recs?.recommendations || [])
          setLoading(false)
        }
      } catch (e) {
        if (alive) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 15000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const routes = Object.values(routeData)
  const selected = selectedRoute ? routeData[selectedRoute] : null

  if (loading) return <div style={{ padding: 16 }}>Loading route intelligence...</div>

  return (
    <div style={{ padding: 16 }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 700 }}>Route Intelligence</h2>
        <p style={{ margin: '0 0 16px', fontSize: 12, color: '#6b7280' }}>
          Vehicle → Route → Corridor → Hotspot → City hierarchy
        </p>

        {/* City Overview */}
        {cityOverview && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            gap: '8px',
            marginBottom: '16px',
          }}>
            {[
              { label: 'Total Routes', value: cityOverview.total_routes, color: '#374151' },
              { label: 'Total Buses', value: cityOverview.total_buses, color: '#374151' },
              { label: 'Overall Health', value: `${cityOverview.overall_health}/100`, color: cityOverview.overall_health >= 75 ? '#16a34a' : cityOverview.overall_health >= 50 ? '#d97706' : '#dc2626' },
              { label: 'GREEN Routes', value: cityOverview.classification_counts?.GREEN || 0, color: '#16a34a' },
              { label: 'RED/CRITICAL', value: (cityOverview.classification_counts?.RED || 0) + (cityOverview.classification_counts?.CRITICAL || 0), color: '#dc2626' },
            ].map((item, i) => (
              <div key={i} style={{ padding: '10px', background: '#f3f4f6', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '20px', fontWeight: 700, color: item.color }}>{item.value}</div>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>{item.label}</div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {/* Route List */}
          <div>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Routes by Health</h3>
            <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
              {routes.map((route) => (
                <RouteCard
                  key={route.route_code}
                  route={route}
                  onClick={setSelectedRoute}
                  isSelected={selectedRoute === route.route_code}
                />
              ))}
            </div>
          </div>

          {/* Detail Panel */}
          <div>
            {selected ? (
              <div>
                <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                  {selected.route_code} — {selected.route_name}
                </h3>
                <div style={{
                  padding: '12px',
                  background: '#f9fafb',
                  borderRadius: '8px',
                  marginBottom: '12px',
                }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                    {Object.entries(selected.metrics || {}).map(([key, val]) => (
                      <div key={key} style={{ fontSize: '12px' }}>
                        <span style={{ color: '#6b7280' }}>{key.replace(/_/g, ' ')}: </span>
                        <span style={{ fontWeight: 600 }}>{val}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Recommendations</h4>
                {selected.recommendations?.map((rec, i) => (
                  <RecommendationCard key={i} rec={rec} />
                ))}
              </div>
            ) : (
              <div style={{ padding: '24px', textAlign: 'center', color: '#6b7280', fontSize: 13 }}>
                Select a route to view details
              </div>
            )}
          </div>
        </div>

        {/* Recommendations */}
        <TrafficAnalyticsPanel />
        {recommendations.length > 0 && (
          <div style={{ marginTop: '16px' }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>All Recommendations</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
              {recommendations.map((rec, i) => (
                <div key={i} style={{
                  padding: '10px 12px',
                  border: '1px solid #e5e7eb',
                  borderRadius: '6px',
                  fontSize: '12px',
                }}>
                  <span style={{ fontWeight: 600, color: '#6b7280' }}>{rec.route_code}</span>
                  <span style={{ marginLeft: '8px' }}>{rec.action}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
  )
}
