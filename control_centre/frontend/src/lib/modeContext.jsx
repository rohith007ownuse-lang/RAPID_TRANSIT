import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

const ModeContext = createContext(null)

export function ModeProvider({ children }) {
  const [mode, setMode] = useState('simulation')
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [liveStatus, setLiveStatus] = useState({
    connected: false,
    nodes: [],
    connected_count: 0,
  })

  // Fetch current mode on mount
  useEffect(() => {
    api.getMode()
      .then((data) => {
        setMode(data.mode)
        setLiveStatus({
          connected: data.connected_count > 0,
          nodes: data.connected_nodes,
          connected_count: data.connected_count,
        })
      })
      .catch(() => {
        // Default to simulation on error
        setMode('simulation')
      })
      .finally(() => setLoading(false))
  }, [])

  // Poll live status when in live mode
  useEffect(() => {
    if (mode !== 'live') return
    const interval = setInterval(() => {
      api.liveStatus()
        .then((data) => {
          setLiveStatus({
            connected: data.connected_count > 0,
            nodes: data.nodes || [],
            connected_count: data.connected_count,
          })
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
  }, [mode])

  const switchMode = useCallback(async (newMode) => {
    if (switching) return
    setSwitching(true)
    try {
      const result = await api.switchMode(newMode)
      setMode(result.mode)
      // Reset live status when switching
      if (newMode === 'simulation') {
        setLiveStatus({ connected: false, nodes: [], connected_count: 0 })
      }
      return result
    } finally {
      setSwitching(false)
    }
  }, [switching])

  const value = {
    mode,
    isSimulation: mode === 'simulation',
    isLive: mode === 'live',
    loading,
    switching,
    switchMode,
    liveStatus,
  }

  return (
    <ModeContext.Provider value={value}>
      {children}
    </ModeContext.Provider>
  )
}

export function useMode() {
  const context = useContext(ModeContext)
  if (!context) {
    throw new Error('useMode must be used within a ModeProvider')
  }
  return context
}
