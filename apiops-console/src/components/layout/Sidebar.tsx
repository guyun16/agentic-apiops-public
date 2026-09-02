import {
  BarChart3,
  Box,
  ChevronLeft,
  CirclePlay,
  GitBranch,
  LayoutDashboard,
  ScanSearch,
  Settings,
  Stethoscope,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'

type SidebarProps = {
  activeItem: string
  collapsed: boolean
  onCollapse: () => void
  onSelect: (item: string) => void
}

type NavigationItem = {
  label: string
  translationKey: string
  icon: LucideIcon
}

const navigationItems: NavigationItem[] = [
  { label: 'Overview', translationKey: 'nav.overview', icon: LayoutDashboard },
  { label: 'API Studio', translationKey: 'nav.apiStudio', icon: Box },
  { label: 'Runs', translationKey: 'nav.runs', icon: CirclePlay },
  { label: 'Diagnosis Studio', translationKey: 'nav.diagnosisStudio', icon: Stethoscope },
  { label: 'Diagnosis', translationKey: 'nav.diagnosis', icon: ScanSearch },
  { label: 'Traces', translationKey: 'nav.traces', icon: GitBranch },
  { label: 'Evaluation', translationKey: 'nav.evaluation', icon: BarChart3 },
  { label: 'Settings', translationKey: 'nav.settings', icon: Settings },
]

export function Sidebar({ activeItem, collapsed, onCollapse, onSelect }: SidebarProps) {
  const { t, ui } = useConsoleLanguage()

  return (
    <aside className="sidebar">
      <nav className="sidebar-nav" aria-label={ui('Primary navigation')}>
        {navigationItems.map(({ label, translationKey, icon: Icon }) => (
          <button
            className={`nav-item${activeItem === label ? ' is-active' : ''}`}
            key={label}
            onClick={() => onSelect(label)}
            title={collapsed ? t(translationKey) : undefined}
            type="button"
          >
            <Icon size={19} strokeWidth={1.8} />
            <span className="nav-label">{t(translationKey)}</span>
          </button>
        ))}
      </nav>

      <button
        aria-label={collapsed ? t('common.expand') : t('common.collapse')}
        className="collapse-button"
        onClick={onCollapse}
        title={collapsed ? t('common.expand') : t('common.collapse')}
        type="button"
      >
        <ChevronLeft size={17} strokeWidth={1.8} />
        <span className="nav-label">{collapsed ? t('common.expand') : t('common.collapse')}</span>
      </button>
    </aside>
  )
}
