import { ChevronDown, LogOut, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'

function getInitials(username: string) {
  return username
    .split(/[\s._-]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export function UserMenu() {
  const { currentUser, signOut } = useAuth()
  const { t } = useConsoleLanguage()
  const { currentProject } = useProject()
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = 'current-user-menu'
  const projectAccessLabel = currentProject ? t(`project.role.${currentProject.projectRole}`) : t('project.noProjectSelected')

  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  if (!currentUser) return null

  return (
    <div className="user-menu-container" ref={menuRef}>
      <button
        aria-controls={menuId}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t('common.userMenu')}
        className="user-menu"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span className="avatar-placeholder" aria-hidden="true">
          {getInitials(currentUser.username) || <UserRound size={16} strokeWidth={1.8} />}
        </span>
        <span className="user-menu-trigger-copy">
          <strong>{currentUser.username}</strong>
          <span>{projectAccessLabel}</span>
        </span>
        <ChevronDown size={15} strokeWidth={1.8} />
      </button>

      {open ? (
        <div className="user-menu-popover" id={menuId} role="menu">
          <div className="user-menu-profile">
            <strong>{currentUser.username}</strong>
            <span>{t('auth.userId')}: {currentUser.id}</span>
          </div>
          <div className="user-menu-access">
            <span>{t('project.currentProject')}</span>
            <strong>{currentProject ? currentProject.projectName : t('project.noProjectSelected')}</strong>
            <small>{t('project.access')}: {projectAccessLabel}</small>
          </div>
          <div className="user-menu-session-note">{t('auth.javaSession')}</div>
          <button className="user-menu-signout" onClick={signOut} role="menuitem" type="button">
            <LogOut size={16} strokeWidth={1.8} />
            {t('auth.signOut')}
          </button>
        </div>
      ) : null}
    </div>
  )
}
