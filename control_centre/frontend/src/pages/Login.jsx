import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/authContext.jsx'
import { BrandLogo } from '../components/UI.jsx'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <BrandLogo size={56} />
          <div>
            <div className="brand-name">Rapid Transit</div>
            <div className="brand-sub">City Public Transport · Control Centre</div>
          </div>
        </div>
        <div className="muted" style={{ fontSize: 12.5, textAlign: 'center' }}>
          Sign in to access the fleet control console.
        </div>

        <div className="login-form">
          <label className="login-label" htmlFor="username">Username</label>
          <input
            id="username"
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />

          <label className="login-label" htmlFor="password">Password</label>
          <input
            id="password"
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />

          {error && <div className="login-error">{error}</div>}

          <button className="btn-login" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign In'}
          </button>
        </div>

        <div className="login-footer">
          Rapid Transit · Protected access for authorized operators only.
        </div>
      </form>
    </div>
  )
}