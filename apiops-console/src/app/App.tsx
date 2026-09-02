import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './AuthContext'
import { ConsoleLanguageProvider } from './ConsoleLanguage'
import { ContextTrailProvider } from './ContextTrailContext'
import { ProjectProvider } from './ProjectContext'
import { AppShell } from '../components/layout/AppShell'
import { LoginPage } from '../features/auth/LoginPage'

export type Theme = 'dark' | 'light'
export type ThemePreference = Theme | 'system'

const THEME_STORAGE_KEY = 'apiops-console-theme'
const COMPACT_DENSITY_STORAGE_KEY = 'apiops-console-compact-density'
const REDUCED_MOTION_STORAGE_KEY = 'apiops-console-reduced-motion'
const AUTO_DIAGNOSE_STORAGE_KEY = 'apiops-console-auto-diagnose'

function getInitialThemePreference(): ThemePreference {
  if (typeof window === 'undefined') {
    return 'dark'
  }

  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
    return storedTheme === 'light' || storedTheme === 'system' ? storedTheme : 'dark'
  } catch {
    return 'dark'
  }
}

function getSystemTheme(): Theme {
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches) {
    return 'light'
  }

  return 'dark'
}

function getInitialBoolean(key: string, fallback: boolean) {
  if (typeof window === 'undefined') return fallback

  try {
    const value = window.localStorage.getItem(key)
    return value === null ? fallback : value === 'true'
  } catch {
    return fallback
  }
}

type ConsoleShellProps = {
  theme: Theme
  themePreference: ThemePreference
  onThemePreferenceChange: (theme: ThemePreference) => void
  compactDensity: boolean
  onCompactDensityChange: (enabled: boolean) => void
  reducedMotion: boolean
  onReducedMotionChange: (enabled: boolean) => void
  autoDiagnose: boolean
  onAutoDiagnoseChange: (enabled: boolean) => void
}

function AuthenticatedConsole(props: ConsoleShellProps) {
  const { expireSession, status } = useAuth()

  if (status !== 'authenticated') {
    return <LoginPage mode={status === 'loading' ? 'loading' : status === 'expired' ? 'expired' : 'login'} onThemeChange={props.onThemePreferenceChange} theme={props.theme} />
  }

  return (
    <ProjectProvider onSessionExpired={expireSession}>
      <ContextTrailProvider>
        <AppShell {...props} />
      </ContextTrailProvider>
    </ProjectProvider>
  )
}

export default function App() {
  const [themePreference, setThemePreference] = useState<ThemePreference>(getInitialThemePreference)
  const [systemTheme, setSystemTheme] = useState<Theme>(getSystemTheme)
  const [compactDensity, setCompactDensity] = useState(() => getInitialBoolean(COMPACT_DENSITY_STORAGE_KEY, true))
  const [reducedMotion, setReducedMotion] = useState(() => getInitialBoolean(REDUCED_MOTION_STORAGE_KEY, false))
  const [autoDiagnose, setAutoDiagnose] = useState(() => getInitialBoolean(AUTO_DIAGNOSE_STORAGE_KEY, true))

  useEffect(() => {
    if (themePreference !== 'system' || typeof window === 'undefined' || !window.matchMedia) return

    const mediaQuery = window.matchMedia('(prefers-color-scheme: light)')
    const updateSystemTheme = () => setSystemTheme(mediaQuery.matches ? 'light' : 'dark')
    updateSystemTheme()
    mediaQuery.addEventListener?.('change', updateSystemTheme)

    return () => mediaQuery.removeEventListener?.('change', updateSystemTheme)
  }, [themePreference])

  const theme: Theme = themePreference === 'system' ? systemTheme : themePreference

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, themePreference)
    } catch {
      // The UI remains usable when storage is unavailable.
    }
  }, [theme, themePreference])

  useEffect(() => {
    document.documentElement.dataset.density = compactDensity ? 'compact' : 'comfortable'
  }, [compactDensity])

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(reducedMotion)
  }, [reducedMotion])

  useEffect(() => {
    try {
      window.localStorage.setItem(COMPACT_DENSITY_STORAGE_KEY, String(compactDensity))
      window.localStorage.setItem(REDUCED_MOTION_STORAGE_KEY, String(reducedMotion))
      window.localStorage.setItem(AUTO_DIAGNOSE_STORAGE_KEY, String(autoDiagnose))
    } catch {
      // Preferences remain session-local when storage is unavailable.
    }
  }, [autoDiagnose, compactDensity, reducedMotion])

  return (
    <ConsoleLanguageProvider>
      <AuthProvider>
        <AuthenticatedConsole
          autoDiagnose={autoDiagnose}
          compactDensity={compactDensity}
          onAutoDiagnoseChange={setAutoDiagnose}
          onCompactDensityChange={setCompactDensity}
          onReducedMotionChange={setReducedMotion}
          onThemePreferenceChange={setThemePreference}
          reducedMotion={reducedMotion}
          theme={theme}
          themePreference={themePreference}
        />
      </AuthProvider>
    </ConsoleLanguageProvider>
  )
}
