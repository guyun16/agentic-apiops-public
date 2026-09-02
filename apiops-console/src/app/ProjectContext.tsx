import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, apiFetch } from '../lib/api-client'

export type ProjectRole = 'OWNER' | 'EDITOR' | 'VIEWER'

export type AccessibleProject = {
  projectId: string
  projectName: string
  projectRole: ProjectRole
}

type AccessibleProjectResponse = {
  projectId: number
  projectName: string
  projectRole: ProjectRole
}

export const PROJECT_STORAGE_KEY = 'apiops-console-project'

type ProjectContextValue = {
  availableProjects: AccessibleProject[]
  currentProject: AccessibleProject | null
  loading: boolean
  error: ApiError | null
  selectProject: (projectId: string) => void
  switchToAccessibleProject: () => void
  refreshProjects: () => Promise<void>
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

function toProject(project: AccessibleProjectResponse): AccessibleProject {
  return {
    projectId: String(project.projectId),
    projectName: project.projectName,
    projectRole: project.projectRole,
  }
}

function getStoredProjectId() {
  if (typeof window === 'undefined') return null

  try {
    return window.localStorage.getItem(PROJECT_STORAGE_KEY)
  } catch {
    return null
  }
}

function persistProjectId(projectId: string | null) {
  try {
    if (projectId) window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId)
    else window.localStorage.removeItem(PROJECT_STORAGE_KEY)
  } catch {
    // The selected project remains session-local when storage is unavailable.
  }
}

export function ProjectProvider({ children, onSessionExpired }: { children: ReactNode; onSessionExpired: () => void }) {
  const [availableProjects, setAvailableProjects] = useState<AccessibleProject[]>([])
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | null>(null)

  const refreshProjects = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await apiFetch<AccessibleProjectResponse[]>('/api/v1/projects')
      const projects = response.map(toProject)
      setAvailableProjects(projects)
      setCurrentProjectId((currentId) => {
        const storedId = getStoredProjectId()
        const nextId = projects.some((project) => project.projectId === currentId)
          ? currentId
          : projects.some((project) => project.projectId === storedId)
            ? storedId
            : projects[0]?.projectId ?? null
        persistProjectId(nextId)
        return nextId
      })
    } catch (requestError) {
      const apiError = requestError instanceof ApiError
        ? requestError
        : new ApiError('Unable to load projects', 0, 'PROJECTS_LOAD_FAILED')
      setAvailableProjects([])
      setCurrentProjectId(null)
      setError(apiError)
      if (apiError.status === 401) onSessionExpired()
    } finally {
      setLoading(false)
    }
  }, [onSessionExpired])

  useEffect(() => {
    void refreshProjects()
  }, [refreshProjects])

  const selectProject = useCallback((projectId: string) => {
    if (!availableProjects.some((project) => project.projectId === projectId)) return
    setCurrentProjectId(projectId)
    persistProjectId(projectId)
  }, [availableProjects])

  const switchToAccessibleProject = useCallback(() => {
    const accessibleProject = availableProjects[0]
    if (accessibleProject) selectProject(accessibleProject.projectId)
  }, [availableProjects, selectProject])

  const currentProject = useMemo(
    () => availableProjects.find((project) => project.projectId === currentProjectId) ?? null,
    [availableProjects, currentProjectId],
  )

  const value = useMemo<ProjectContextValue>(() => ({
    availableProjects,
    currentProject,
    error,
    loading,
    refreshProjects,
    selectProject,
    switchToAccessibleProject,
  }), [availableProjects, currentProject, error, loading, refreshProjects, selectProject, switchToAccessibleProject])

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject() {
  const context = useContext(ProjectContext)
  if (!context) throw new Error('useProject must be used within ProjectProvider')
  return context
}
