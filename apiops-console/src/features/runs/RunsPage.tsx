import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ActiveContext, type ContextTrailEndpoint, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { ApiError, apiFetch, streamSse } from '../../lib/api-client'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { PageState } from '../../components/common/PageState'
import { resolveEndpointIdentityForRun } from '../../app/contextTrailModel'
import { RunDetail } from './components/RunDetail'
import { RunsExplorer } from './components/RunsExplorer'
import type { RunFilter, RunLiveState, RunProgress, RunSummary, RunTab, TestReport } from './types'

type RunsPageProps = {
  initialRunId?: number | null
  onContextNavigate?: (target: ContextTrailTarget) => void
  onDiagnose?: (runId: string) => void
}

type RunsLoadState = 'loading' | 'ready' | 'error'
type ReportLoadState = 'idle' | 'loading' | 'ready' | 'unavailable' | 'error'

type RunSummaryResponse = Omit<RunSummary, 'runId' | 'durationMs'> & {
  runId: number
  durationMs: number | null
}

type ApiMetadataSummaryResponse = {
  apiId: string | number
  apiDocId: string | number
  operationId: string
  method: string
  path: string
  summary: string | null
}

type ProgressResponse = RunProgress

function normalizeRunSummary(summary: RunSummaryResponse): RunSummary {
  return {
    ...summary,
    runId: Number(summary.runId),
    durationMs: summary.durationMs === null ? null : Number(summary.durationMs),
  }
}

function normalizeEndpointMetadata(summary: ApiMetadataSummaryResponse): ContextTrailEndpoint {
  return {
    apiDocId: String(summary.apiDocId),
    id: String(summary.apiId),
    method: summary.method.trim().toUpperCase(),
    operationId: summary.operationId,
    path: summary.path,
    summary: summary.summary,
  }
}

function normalizeProgress(progress: ProgressResponse): RunProgress {
  return {
    assertionFailed: progress.assertionFailed,
    cancelled: progress.cancelled,
    completed: progress.completed,
    executionFailed: progress.executionFailed,
    runId: Number(progress.runId),
    running: progress.running,
    status: progress.status,
    success: progress.success,
    timeout: progress.timeout,
    total: progress.total,
    updatedAt: progress.updatedAt,
  }
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function apiErrorFor(error: unknown, fallback: string) {
  return error instanceof ApiError ? error : new ApiError(fallback, 0, 'NETWORK_ERROR')
}

function selectRunForContext(
  nextRuns: RunSummary[],
  initialRunId: number | null,
  context: ActiveContext | null,
) {
  if (initialRunId !== null) {
    return nextRuns.find((run) => run.runId === initialRunId) ?? null
  }

  if (context?.runId !== null && context?.runId !== undefined) {
    const sourceApiId = context.endpointResolution?.sourceValue ?? context.endpointId
    return nextRuns.find((run) => (
      run.runId === context.runId
      && (!context.caseId || run.caseId === context.caseId)
      && (!sourceApiId || run.apiId === sourceApiId)
    )) ?? null
  }

  if (context?.caseId || context?.endpointId) return null
  return nextRuns[0] ?? null
}

export function RunsPage({ initialRunId = null, onContextNavigate, onDiagnose }: RunsPageProps) {
  const { expireSession } = useAuth()
  const { t } = useConsoleLanguage()
  const {
    activateContext,
    activeContext,
    endpoints,
    recordContextReadModelGap,
    recordEndpoint,
    recordObservedTestCase,
    recordRun,
  } = useContextTrail()
  const { currentProject, refreshProjects } = useProject()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsState, setRunsState] = useState<RunsLoadState>('loading')
  const [runsError, setRunsError] = useState<ApiError | null>(null)
  const [endpointMetadata, setEndpointMetadata] = useState<ContextTrailEndpoint[]>([])
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<RunFilter>('ALL')
  const [activeTab, setActiveTab] = useState<RunTab>('Summary')
  const [report, setReport] = useState<TestReport | null>(null)
  const [reportState, setReportState] = useState<ReportLoadState>('idle')
  const [reportAttempt, setReportAttempt] = useState(0)
  const [progress, setProgress] = useState<RunProgress | null>(null)
  const [liveState, setLiveState] = useState<RunLiveState>('idle')
  const activeContextRef = useRef<ActiveContext | null>(activeContext)

  useEffect(() => {
    activeContextRef.current = activeContext
  }, [activeContext])

  const projectId = currentProject?.projectId ?? null
  const selectedRun = useMemo(
    () => runs.find((run) => run.runId === selectedRunId) ?? null,
    [runs, selectedRunId],
  )

  const fetchRuns = useCallback(async (nextProjectId: string, signal?: AbortSignal) => {
    const response = await apiFetch<RunSummaryResponse[]>(`/api/v1/projects/${encodeURIComponent(nextProjectId)}/test-runs`, { signal })
    return response.map(normalizeRunSummary)
  }, [])

  const fetchEndpointMetadata = useCallback(async (nextProjectId: string, signal: AbortSignal) => {
    const response = await apiFetch<ApiMetadataSummaryResponse[]>(
      `/api/v1/projects/${encodeURIComponent(nextProjectId)}/openapi/apis`,
      { signal },
    )
    return response.map(normalizeEndpointMetadata)
  }, [])

  const rememberRuns = useCallback((nextRuns: RunSummary[]) => {
    nextRuns.forEach((run) => {
      recordRun({
        apiId: run.apiId,
        caseId: run.caseId,
        createdAt: run.createdAt,
        name: run.testCaseName,
        runId: run.runId,
        status: run.status,
      })
    })
  }, [recordRun])

  const rememberEndpoints = useCallback((nextEndpoints: ContextTrailEndpoint[]) => {
    nextEndpoints.forEach(recordEndpoint)
  }, [recordEndpoint])

  const hydrateRunContext = useCallback((run: RunSummary) => {
    const endpointResolution = resolveEndpointIdentityForRun(run.apiId, [...endpointMetadata, ...endpoints])
    const endpoint = endpointResolution.endpoint
    if (endpoint) {
      recordEndpoint(endpoint)
    }
    recordObservedTestCase({
      apiDocId: endpoint?.apiDocId ?? '',
      apiId: endpoint?.id ?? run.apiId,
      id: run.caseId,
      name: run.testCaseName,
      runId: run.runId,
    })
    activateContext({
      type: 'run',
      id: String(run.runId),
      runId: run.runId,
      caseId: run.caseId,
      apiId: run.apiId,
    })
    if (!endpoint) {
      recordContextReadModelGap({
        agentRunId: null,
        missing: ['endpoint'],
        reason: endpointResolution.resolution === 'AMBIGUOUS_OPERATION_ID'
          ? 'Multiple endpoints share this operationId.'
          : 'Endpoint identity is unavailable.',
        reportId: null,
        runId: run.runId,
        targetType: 'run',
      })
    }
  }, [activateContext, endpointMetadata, endpoints, recordContextReadModelGap, recordEndpoint, recordObservedTestCase])

  useEffect(() => {
    let cancelled = false
    setRuns([])
    setSelectedRunId(null)
    setReport(null)
    setReportState('idle')
    setProgress(null)
    setLiveState('idle')

    if (!projectId) {
      setRunsState('ready')
      return () => { cancelled = true }
    }

    setRunsState('loading')
    setRunsError(null)
    const controller = new AbortController()
    void fetchRuns(projectId, controller.signal)
      .then((nextRuns) => {
        if (cancelled) return
        rememberRuns(nextRuns)
        setRuns(nextRuns)
        const nextSelectedRun = selectRunForContext(nextRuns, initialRunId, activeContextRef.current)
        setSelectedRunId(nextSelectedRun?.runId ?? null)
        const contextAtLoad = activeContextRef.current
        if (!nextSelectedRun && initialRunId !== null) {
          recordContextReadModelGap({
            agentRunId: contextAtLoad?.agentRunId ?? null,
            missing: ['run', 'endpoint', 'testcase'],
            reason: `Java test-runs did not return the requested run ${initialRunId}; no ancestor was inferred.`,
            reportId: contextAtLoad?.reportId ?? null,
            runId: initialRunId,
            targetType: 'run',
          })
        } else if (!nextSelectedRun && contextAtLoad?.runId !== null && contextAtLoad?.runId !== undefined) {
          recordContextReadModelGap({
            agentRunId: contextAtLoad.agentRunId,
            missing: ['run', 'endpoint', 'testcase'],
            reason: `Java test-runs did not return owning run ${contextAtLoad.runId}; no ancestor was inferred.`,
            reportId: contextAtLoad.reportId,
            runId: contextAtLoad.runId,
            targetType: 'run',
          })
        }
        setRunsState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = apiErrorFor(error, 'Unable to load runs')
        setRuns([])
        setSelectedRunId(null)
        setRunsError(apiError)
        setRunsState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, fetchRuns, initialRunId, projectId, recordContextReadModelGap, refreshProjects, rememberRuns])

  useEffect(() => {
    let cancelled = false
    setEndpointMetadata([])

    if (!projectId) return () => { cancelled = true }

    const controller = new AbortController()
    void fetchEndpointMetadata(projectId, controller.signal)
      .then((nextEndpoints) => {
        if (cancelled) return
        rememberEndpoints(nextEndpoints)
        setEndpointMetadata(nextEndpoints)
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = apiErrorFor(error, 'Unable to load endpoint metadata')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, fetchEndpointMetadata, projectId, refreshProjects, rememberEndpoints])

  useEffect(() => {
    if (selectedRun) hydrateRunContext(selectedRun)
  }, [hydrateRunContext, selectedRun])

  useEffect(() => {
    let cancelled = false
    setReport(null)
    setReportState('idle')

    if (!projectId || !selectedRun) return () => { cancelled = true }

    setReportState('loading')
    const controller = new AbortController()
    void apiFetch<TestReport>(`/api/v1/projects/${encodeURIComponent(projectId)}/test-runs/${selectedRun.runId}/report`, { signal: controller.signal })
      .then((nextReport) => {
        if (cancelled) return
        setReport(nextReport)
        setReportState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = apiErrorFor(error, 'Unable to load TestReport')
        setReport(null)
        setReportState(apiError.status === 404 ? 'unavailable' : 'error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, projectId, refreshProjects, reportAttempt, selectedRun?.runId, selectedRun?.status])

  useEffect(() => {
    if (!projectId || !selectedRun || selectedRun.status !== 'RUNNING') {
      setProgress(null)
      setLiveState('idle')
      return
    }

    let cancelled = false
    const controller = new AbortController()
    setProgress(null)
    setLiveState('connecting')
    void streamSse<ProgressResponse>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/test-runs/${selectedRun.runId}/progress/events`,
      (event) => {
        if (cancelled) return
        setProgress(normalizeProgress(event.data))
        setLiveState('live')
        if (event.event === 'terminal') {
          setLiveState('idle')
          void fetchRuns(projectId)
            .then((nextRuns) => {
              if (cancelled) return
              rememberRuns(nextRuns)
              setRuns(nextRuns)
              setSelectedRunId((currentId) => nextRuns.some((run) => run.runId === currentId)
                ? currentId
                : selectRunForContext(nextRuns, initialRunId, activeContextRef.current)?.runId ?? null)
            })
            .catch((error: unknown) => {
              if (cancelled || isAbortError(error)) return
              const apiError = apiErrorFor(error, 'Unable to refresh runs')
              setRunsError(apiError)
              setRunsState('error')
              if (apiError.status === 401) expireSession()
              if (apiError.status === 403) void refreshProjects()
            })
        }
      },
      controller.signal,
    ).catch((error: unknown) => {
      if (cancelled || isAbortError(error)) return
      const apiError = apiErrorFor(error, 'Live progress disconnected')
      setLiveState('disconnected')
      if (apiError.status === 401) expireSession()
      if (apiError.status === 403) void refreshProjects()
    })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, fetchRuns, initialRunId, projectId, refreshProjects, rememberRuns, selectedRun?.runId, selectedRun?.status])

  const normalizedQuery = query.trim().toLowerCase()
  const visibleRuns = useMemo(() => runs.filter((run) => {
    const searchable = `${run.runId} ${run.caseId} ${run.apiId} ${run.testCaseName} ${run.status}`.toLowerCase()
    const matchesQuery = !normalizedQuery || searchable.includes(normalizedQuery)
    const matchesFilter = filter === 'ALL'
      || (filter === 'SUCCESS' && run.status === 'SUCCESS')
      || (filter === 'RUNNING' && run.status === 'RUNNING')
      || (filter === 'PENDING' && run.status === 'PENDING')
      || (filter === 'CANCELLED' && run.status === 'CANCELLED')
      || (filter === 'FAILED' && ['ASSERTION_FAILED', 'EXECUTION_FAILED', 'TIMEOUT'].includes(run.status))
    return matchesQuery && matchesFilter
  }), [filter, normalizedQuery, runs])

  const retryRuns = () => {
    setRunsState('loading')
    setRunsError(null)
    if (projectId) {
      void fetchRuns(projectId)
        .then((nextRuns) => {
          rememberRuns(nextRuns)
          setRuns(nextRuns)
          const nextSelectedRun = selectRunForContext(nextRuns, initialRunId, activeContextRef.current)
          setSelectedRunId(nextSelectedRun?.runId ?? null)
          setRunsState('ready')
        })
        .catch((error: unknown) => {
          const apiError = apiErrorFor(error, 'Unable to load runs')
          setRunsError(apiError)
          setRunsState('error')
          if (apiError.status === 401) expireSession()
          if (apiError.status === 403) void refreshProjects()
        })
    }
  }

  const handleContextNavigate = (target: ContextTrailTarget) => {
    if (target.type === 'run') {
      if (runs.some((run) => run.runId === target.runId)) {
        setSelectedRunId(target.runId)
        setActiveTab('Summary')
      }
      return
    }

    onContextNavigate?.(target)
  }

  return (
    <section className="runs-page" aria-label={t('page.runs.title')}>
      <div className="runs-workspace-heading">
        <h1>{t('page.runs.title')}</h1>
      </div>
      {runsState === 'loading' ? (
        <PageState description={t('runs.loadingDescription')} kind="loading" title={t('runs.loading')} />
      ) : runsState === 'error' ? (
        <PageState actionLabel={t('runs.retry')} description={runsError?.status === 403 ? t('auth.accessDeniedDescription') : t('runs.failedToLoadDescription')} kind="error" onAction={retryRuns} title={t('runs.failedToLoad')} />
      ) : (
        <div className="runs-layout">
          <RunsExplorer
            allRuns={runs}
            filter={filter}
            onDiagnose={onDiagnose}
            onFilterChange={setFilter}
            onQueryChange={setQuery}
            onSelect={(runId) => {
              setSelectedRunId(runId)
              setActiveTab('Summary')
            }}
            query={query}
            runs={visibleRuns}
            selectedRunId={selectedRunId}
            totalRuns={runs.length}
          />
          <RunDetail
            activeTab={activeTab}
            onDiagnose={onDiagnose}
            onRetryReport={() => setReportAttempt((attempt) => attempt + 1)}
            onTabChange={setActiveTab}
            report={report}
            reportStatus={reportState}
            liveState={liveState}
            progress={progress}
            run={selectedRun}
          />
          <ContextTrail onNavigate={handleContextNavigate} visibleGroups={['endpoint', 'testcase', 'run']} />
        </div>
      )}
    </section>
  )
}
