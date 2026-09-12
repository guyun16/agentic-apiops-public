import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Theme, ThemePreference } from '../../app/App'
import type { ContextTrailTarget } from '../../app/ContextTrailContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'
import { consoleRouteUrl, consoleViewForItem, parseConsoleRoute, type ConsoleView, type RouteDetails } from '../../app/consoleRoute'
import { ApiStudioPage } from '../../features/api-studio/ApiStudioPage'
import { BenchmarkPage } from '../../features/benchmark/BenchmarkPage'
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

function initialConsoleRoute() {
  return parseConsoleRoute(typeof window === 'undefined' ? '' : window.location.search)
}

function getInitialSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function PlaceholderPage({ title }: { title: string }) {
  const { ui } = useConsoleLanguage()
  return (
    <section className="placeholder-page" aria-labelledby="placeholder-title">
      <div className="placeholder-eyebrow">{ui('APIOps workspace')}</div>
      <h1 id="placeholder-title">{title}</h1>
      <p>{ui('This module is reserved for the next console phase.')}</p>
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
  const { currentProject, availableProjects, selectProject, error: projectError, loading: projectsLoading, refreshProjects } = useProject()
  const projectId = currentProject?.projectId ?? null
  const [route, setRoute] = useState(initialConsoleRoute)
  const activeItem = route.activeItem
  const [collapsed, setCollapsed] = useState(getInitialSidebarCollapsed)
  const [executionContext, setExecutionContext] = useState<DiagnosisExecutionContext | null>(null)
  const [contextTarget, setContextTarget] = useState<Extract<ContextTrailTarget, { type: 'endpoint' | 'testcase' }> | null>(null)
  const previousProjectId = useRef<string | null>(null)
  const apiStudioTarget = useMemo(() => contextTarget ?? (route.apiId
    ? { type: 'endpoint' as const, id: route.apiId, apiDocId: route.apiDocId ?? '' } : null),
  [contextTarget, route.apiId, route.apiDocId])

  const commitLocation = useCallback((url: URL, replace = false) => {
    if (url.href === window.location.href) return
    window.history[replace ? 'replaceState' : 'pushState'](null, '', url)
    setRoute(parseConsoleRoute(url.search))
  }, [])

  const navigate = useCallback((view: ConsoleView, runId: number | null = null, details: RouteDetails = {}, replace = false) => {
    commitLocation(consoleRouteUrl(window.location.href, view, runId, projectId, details), replace)
  }, [commitLocation, projectId])

  useEffect(() => {
    const restore = () => {
      let next = parseConsoleRoute(window.location.search)
      if (next.projectId && next.projectId !== projectId) {
        if (availableProjects.some((project) => project.projectId === next.projectId)) {
          previousProjectId.current = next.projectId
          selectProject(next.projectId)
        } else {
          const url = consoleRouteUrl(window.location.href, next.view, null, projectId)
          window.history.replaceState(null, '', url)
          next = parseConsoleRoute(url.search)
        }
      }
      setExecutionContext(null)
      setContextTarget(null)
      setRoute(next)
    }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [availableProjects, projectId, selectProject])

  useEffect(() => {
    if (!projectId) return
    if ((previousProjectId.current && previousProjectId.current !== projectId)
      || (route.projectId && route.projectId !== projectId)) {
      setExecutionContext(null)
      setContextTarget(null)
      navigate(route.view, null, {}, previousProjectId.current === null)
    }
    previousProjectId.current = projectId
  }, [projectId, route.projectId, route.view, navigate])

  useEffect(() => {
    try { window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed)) } catch { /* Navigation works without storage. */ }
  }, [collapsed])

  // Selection already lives in the mounted page. Updating its input props here
  // would reload its list and discard loaded history pages.
  const rememberLocation = useCallback((view: ConsoleView, runId: number | null, details: RouteDetails = {}, replace = true) => {
    const current = parseConsoleRoute(window.location.search)
    if (current.view !== view || (current.projectId && current.projectId !== projectId)) return
    const url = consoleRouteUrl(window.location.href, view, runId, projectId, details)
    if (url.href !== window.location.href) window.history[replace ? 'replaceState' : 'pushState'](null, '', url)
  }, [projectId])
  const rememberRunLocation = useCallback((runId: number, replace = true) => {
    rememberLocation('runs', runId, {}, replace)
  }, [rememberLocation])
  const rememberDiagnosisLocation = useCallback((runId: number) => {
    rememberLocation('diagnosis-studio', runId)
  }, [rememberLocation])
  const rememberEndpointLocation = useCallback((apiId: string, apiDocId: string) => {
    rememberLocation('api-studio', null, { apiId, apiDocId })
  }, [rememberLocation])
  const rememberDiagnosisResult = useCallback((agentRunId: string) => {
    rememberLocation('diagnosis', null, { agentRunId }, false)
  }, [rememberLocation])
  const rememberTrace = useCallback((traceId: string) => {
    rememberLocation('traces', null, { traceId }, false)
  }, [rememberLocation])

  const openDiagnosisExecution = (runId: string, returnTo: 'Runs' | 'Diagnosis') => {
    setExecutionContext({ runId, returnTo })
    navigate('diagnosis-studio', Number(runId))
  }
  const closeDiagnosisExecution = () => {
    const returnTo = executionContext?.returnTo ?? 'Diagnosis'
    setExecutionContext(null)
    navigate(returnTo === 'Runs' ? 'runs' : 'diagnosis')
  }
  const viewDiagnosisResult = (agentRunId: string) => {
    setExecutionContext(null)
    navigate('diagnosis', null, { agentRunId })
  }
  const viewRunReport = (runId: number) => {
    setExecutionContext(null)
    navigate('runs', runId)
  }
  const viewTrace = (traceId: string) => {
    setExecutionContext(null)
    navigate('traces', null, { traceId })
  }
  const handleNavigation = (item: string) => {
    setExecutionContext(null)
    setContextTarget(null)
    navigate(consoleViewForItem(item))
  }
  const handleContextNavigation = (target: ContextTrailTarget) => {
    setExecutionContext(null)
    if (target.type === 'endpoint' || target.type === 'testcase') {
      setContextTarget(target)
      navigate('api-studio', null, { apiId: target.type === 'endpoint' ? target.id : target.apiId, apiDocId: target.apiDocId })
    } else if (target.type === 'run') viewRunReport(target.runId)
    else viewDiagnosisResult(target.agentRunId)
  }
  const pageContent = executionContext ? (
    <DiagnosisAgentExecutionPage
      initialRunId={executionContext.runId}
      onRunSelected={rememberDiagnosisLocation}
      onClose={closeDiagnosisExecution}
      onViewRunReport={viewRunReport}
      onViewResult={viewDiagnosisResult}
      returnTo={executionContext.returnTo}
    />
  ) : activeItem === 'Overview' ? (
    <OverviewPage onNavigate={handleNavigation} />
  ) : activeItem === 'API Studio' ? (
    <ApiStudioPage onEndpointSelected={rememberEndpointLocation} contextTarget={apiStudioTarget} onContextNavigate={handleContextNavigation} onViewRun={viewRunReport} />
  ) : activeItem === 'Runs' ? (
    <RunsPage
      initialRunId={route.runId}
      onContextNavigate={handleContextNavigation}
      onDiagnose={(runId) => openDiagnosisExecution(runId, 'Runs')}
      onRunSelected={rememberRunLocation}
    />
  ) : activeItem === 'Diagnosis Studio' ? (
    <DiagnosisAgentExecutionPage
      initialRunId={route.runId === null ? null : String(route.runId)}
      onRunSelected={rememberDiagnosisLocation}
      onViewRunReport={viewRunReport}
      onViewResult={viewDiagnosisResult}
    />
  ) : activeItem === 'Diagnosis' ? (
    <DiagnosisPage
      initialAgentRunId={route.agentRunId} onSelected={rememberDiagnosisResult}
      onContextNavigate={handleContextNavigation}
      onOpenDiagnosisStudio={(runId) => openDiagnosisExecution(String(runId), 'Diagnosis')}
      onOpenSourceRun={viewRunReport}
      onViewTrace={viewTrace}
    />
  ) : activeItem === 'Traces' ? (
    <TracesPage initialTraceId={route.traceId} onSelected={rememberTrace} onContextNavigate={handleContextNavigation} />
  ) : activeItem === 'Evaluation' ? (
    <EvaluationPage
      onContextNavigate={handleContextNavigation}
      onViewDiagnosis={viewDiagnosisResult}
      onViewRun={viewRunReport}
      onViewTrace={viewTrace}
    />
  ) : activeItem === 'Benchmark' ? (
    <BenchmarkPage />
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

  const guardedPageContent = projectsLoading || Boolean(route.projectId && projectId && route.projectId !== projectId) ? (
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
          <Fragment key={projectId}>{guardedPageContent}</Fragment>
        </main>
      </div>
    </div>
  )
}
