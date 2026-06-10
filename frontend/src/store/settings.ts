import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark'
export type Accent = 'blue' | 'purple' | 'green' | 'orange' | 'rose'
export type Density = 'compact' | 'normal' | 'comfortable'

interface SettingsState {
  theme: Theme
  accent: Accent
  density: Density
  setTheme: (t: Theme) => void
  setAccent: (a: Accent) => void
  setDensity: (d: Density) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'light',
      accent: 'blue',
      density: 'normal',
      setTheme: (theme) => set({ theme }),
      setAccent: (accent) => set({ accent }),
      setDensity: (density) => set({ density }),
    }),
    { name: 'community-ai-settings' }
  )
)

export function applySettings(theme: Theme, accent: Accent, density: Density) {
  const root = document.documentElement

  // Theme
  root.classList.toggle('dark', theme === 'dark')

  // Accent — remove all, add current
  root.classList.remove('accent-purple', 'accent-green', 'accent-orange', 'accent-rose')
  if (accent !== 'blue') root.classList.add(`accent-${accent}`)

  // Density
  root.classList.remove('density-compact', 'density-normal', 'density-comfortable')
  root.classList.add(`density-${density}`)
}
