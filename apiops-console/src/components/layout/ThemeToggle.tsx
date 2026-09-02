import { Moon, Sun } from 'lucide-react'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import type { Theme } from '../../app/App'

type ThemeToggleProps = {
  theme: Theme
  onChange: (theme: Theme) => void
}

export function ThemeToggle({ theme, onChange }: ThemeToggleProps) {
  const { t } = useConsoleLanguage()
  const nextTheme: Theme = theme === 'dark' ? 'light' : 'dark'
  const Icon = theme === 'dark' ? Sun : Moon
  const label = nextTheme === 'light' ? t('common.switchToLightTheme') : t('common.switchToDarkTheme')

  return (
    <button
      aria-label={label}
      className="theme-toggle"
      onClick={() => onChange(nextTheme)}
      title={label}
      type="button"
    >
      <Icon size={18} strokeWidth={1.7} />
    </button>
  )
}
