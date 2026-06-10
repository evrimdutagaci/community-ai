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

// Separate localStorage key from auth store so settings survive a logout without resetting appearance
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

// Imperatively mutates <html> class list so Tailwind's dark: and custom accent/density
// variants take effect without a full re-render
export function applySettings(theme: Theme, accent: Accent, density: Density) {
  const root = document.documentElement

  root.classList.toggle('dark', theme === 'dark')

  // Blue is the CSS default so it needs no class; only non-blue accents add a class
  root.classList.remove('accent-purple', 'accent-green', 'accent-orange', 'accent-rose')
  if (accent !== 'blue') root.classList.add(`accent-${accent}`)

  root.classList.remove('density-compact', 'density-normal', 'density-comfortable')
  root.classList.add(`density-${density}`)
}
