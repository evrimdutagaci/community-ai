import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { useSettingsStore, applySettings } from './store/settings'
import { api } from './api/client'
import Login from './pages/Login'
import Register from './pages/Register'
import Onboarding from './pages/Onboarding'
import Community from './pages/Community'
import Admin from './pages/Admin'
import Settings from './pages/Settings'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function HomeRedirect() {
  const { token, user } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  // Admin check comes before onboarding_complete because admins bypass onboarding
  if (user?.is_admin) return <Navigate to="/admin" replace />
  if (!user?.onboarding_complete) return <Navigate to="/onboarding" replace />
  return <Navigate to="/community" replace />
}

export default function App() {
  const { token, setUser, logout } = useAuthStore()
  const { theme, accent, density } = useSettingsStore()

  // Re-apply classes whenever settings change so Tailwind variants stay in sync
  useEffect(() => {
    applySettings(theme, accent, density)
  }, [theme, accent, density])

  // Refresh user on mount: the localStorage snapshot can be stale if the server
  // updated onboarding_complete or is_admin since last visit. 401 → clear token.
  useEffect(() => {
    if (token) {
      api.me().then(setUser).catch(() => logout())
    }
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomeRedirect />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
        <Route path="/community" element={<RequireAuth><Community /></RequireAuth>} />
        <Route path="/admin" element={<RequireAuth><Admin /></RequireAuth>} />
        <Route path="/settings" element={<RequireAuth><Settings /></RequireAuth>} />
      </Routes>
    </BrowserRouter>
  )
}
