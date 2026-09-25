import { Navigate } from 'react-router-dom'
import { useAuth } from '../lib/authContext.jsx'

export default function RequireRole({ roles, children }) {
  const { user, loading } = useAuth()

  if (loading) return null
  if (!user) return <Navigate to="/login" replace />

  if (roles && !roles.includes(user.role)) {
    return (
      <div className="card empty" style={{ margin: 40, textAlign: 'center' }}>
        <div style={{ fontSize: 32 }}>🔒</div>
        <h3>Access denied</h3>
        <p className="muted">Your role ({user.role}) does not have permission to view this page.</p>
      </div>
    )
  }

  return children
}
