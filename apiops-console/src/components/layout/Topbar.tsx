import { Bell, Box, CircleHelp, Search } from 'lucide-react'
import type { Theme } from '../../app/App'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { ProjectSwitcher } from './ProjectSwitcher'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

type TopbarProps = {
  theme: Theme
  onThemeChange: (theme: Theme) => void
}

export function Topbar({ theme, onThemeChange }: TopbarProps) {
  const { t, ui } = useConsoleLanguage()

  return (
    <header className="topbar">
      <div aria-label={ui('APIOps home')} className="topbar-brand">
        <span aria-hidden="true" className="topbar-brand-mark">
          <Box size={22} strokeWidth={2.2} />
        </span>
        <span className="topbar-brand-label">Agentic APIOps Console</span>
      </div>
      <div className="topbar-project">
        <span className="topbar-project-label">{ui('Project')}</span>
        <ProjectSwitcher />
        <span className="environment-badge">{t('auth.javaPlatformBadge')}</span>
      </div>
      <div aria-label={ui('Global search')} className="topbar-search" role="search">
        <Search aria-hidden="true" size={16} strokeWidth={1.8} />
        <span>{ui('Search APIs, endpoints, runs, traces...')}</span>
        <kbd>⌘ K</kbd>
      </div>
      <div className="topbar-actions">
        <span aria-hidden="true" className="topbar-utility"><CircleHelp size={19} strokeWidth={1.7} /></span>
        <span aria-hidden="true" className="topbar-utility"><Bell size={19} strokeWidth={1.7} /></span>
        <ThemeToggle theme={theme} onChange={onThemeChange} />
        <UserMenu />
      </div>
    </header>
  )
}
