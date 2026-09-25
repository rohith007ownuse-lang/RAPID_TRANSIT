import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import RequireRole from './components/RequireRole.jsx'
import { useAuth } from './lib/authContext.jsx'
import Dashboard from './pages/Dashboard.jsx'
import LiveFleet from './pages/LiveFleet.jsx'
import BusDetails from './pages/BusDetails.jsx'
import CallCenter from './pages/CallCenter.jsx'
import Incidents from './pages/Incidents.jsx'
import RoadIntelligence from './pages/RoadIntelligence.jsx'
import VehicleHealth from './pages/VehicleHealth.jsx'
import DriverSafety from './pages/DriverSafety.jsx'
import LoadManagement from './pages/LoadManagement.jsx'
import RouteMap from './pages/RouteMap.jsx'
import Analytics from './pages/Analytics.jsx'
import Settings from './pages/Settings.jsx'
import FeatureToggles from './pages/FeatureToggles.jsx'
import Users from './pages/Users.jsx'
import Login from './pages/Login.jsx'
import RouteIntelligence from './pages/RouteIntelligence.jsx'
import HistoricalIntelligence from './pages/HistoricalIntelligence.jsx'
import Emergency from './pages/Emergency.jsx'
import AISuggestions from './pages/AISuggestions.jsx'

export default function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="app-loading">
        <div className="app-loading-spinner" />
        <div className="app-loading-text">Rapid Transit</div>
        <div className="app-loading-sub">Loading…</div>
      </div>
    )
  }

  // Unauthenticated: only the login route is reachable.
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <Layout>
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/" element={<Dashboard />} />
        <Route path="/fleet" element={<LiveFleet />} />
        <Route path="/fleet/:busId" element={<BusDetails />} />
        <Route path="/calls" element={<CallCenter />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/roads" element={<RoadIntelligence />} />
        <Route path="/routes" element={<RouteMap />} />
        <Route path="/route-intelligence" element={<RouteIntelligence />} />
        <Route path="/historical" element={<HistoricalIntelligence />} />
        <Route path="/emergency" element={<Emergency />} />
        <Route path="/ai-suggestions" element={<AISuggestions />} />
        <Route path="/health" element={<VehicleHealth />} />
        <Route path="/driver-safety" element={<DriverSafety />} />
        <Route path="/load-management" element={<LoadManagement />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/settings" element={<RequireRole roles={['admin']}><Settings /></RequireRole>} />
        <Route path="/features" element={<RequireRole roles={['admin']}><FeatureToggles /></RequireRole>} />
        <Route path="/users" element={<RequireRole roles={['admin']}><Users /></RequireRole>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
