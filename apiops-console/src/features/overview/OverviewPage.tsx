import { BarChart3, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'
import { ApiError } from '../../lib/api-client'
import { RecentDiagnosis } from './components/RecentDiagnosis'
import { RecentRuns } from './components/RecentRuns'
import { SystemHealth } from './components/SystemHealth'
import {
  fetchJavaHealth,
  fetchPythonHealth,
  fetchRecentJavaRuns,
  fetchRecentDiagnoses,
  unavailableHealthItem,
} from './overview-api'
import type { HealthItem, RecentDiagnosis as RecentDiagnosisItem } from './types'
import type { RunSummary } from '../runs/types'

type LoadState = 'loading' | 'ready' | 'error'

export type OverviewNavigationTarget = 'Runs' | 'Diagnosis'

type OverviewPageProps = {
  onNavigate?: (target: OverviewNavigationTarget) => void
}

const initialHealthItems = (): HealthItem[] => [
  unavailableHealthItem('java', 'Java Platform', 'Java /actuator/health'),
  unavailableHealthItem('python', 'Python AgentLab', 'Python /health'),
]

function toApiError(error: unknown, fallback: string) {
  return error instanceof ApiError ? error : new ApiError(fallback, 0, 'NETWORK_ERROR')
}

function isStatus(error: unknown, status: number) {
  return error instanceof ApiError && error.status === status
}

export function OverviewPage({ onNavigate }: OverviewPageProps) {
  const { expireSession } = useAuth()
  const { t, ui } = useConsoleLanguage()
  const { currentProject, loading: projectsLoading, refreshProjects } = useProject()
  const [healthItems, setHealthItems] = useState<HealthItem[]>(initialHealthItems)
  const [healthLoading, setHealthLoading] = useState(true)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsState, setRunsState] = useState<LoadState>('loading')
  const [diagnoses, setDiagnoses] = useState<RecentDiagnosisItem[]>([])
  const [diagnosisState, setDiagnosisState] = useState<LoadState>('loading')
  const [diagnosisError, setDiagnosisError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)

  const projectId = currentProject?.projectId ?? null
  const navigate = onNavigate ?? (() => undefined)

  useEffect(() => {
    let cancelled = false
    setHealthItems(initialHealthItems())
    setHealthLoading(true)
    setRuns([])
    setRunsState('loading')
    setDiagnoses([])
    setDiagnosisState('loading')
    setDiagnosisError(null)

    if (projectsLoading) {
      return () => { cancelled = true }
    }

    const controller = new AbortController()
    const runsRequest = projectId
      ? fetchRecentJavaRuns(projectId, controller.signal)
      : Promise.reject(new ApiError('No project is selected.', 0, 'PROJECT_MISSING'))
    const diagnosisRequest = projectId
      ? fetchRecentDiagnoses(projectId, controller.signal)
      : Promise.reject(new ApiError('No project is selected.', 0, 'PROJECT_MISSING'))

    void Promise.allSettled([
      fetchJavaHealth(controller.signal),
      fetchPythonHealth(controller.signal),
      runsRequest,
      diagnosisRequest,
    ]).then(([javaResult, pythonResult, runsResult, diagnosisResult]) => {
      if (cancelled) return

      const nextHealth = javaResult.status === 'fulfilled'
        ? javaResult.value
        : unavailableHealthItem('java', 'Java Platform', 'Java /actuator/health', new Date().toISOString())
      const pythonHealth = pythonResult.status === 'fulfilled'
        ? pythonResult.value
        : unavailableHealthItem('python', 'Python AgentLab', 'Python /health', new Date().toISOString())
      setHealthItems([nextHealth, pythonHealth])
      setHealthLoading(false)

      if (runsResult.status === 'fulfilled') {
        setRuns(runsResult.value)
        setRunsState('ready')
      } else {
        setRuns([])
        setRunsState('error')
      }

      if (diagnosisResult.status === 'fulfilled') {
        setDiagnoses(diagnosisResult.value)
        setDiagnosisState('ready')
      } else {
        setDiagnoses([])
        setDiagnosisError(toApiError(diagnosisResult.reason, 'Unable to load recent diagnoses.'))
        setDiagnosisState('error')
      }

      const reasons = [javaResult, pythonResult, runsResult, diagnosisResult]
        .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
        .map((result) => result.reason)
      if (reasons.some((reason) => isStatus(reason, 401))) {
        expireSession()
      } else if (reasons.some((reason) => isStatus(reason, 403))) {
        void refreshProjects()
      }
    })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, projectId, projectsLoading, refreshProjects, attempt])

  const refresh = () => setAttempt((current) => current + 1)

  return (
    <div className="overview-page">
      <header className="overview-header">
        <div>
          <h1>{t('page.overview.title')}</h1>
          <div className="overview-project-identity">
            <span aria-hidden="true" className="overview-project-mark">
              <BarChart3 size={28} strokeWidth={2} />
            </span>
            <div className="overview-project-copy">
              <strong>{currentProject?.projectName ?? t('project.noProjectSelected')}</strong>
              <span>{t('project.project')} #{currentProject?.projectId ?? '—'}</span>
            </div>
          </div>
          <p className="overview-project-description">
            {ui('Monitor system health and recent activity across your APIOps workflows.')}
          </p>
        </div>
        <div className="overview-actions">
          <button
            aria-label={ui('Refresh overview')}
            className="icon-button"
            onClick={refresh}
            title={ui('Refresh overview')}
            type="button"
          >
            <RefreshCw size={16} strokeWidth={1.8} />
          </button>
        </div>
      </header>

      <SystemHealth items={healthItems} loading={healthLoading} />

      <section aria-labelledby="recent-activity-title" className="overview-activity-section">
        <div className="overview-section-heading">
          <h2 id="recent-activity-title">{ui('Recent Activity')}</h2>
        </div>
        <div className="overview-content-grid">
          <RecentRuns onNavigate={() => navigate('Runs')} runs={runs} state={runsState} />
          <RecentDiagnosis
            error={diagnosisError}
            onNavigate={() => navigate('Diagnosis')}
            runs={diagnoses}
            state={diagnosisState}
          />
        </div>
      </section>

      <footer className="overview-footer">© 2026 Agentic APIOps Console. {ui('All rights reserved.')}</footer>
    </div>
  )
}
