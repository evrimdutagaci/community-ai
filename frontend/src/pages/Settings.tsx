import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import { useSettingsStore, applySettings, type Theme, type Accent, type Density } from '../store/settings'
import { api } from '../api/client'

type Tab = 'profile' | 'security' | 'appearance'

export default function Settings() {
  const navigate = useNavigate()
  const { user, setUser } = useAuthStore()
  const { theme, accent, density, setTheme, setAccent, setDensity } = useSettingsStore()

  const [tab, setTab] = useState<Tab>('profile')

  // Profile
  const [username, setUsername] = useState(user?.username ?? '')
  const [profileMsg, setProfileMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [profileSaving, setProfileSaving] = useState(false)

  // Security
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [pwSaving, setPwSaving] = useState(false)

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault()
    setProfileSaving(true)
    setProfileMsg(null)
    try {
      const updated = await api.updateProfile({ username })
      setUser(updated)
      setProfileMsg({ ok: true, text: 'Username updated.' })
    } catch (err: any) {
      setProfileMsg({ ok: false, text: err.message })
    } finally {
      setProfileSaving(false)
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault()
    if (newPw !== confirmPw) {
      setPwMsg({ ok: false, text: 'New passwords do not match.' })
      return
    }
    setPwSaving(true)
    setPwMsg(null)
    try {
      await api.changePassword({ current_password: currentPw, new_password: newPw })
      setPwMsg({ ok: true, text: 'Password changed.' })
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err: any) {
      setPwMsg({ ok: false, text: err.message })
    } finally {
      setPwSaving(false)
    }
  }

  // Each handler calls both the store setter (persists to localStorage) and applySettings
  // directly so the UI updates immediately without waiting for a re-render from the store
  function handleTheme(t: Theme) {
    setTheme(t)
    applySettings(t, accent, density)
  }

  function handleAccent(a: Accent) {
    setAccent(a)
    applySettings(theme, a, density)
  }

  function handleDensity(d: Density) {
    setDensity(d)
    applySettings(theme, accent, d)
  }

  const tabCls = (t: Tab) =>
    `px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
      tab === t
        ? 'bg-blue-600 text-white'
        : 'text-gray-600 hover:bg-gray-100'
    }`

  const inputCls = 'w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  const ACCENTS: { value: Accent; label: string; swatch: string }[] = [
    { value: 'blue',   label: 'Blue',   swatch: 'bg-blue-500' },
    { value: 'purple', label: 'Purple', swatch: 'bg-purple-500' },
    { value: 'green',  label: 'Green',  swatch: 'bg-green-500' },
    { value: 'orange', label: 'Orange', swatch: 'bg-orange-500' },
    { value: 'rose',   label: 'Rose',   swatch: 'bg-rose-500' },
  ]

  const DENSITIES: { value: Density; label: string; desc: string }[] = [
    { value: 'compact',     label: 'Compact',     desc: 'Smaller text and tighter spacing' },
    { value: 'normal',      label: 'Normal',      desc: 'Default size and spacing' },
    { value: 'comfortable', label: 'Comfortable', desc: 'Larger text and more spacing' },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-6 py-4 flex items-center gap-4">
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-blue-600 hover:text-blue-800 transition-colors"
        >
          ← Back
        </button>
        <h1 className="text-lg font-semibold">Settings</h1>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-8">
        {/* Tab nav */}
        <div className="flex gap-2 mb-8">
          <button className={tabCls('profile')}    onClick={() => setTab('profile')}>Profile</button>
          <button className={tabCls('security')}   onClick={() => setTab('security')}>Security</button>
          <button className={tabCls('appearance')} onClick={() => setTab('appearance')}>Appearance</button>
        </div>

        {/* Profile tab */}
        {tab === 'profile' && (
          <div className="bg-white border rounded-xl p-6 shadow-sm space-y-6">
            <div>
              <h2 className="text-base font-semibold mb-1">Profile</h2>
              <p className="text-sm text-gray-500">Update your display name.</p>
            </div>
            <form onSubmit={saveProfile} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  className={`${inputCls} opacity-60 cursor-not-allowed`}
                  value={user?.email ?? ''}
                  disabled
                />
                <p className="text-xs text-gray-400 mt-1">Email cannot be changed.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  className={inputCls}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  minLength={2}
                  maxLength={40}
                  required
                />
              </div>
              {profileMsg && (
                <p className={`text-sm ${profileMsg.ok ? 'text-green-600' : 'text-red-600'}`}>
                  {profileMsg.text}
                </p>
              )}
              <button
                type="submit"
                disabled={profileSaving}
                className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {profileSaving ? 'Saving…' : 'Save changes'}
              </button>
            </form>
          </div>
        )}

        {/* Security tab */}
        {tab === 'security' && (
          <div className="bg-white border rounded-xl p-6 shadow-sm space-y-6">
            <div>
              <h2 className="text-base font-semibold mb-1">Change password</h2>
              <p className="text-sm text-gray-500">Use a strong password of at least 8 characters.</p>
            </div>
            <form onSubmit={savePassword} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Current password</label>
                <input
                  type="password"
                  className={inputCls}
                  value={currentPw}
                  onChange={(e) => setCurrentPw(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
                <input
                  type="password"
                  className={inputCls}
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  minLength={8}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm new password</label>
                <input
                  type="password"
                  className={inputCls}
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  minLength={8}
                  required
                />
              </div>
              {pwMsg && (
                <p className={`text-sm ${pwMsg.ok ? 'text-green-600' : 'text-red-600'}`}>
                  {pwMsg.text}
                </p>
              )}
              <button
                type="submit"
                disabled={pwSaving}
                className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {pwSaving ? 'Saving…' : 'Update password'}
              </button>
            </form>
          </div>
        )}

        {/* Appearance tab */}
        {tab === 'appearance' && (
          <div className="space-y-6">
            {/* Theme */}
            <div className="bg-white border rounded-xl p-6 shadow-sm">
              <h2 className="text-base font-semibold mb-1">Theme</h2>
              <p className="text-sm text-gray-500 mb-4">Choose light or dark mode.</p>
              <div className="flex gap-3">
                {(['light', 'dark'] as Theme[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => handleTheme(t)}
                    className={`flex-1 border-2 rounded-xl p-4 text-sm font-medium transition-all capitalize ${
                      theme === t
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-gray-200 text-gray-600 hover:border-gray-300'
                    }`}
                  >
                    {t === 'light' ? '☀ Light' : '⬛ Dark'}
                  </button>
                ))}
              </div>
            </div>

            {/* Accent color */}
            <div className="bg-white border rounded-xl p-6 shadow-sm">
              <h2 className="text-base font-semibold mb-1">Accent color</h2>
              <p className="text-sm text-gray-500 mb-4">Pick the primary color used throughout the app.</p>
              <div className="flex gap-3 flex-wrap">
                {ACCENTS.map((a) => (
                  <button
                    key={a.value}
                    onClick={() => handleAccent(a.value)}
                    className={`flex items-center gap-2 border-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all ${
                      accent === a.value
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-gray-200 text-gray-600 hover:border-gray-300'
                    }`}
                  >
                    <span className={`w-3 h-3 rounded-full ${a.swatch}`} />
                    {a.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Density */}
            <div className="bg-white border rounded-xl p-6 shadow-sm">
              <h2 className="text-base font-semibold mb-1">Density</h2>
              <p className="text-sm text-gray-500 mb-4">Control text size and interface spacing.</p>
              <div className="space-y-2">
                {DENSITIES.map((d) => (
                  <button
                    key={d.value}
                    onClick={() => handleDensity(d.value)}
                    className={`w-full text-left border-2 rounded-xl px-4 py-3 transition-all ${
                      density === d.value
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <span className={`text-sm font-medium ${density === d.value ? 'text-blue-700' : 'text-gray-700'}`}>
                      {d.label}
                    </span>
                    <span className="text-xs text-gray-400 ml-2">{d.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
