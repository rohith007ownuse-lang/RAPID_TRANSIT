import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ModeProvider } from './lib/modeContext.jsx'
import { AuthProvider, useAuth } from './lib/authContext.jsx'
import { onUnauthorized } from './api.js'
import App from './App.jsx'
import './theme.css'

// When the backend rejects a session (401), tear down local auth state so the
// app redirects to the login screen. This is a redirect convenience only; the
// backend never trusts the browser.
function AuthSessionBridge() {
  const { user, logout } = useAuth()
  React.useEffect(() => {
    if (!user) return undefined
    return onUnauthorized(() => logout())
  }, [user, logout])
  return null
}

function Root() {
  return (
    <AuthProvider>
      <ModeProvider>
        <AuthSessionBridge />
        <App />
      </ModeProvider>
    </AuthProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Root />
    </BrowserRouter>
  </React.StrictMode>,
)
