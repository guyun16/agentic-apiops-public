import { useEffect, useState } from 'react'
import type { Theme, ThemePreference } from '../../app/App'
import type { ContextTrailTarget } from '../../app/ContextTrailContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'
import { ApiStudioPage } from '../../features/api-studio/ApiStudioPage'
import { DiagnosisPage } from '../../features/diagnosis/DiagnosisPage'
import { DiagnosisAgentExecutionPage } from '../../features/diagnosis-execution/DiagnosisAgentExecutionPage'
import { EvaluationPage } from '../../features/evaluation/EvaluationPage'
import { OverviewPage } from '../../features/overview/OverviewPage'
import { RunsPage } from '../../features/runs/RunsPage'
import { SettingsPage } from '../../features/settings/SettingsPage'
import { TracesPage } from '../../features/traces/TracesPage'
import { PageState } from '../common/PageState'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

type AppShellProps = {
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

type DiagnosisExecutionContext = {
  runId: string
  returnTo: 'Runs' | 'Diagnosis'
}

const SIDEBAR_STORAGE_KEY = 'apiops-console-sidebar-collapsed'

function getInitialSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="placeholder-page" aria-labelledby="placeholder-title">
      <div className="placeholder-eyebrow">APIOps workspace</div>
      <h1 id="placeholder-title">{title}</h1>
      <p>This module is reserved for the next console phase.</p>
    </section>
  )
}

export function AppShell({
  autoDiagnose,
  compactDensity,
  onAutoDiagnoseChange,
  onCompactDensityChange,
  onReducedMotionChange,
  onThemePreferenceChange,
  reducedMotion,
  theme,
  themePreference,
}: AppShellProps) {
  const { t } = useConsoleLanguage()
  const { currentProject, error: projectError, loading: projectsLoading, refreshProjects } = useProject()
  const [activeItem, setActiveItem] = useState('Overview')
  const [collapsed, setCollapsed] = useState(getInitialSidebarCollapsed)
  const [diagnosisStudioRunId, setDiagnosisStudioRunId] = useState<string | null>(null)
  const [diagnosisAgentRunId, setDiagnosisAgentRunId] = useState<string | null>(null)
  const [executionContext, setExecutionContext] = useState<DiagnosisExecutionContext | null>(null)
  const [apiStudioTarget, setApiStudioTarget] = useState<Extract<ContextTrailTarget, { type: 'endpoint' | 'testcase' }> | null>(null)
  const [runsTargetId, setRunsTargetId] = useState<number | null>(null)
  const [tracesTargetId, setTracesTargetId] = useState<string | null>(null)

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed))
    } catch {
      // The navigation still works when storage is unavailable.
    }
  }, [collapsed])

  const openDiagnosisExecution = (runId: string, returnTo: 'Runs' | 'Diagnosis') => {
    setDiagnosisStudioRunId(runId)
    setExecutionContext({ runId, returnTo })
    setActiveItem('Diagnosis Studio')
  }

  const closeDiagnosisExecution = () => {
    const returnTo = executionContext?.returnTo ?? 'Diagnosis'
    setExecutionContext(null)
    setActiveItem(returnTo)
  }

  const viewDiagnosisResult = (agentRunId: string) => {
    setDiagnosisAgentRunId(agentRunId)
    setExecutionContext(null)
    setActiveItem('Diagnosis')
  }

  const viewRunReport = (runId: number) => {
    setExecutionContext(null)
    setRunsTargetId(runId)
    setActiveItem('Runs')
  }

  const viewTrace = (traceId: string) => {
    setExecutionContext(null)
    setTracesTargetId(traceId)
    setActiveItem('Traces')
  }

  const handleNavigation = (item: string) => {
    setExecutionContext(null)
    if (item !== 'API Studio') setApiStudioTarget(null)
    if (item !== 'Runs') setRunsTargetId(null)
    if (item !== 'Traces') setTracesTargetId(null)
    setActiveItem(item)
  }

  const handleContextNavigation = (target: ContextTrailTarget) => {
    setExecutionContext(null)
    if (target.type === 'endpoint' || target.type === 'testcase') {
      setRunsTargetId(null)
      setTracesTargetId(null)
      setApiStudioTarget(target)
      setActiveItem('API Studio')
      return
    }

    if (target.type === 'run') {
      setApiStudioTarget(null)
      setRunsTargetId(target.runId)
      setTracesTargetId(null)
      setActiveItem('Runs')
      return
    }

    setTracesTargetId(null)
    setDiagnosisAgentRunId(target.agentRunId)
    setActiveItem('Diagnosis')
  }

  const pageContent = executionContext ? (
    <DiagnosisAgentExecutionPage
      initialRunId={executionContext.runId}
      onClose={closeDiagnosisExecution}
      onViewRunReport={viewRunReport}
      onViewResult={viewDiagnosisResult}
      returnTo={executionContext.returnTo}
    />
  ) : activeItem === 'Overview' ? (
    <OverviewPage onNavigate={handleNavigation} />
  ) : activeItem === 'API Studio' ? (
    <ApiStudioPage contextTarget={apiStudioTarget} onContextNavigate={handleContextNavigation} />
  ) : activeItem === 'Runs' ? (
    <RunsPage
      initialRunId={runsTargetId}
      onContextNavigate={handleContextNavigation}
      onDiagnose={(runId) => openDiagnosisExecution(runId, 'Runs')}
    />
  ) : activeItem === 'Diagnosis Studio' ? (
    <DiagnosisAgentExecutionPage
      initialRunId={diagnosisStudioRunId}
      onViewRunReport={viewRunReport}
      onViewResult={viewDiagnosisResult}
    />
  ) : activeItem === 'Diagnosis' ? (
    <DiagnosisPage
      initialAgentRunId={diagnosisAgentRunId}
      onContextNavigate={handleContextNavigation}
      onOpenDiagnosisStudio={(runId) => openDiagnosisExecution(String(runId), 'Diagnosis')}
      onOpenSourceRun={viewRunReport}
      onViewTrace={viewTrace}
    />
  ) : activeItem === 'Traces' ? (
    <TracesPage initialTraceId={tracesTargetId} onContextNavigate={handleContextNavigation} />
  ) : activeItem === 'Evaluation' ? (
    <EvaluationPage />
  ) : activeItem === 'Settings' ? (
    <SettingsPage
      autoDiagnose={autoDiagnose}
      compactDensity={compactDensity}
      onAutoDiagnoseChange={onAutoDiagnoseChange}
      onCompactDensityChange={onCompactDensityChange}
      onReducedMotionChange={onReducedMotionChange}
      onThemePreferenceChange={onThemePreferenceChange}
      reducedMotion={reducedMotion}
      themePreference={themePreference}
    />
  ) : (
    <PlaceholderPage title={activeItem} />
  )

  const guardedPageContent = projectsLoading ? (
    <PageState
      description={t('project.loadingProjectsDescription')}
      kind="loading"
      title={t('project.loadingProjects')}
    />
  ) : projectError ? (
    <PageState
      actionLabel={t('common.retry')}
      description={t('project.failedToLoadDescription')}
      kind="error"
      onAction={() => { void refreshProjects() }}
      title={t('project.failedToLoad')}
    />
  ) : !currentProject ? (
    <PageState
      description={t('project.noAccessibleProjectsDescription')}
      kind="empty"
      title={t('project.noAccessibleProjects')}
    />
  ) : pageContent

  const isApiStudio = activeItem === 'API Studio'
  const isRuns = activeItem === 'Runs'
  const isDiagnosis = activeItem === 'Diagnosis'

  return (
    <div className={`app-shell${collapsed ? ' sidebar-collapsed' : ''}${isApiStudio ? ' api-studio-active' : ''}${isRuns ? ' runs-active' : ''}${isDiagnosis ? ' diagnosis-active' : ''}`}>
      <Topbar theme={theme} onThemeChange={(nextTheme) => onThemePreferenceChange(nextTheme)} />
      <Sidebar
        activeItem={activeItem}
        collapsed={collapsed}
        onCollapse={() => setCollapsed((current) => !current)}
        onSelect={handleNavigation}
      />
      <div className="shell-main">
        <main className={`main-content${isApiStudio ? ' main-content-api-studio' : ''}${isRuns ? ' main-content-runs' : ''}${isDiagnosis ? ' main-content-diagnosis' : ''}`}>
          {guardedPageContent}
        </main>
      </div>
    </div>
  )
}
