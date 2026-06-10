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
  if (user?.is_admin) return <Navigate to="/admin" replace />
  if (!user?.onboarding_complete) return <Navigate to="/onboarding" replace />
  return <Navigate to="/community" replace />
}

export default function App() {
  const { token, setUser, logout } = useAuthStore()
  const { theme, accent, density } = useSettingsStore()

  // Apply persisted appearance settings on every mount
  useEffect(() => {
    applySettings(theme, accent, density)
  }, [theme, accent, density])

  // Refresh user on mount to pick up changes since last session
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
