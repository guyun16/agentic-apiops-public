import { ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'

export function ProjectSwitcher() {
  const { t } = useConsoleLanguage()
  const { availableProjects, currentProject, loading, selectProject } = useProject()
  const [open, setOpen] = useState(false)
  const switcherRef = useRef<HTMLDivElement>(null)
  const menuId = 'project-context-menu'

  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (!switcherRef.current?.contains(event.target as Node)) setOpen(false)
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

  return (
    <div className="project-switcher-container" ref={switcherRef}>
      <button
        aria-controls={menuId}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${t('project.currentProject')}: ${currentProject ? currentProject.projectName : loading ? t('project.loadingProjects') : t('project.noAccessibleProjects')}`}
        className="project-switcher"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span>{currentProject ? currentProject.projectName : loading ? t('project.loadingProjects') : t('project.noAccessibleProjects')}</span>
        <ChevronDown size={16} strokeWidth={1.8} />
      </button>

      {open ? (
        <div className="project-switcher-popover" id={menuId} role="menu">
          <div className="project-switcher-heading">
            <span>{t('project.currentProject')}</span>
            <strong>{currentProject ? currentProject.projectName : loading ? t('project.loadingProjects') : t('project.noAccessibleProjects')}</strong>
          </div>
          <div className="project-switcher-menu-label">{t('project.projects')}</div>
          <div className="project-switcher-list">
            {availableProjects.length ? availableProjects.map((project) => {
              const selected = project.projectId === currentProject?.projectId
              return (
                <button
                  aria-checked={selected}
                  className={`project-switcher-item${selected ? ' is-selected' : ''}`}
                  key={project.projectId}
                  onClick={() => {
                    selectProject(project.projectId)
                    setOpen(false)
                  }}
                  role="menuitemradio"
                  type="button"
                >
                  <span className="project-switcher-item-copy">
                    <strong>{project.projectName}</strong>
                    <small>{t('project.access')}: {t(`project.role.${project.projectRole}`)}</small>
                  </span>
                  {selected ? <span className="project-switcher-check">✓</span> : null}
                </button>
              )
            }) : (
              <span className="project-switcher-empty">{loading ? t('project.loadingProjects') : t('project.noAccessibleProjects')}</span>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
