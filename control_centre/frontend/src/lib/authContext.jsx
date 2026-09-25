import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react'
import { api } from '../api.js'

const TOKEN_KEY = 'aiuc_token'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refreshRef = useRef(0)

  // Validate the stored token (if any) on load so role/spoofed storage never
  // grants access: the backend re-checks every request anyway.
  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    refreshToken(token)
      .catch(() => {}) // already handled inside refreshToken
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function refreshToken(tok) {
    try {
      const data = await api.me(tok)
      setUser(data.user)
      setToken(tok)
      localStorage.setItem(TOKEN_KEY, tok)
      setError(null)
      return data
    } catch (e) {
      clearAuth()
      setError('Your session has expired. Please log in again.')
      throw e
    }
  }

  async function login(username, password) {
    const data = await api.login({ username, password })
    setUser(data.user)
    setToken(data.token)
    localStorage.setItem(TOKEN_KEY, data.token)
    setError(null)
    return data
  }

  function clearAuth() {
    setUser(null)
    setToken(null)
    localStorage.removeItem(TOKEN_KEY)
  }

  async function logout() {
    try {
      if (token) await api.logout(token)
    } finally {
      clearAuth()
    }
  }

  const value = {
    user,
    token,
    loading,
    error,
    isAuthenticated: !!user,
    login,
    logout,
    // Role helpers (display/UX gating only — the backend is authoritative).
    can: (roles) => (user ? roles.includes(user.role) : false),
    isAdmin: user?.role === 'admin',
    isSupervisor: user?.role === 'supervisor',
    isOperator: user?.role === 'operator',
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
