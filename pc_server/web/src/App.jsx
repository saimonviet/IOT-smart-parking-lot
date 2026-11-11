import { createContext, useContext, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, setToken } from './api'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import History from './pages/History.jsx'
import Analytics from './pages/Analytics.jsx'
import Devices from './pages/Devices.jsx'
import LayoutSettings from './pages/LayoutSettings.jsx'
import Vehicles from './pages/Vehicles.jsx'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

export default function App() {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!getToken()) return setReady(true)
    api('/auth/me').then(setUser).catch(() => setToken('')).finally(() => setReady(true))
  }, [])

  const login = (token, u) => { setToken(token); setUser(u) }
  const logout = () => { setToken(''); setUser(null) }

  if (!ready) return <div className="splash">Đang tải…</div>

  return (
    <AuthCtx.Provider value={{ user, login, logout }}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route element={user ? <Layout /> : <Navigate to="/login" replace />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/vehicles" element={<Vehicles />} />
          <Route path="/history" element={<History />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/devices" element={<Devices />} />
          <Route path="/layout-settings" element={<LayoutSettings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthCtx.Provider>
  )
}
