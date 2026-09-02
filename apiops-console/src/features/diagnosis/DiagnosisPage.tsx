import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ContextReadModelGap, type ContextTrailEndpoint, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { PageState } from '../../components/common/PageState'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { agentApiFetch, apiFetch, ApiError } from '../../lib/api-client'
import type { RuntimeRunSummary } from '../evaluation/types'
import { DiagnosisHistory } from './components/DiagnosisHistory'
import { DiagnosisReport } from './components/DiagnosisReport'
import { EvidenceInspector } from './components/EvidenceInspector'
import { resolveEndpointIdentityForRun } from '../../app/contextTrailModel'
import type { DiagnosisExecutionResponse, DiagnosisHistoryFilter } from './types'
import type { RunSummary } from '../runs/types'

type DiagnosisPageProps = {
  initialAgentRunId?: string | null
  onOpenSourceRun?: (runId: number) => void
  onOpenDiagnosisStudio?: (runId: number) => void
  onViewTrace?: (traceId: string) => void
  onContextNavigate?: (target: ContextTrailTarget) => void
}

type LoadState = 'idle' | 'loading' | 'ready' | 'error'

const HISTORY_PAGE_SIZE = 6

type RunSummaryResponse = Omit<RunSummary, 'runId' | 'durationMs'> & {
  runId: number | string
  durationMs: number | string | null
}

type ApiMetadataSummaryResponse = {
  apiId: string | number
  apiDocId: string | number
  operationId: string
  method: string
  path: string
  summary: string | null
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function asApiError(error: unknown, fallbackMessage: string, fallbackCode: string) {
  return error instanceof ApiError ? error : new ApiError(fallbackMessage, 0, fallbackCode)
}

function hasSummary(summaryByAgentRunId: Readonly<Record<string, string | null>>, agentRunId: string) {
  return Object.prototype.hasOwnProperty.call(summaryByAgentRunId, agentRunId)
}

function latestRuntimeTimestamp(run: Pick<RuntimeRunSummary, 'startedAt' | 'finishedAt'>) {
  const startedAt = Date.parse(run.startedAt)
  const finishedAt = run.finishedAt ? Date.parse(run.finishedAt) : Number.NaN
  return Math.max(Number.isFinite(startedAt) ? startedAt : 0, Number.isFinite(finishedAt) ? finishedAt : 0)
}

function historySearchText(run: RuntimeRunSummary) {
  return [
    run.agentRunId,
    run.traceId,
    run.executionType,
    run.status,
    run.provider,
    run.model,
    run.projectId,
    run.apiId,
    run.runId,
    run.reportId,
  ].filter((value) => value !== null && value !== undefined).join(' ').toLowerCase()
}

function normalizeRunSummary(run: RunSummaryResponse): RunSummary {
  return {
    ...run,
    runId: Number(run.runId),
    durationMs: run.durationMs === null ? null : Number(run.durationMs),
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

function DiagnosisResultUnavailable({ agentRunId }: { agentRunId?: string | null }) {
  const { ui } = useConsoleLanguage()
  return (
    <article className="diagnosis-empty-result diagnosis-report panel">
      <div>
        <span className="diagnosis-eyebrow">{ui('Diagnosis Result')}</span>
        <h2>{agentRunId ? ui('DiagnosisReport is not available for this execution.') : ui('Select a diagnosis execution from History.')}</h2>
        <p>{agentRunId ? `${ui('Agent run')} ${agentRunId}` : ui('Choose a diagnosis execution to inspect its real result.')}</p>
      </div>
    </article>
  )
}

export function DiagnosisPage({
  initialAgentRunId = null,
  onContextNavigate,
  onOpenDiagnosisStudio,
  onOpenSourceRun,
  onViewTrace,
}: DiagnosisPageProps) {
  const { t, ui } = useConsoleLanguage()
  const { expireSession } = useAuth()
  const {
    activateContext,
    recordContextReadModelGap,
    recordDiagnosis,
    recordEndpoint,
    recordObservedTestCase,
    recordReport,
    recordRun,
  } = useContextTrail()
  const { currentProject, refreshProjects } = useProject()
  const projectId = currentProject?.projectId ?? null

  const [history, setHistory] = useState<RuntimeRunSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<ApiError | null>(null)
  const [historyAttempt, setHistoryAttempt] = useState(0)
  const [selectedAgentRunId, setSelectedAgentRunId] = useState<string | null>(initialAgentRunId)
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyFilter, setHistoryFilter] = useState<DiagnosisHistoryFilter>('ALL')
  const [historyPage, setHistoryPage] = useState(1)
  const [summaryByAgentRunId, setSummaryByAgentRunId] = useState<Record<string, string | null>>({})
  const [summaryLoadingIds, setSummaryLoadingIds] = useState<Set<string>>(new Set())
  const [execution, setExecution] = useState<DiagnosisExecutionResponse | null>(null)
  const [detailState, setDetailState] = useState<LoadState>(initialAgentRunId ? 'loading' : 'idle')
  const [detailError, setDetailError] = useState<ApiError | null>(null)
  const [detailAttempt, setDetailAttempt] = useState(0)

  const hydrateExecutionContext = useCallback(async (
    nextExecution: DiagnosisExecutionResponse,
    signal: AbortSignal,
  ): Promise<ContextReadModelGap | null> => {
    const [runsResult, endpointsResult] = await Promise.allSettled([
      apiFetch<RunSummaryResponse[]>(`/api/v1/projects/${encodeURIComponent(String(projectId))}/test-runs`, { signal }),
      apiFetch<ApiMetadataSummaryResponse[]>(`/api/v1/projects/${encodeURIComponent(String(projectId))}/openapi/apis`, { signal }),
    ])
    if (runsResult.status === 'rejected' && !(runsResult.reason instanceof DOMException && runsResult.reason.name === 'AbortError')) {
      const error = runsResult.reason
      if (error instanceof ApiError && error.status === 401) expireSession()
      if (error instanceof ApiError && error.status === 403) void refreshProjects()
    }
    if (endpointsResult.status === 'rejected' && !(endpointsResult.reason instanceof DOMException && endpointsResult.reason.name === 'AbortError')) {
      const error = endpointsResult.reason
      if (error instanceof ApiError && error.status === 401) expireSession()
      if (error instanceof ApiError && error.status === 403) void refreshProjects()
    }

    const javaRuns = runsResult.status === 'fulfilled' ? runsResult.value.map(normalizeRunSummary) : []
    const javaEndpoints = endpointsResult.status === 'fulfilled'
      ? endpointsResult.value.map(normalizeEndpointMetadata)
      : []
    javaRuns.forEach((run) => {
      recordRun({
        apiId: run.apiId,
        caseId: run.caseId,
        createdAt: run.createdAt,
        name: run.testCaseName,
        runId: run.runId,
        status: run.status,
      })
    })
    javaEndpoints.forEach(recordEndpoint)

    const owningRun = javaRuns.find((run) => run.runId === nextExecution.runId) ?? null
    const endpointResolution = owningRun
      ? resolveEndpointIdentityForRun(owningRun.apiId, javaEndpoints)
      : null
    const endpoint = endpointResolution?.endpoint ?? null
    if (owningRun && endpoint) {
      recordObservedTestCase({
        apiDocId: endpoint.apiDocId,
        apiId: endpoint.id,
        id: owningRun.caseId,
        name: owningRun.testCaseName,
        runId: owningRun.runId,
      })
    } else if (owningRun) {
      recordObservedTestCase({
        apiDocId: '',
        apiId: owningRun.apiId,
        id: owningRun.caseId,
        name: owningRun.testCaseName,
        runId: owningRun.runId,
      })
    }

    const missing = !owningRun
      ? ['run', 'endpoint', 'testcase'] as const
      : endpoint
        ? []
        : ['endpoint'] as const
    if (!missing.length) return null

    return {
      agentRunId: nextExecution.agentRunId,
      missing: [...missing],
      reason: !owningRun
        ? `Java test-runs did not return owning run ${nextExecution.runId}; no ancestor was inferred.`
        : endpointResolution?.resolution === 'AMBIGUOUS_OPERATION_ID'
          ? 'Multiple endpoints share this operationId.'
          : 'Endpoint identity is unavailable.',
      reportId: nextExecution.report?.reportId ?? null,
      runId: nextExecution.runId,
      targetType: nextExecution.report ? 'report' : 'diagnosis',
    }
  }, [expireSession, projectId, recordEndpoint, recordObservedTestCase, recordRun, refreshProjects])

  const rememberExecution = useCallback((nextExecution: DiagnosisExecutionResponse) => {
    recordDiagnosis({
      agentRunId: nextExecution.agentRunId,
      id: nextExecution.agentRunId,
      reportId: nextExecution.report?.reportId ?? null,
      runId: nextExecution.runId,
      status: nextExecution.status,
    })

    if (nextExecution.report) {
      recordReport({
        agentRunId: nextExecution.agentRunId,
        id: nextExecution.report.reportId,
        reportId: nextExecution.report.reportId,
        runId: nextExecution.runId,
      })
      activateContext({
        agentRunId: nextExecution.agentRunId,
        id: nextExecution.report.reportId,
        reportId: nextExecution.report.reportId,
        runId: nextExecution.runId,
        type: 'report',
      })
      return
    }

    activateContext({
      agentRunId: nextExecution.agentRunId,
      id: nextExecution.agentRunId,
      runId: nextExecution.runId,
      type: 'diagnosis',
    })
  }, [activateContext, recordDiagnosis, recordReport])

  useEffect(() => {
    if (initialAgentRunId) setSelectedAgentRunId(initialAgentRunId)
  }, [initialAgentRunId])

  useEffect(() => {
    let cancelled = false
    setHistory([])
    setHistoryError(null)
    setHistoryLoading(true)
    setHistoryPage(1)
    setSummaryByAgentRunId({})
    setSummaryLoadingIds(new Set())

    if (!projectId) {
      setHistoryLoading(false)
      return () => { cancelled = true }
    }

    const controller = new AbortController()
    void agentApiFetch<RuntimeRunSummary[]>(
      `/api/v1/evaluation/runtime/runs?projectId=${encodeURIComponent(projectId)}`,
      { signal: controller.signal },
    )
      .then((response) => {
        if (cancelled) return
        const diagnosisRuns = response
          .filter((run) => run.executionType === 'DIAGNOSIS')
          .sort((left, right) => {
            const timestampDifference = latestRuntimeTimestamp(right) - latestRuntimeTimestamp(left)
            return timestampDifference || right.agentRunId.localeCompare(left.agentRunId)
          })
        setHistory(diagnosisRuns)
        setSelectedAgentRunId((currentId) => {
          if (initialAgentRunId) return initialAgentRunId
          return currentId && diagnosisRuns.some((run) => run.agentRunId === currentId)
            ? currentId
            : diagnosisRuns[0]?.agentRunId ?? null
        })
        setHistoryLoading(false)
      })
      .catch((requestError: unknown) => {
        if (cancelled || isAbortError(requestError)) return
        const apiError = asApiError(requestError, 'Unable to load diagnosis history.', 'DIAGNOSIS_HISTORY_LOAD_FAILED')
        setHistory([])
        setHistoryError(apiError)
        setHistoryLoading(false)
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, historyAttempt, initialAgentRunId, projectId, refreshProjects])

  const filteredHistory = useMemo(() => {
    const normalizedQuery = historyQuery.trim().toLowerCase()
    return history.filter((run) => {
      const matchesFilter = historyFilter === 'ALL' || run.status === historyFilter
      return matchesFilter && (!normalizedQuery || historySearchText(run).includes(normalizedQuery))
    })
  }, [history, historyFilter, historyQuery])

  const pageCount = Math.max(1, Math.ceil(filteredHistory.length / HISTORY_PAGE_SIZE))
  const visibleHistory = useMemo(
    () => filteredHistory.slice((historyPage - 1) * HISTORY_PAGE_SIZE, historyPage * HISTORY_PAGE_SIZE),
    [filteredHistory, historyPage],
  )

  useEffect(() => {
    setHistoryPage((currentPage) => Math.min(currentPage, pageCount))
  }, [pageCount])

  useEffect(() => {
    if (historyLoading || historyError) return
    if (!filteredHistory.length) {
      setSelectedAgentRunId(null)
      return
    }
    setSelectedAgentRunId((currentId) => filteredHistory.some((run) => run.agentRunId === currentId)
      ? currentId
      : filteredHistory[0].agentRunId)
  }, [filteredHistory, historyError, historyLoading])

  useEffect(() => {
    const candidates = visibleHistory.filter((run) => (
      run.status === 'COMPLETED'
      && run.agentRunId !== selectedAgentRunId
      && !hasSummary(summaryByAgentRunId, run.agentRunId)
      && !summaryLoadingIds.has(run.agentRunId)
    ))
    if (!candidates.length) return

    let cancelled = false
    const controller = new AbortController()
    const candidateIds = candidates.map((run) => run.agentRunId)
    setSummaryLoadingIds((currentIds) => new Set([...currentIds, ...candidateIds]))

    void Promise.allSettled(candidates.map((run) => agentApiFetch<DiagnosisExecutionResponse>(
      `/api/v1/diagnosis/runs/${encodeURIComponent(run.agentRunId)}`,
      { signal: controller.signal },
    ))).then((results) => {
      if (cancelled) return
      const summaries: Record<string, string | null> = {}
      results.forEach((result, index) => {
        const agentRunId = candidateIds[index]
        if (result.status === 'fulfilled') {
          summaries[agentRunId] = result.value.report?.summary?.trim() || null
          return
        }
        const requestError = result.reason
        if (requestError instanceof ApiError && requestError.status === 401) expireSession()
        if (requestError instanceof ApiError && requestError.status === 403) void refreshProjects()
        summaries[agentRunId] = null
      })
      setSummaryByAgentRunId((currentSummaries) => ({ ...currentSummaries, ...summaries }))
      setSummaryLoadingIds((currentIds) => {
        const nextIds = new Set(currentIds)
        candidateIds.forEach((agentRunId) => nextIds.delete(agentRunId))
        return nextIds
      })
    })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, refreshProjects, selectedAgentRunId, summaryByAgentRunId, summaryLoadingIds, visibleHistory])

  useEffect(() => {
    let cancelled = false
    setExecution(null)
    setDetailError(null)

    if (!projectId || !selectedAgentRunId) {
      setDetailState('idle')
      return () => { cancelled = true }
    }

    const controller = new AbortController()
    setDetailState('loading')
    void agentApiFetch<DiagnosisExecutionResponse>(
      `/api/v1/diagnosis/runs/${encodeURIComponent(selectedAgentRunId)}`,
      { signal: controller.signal },
    )
      .then(async (nextExecution) => {
        if (cancelled) return
        const contextGap = await hydrateExecutionContext(nextExecution, controller.signal)
        if (cancelled) return
        setExecution(nextExecution)
        setSummaryByAgentRunId((currentSummaries) => ({
          ...currentSummaries,
          [nextExecution.agentRunId]: nextExecution.report?.summary?.trim() || null,
        }))
        rememberExecution(nextExecution)
        if (contextGap) recordContextReadModelGap(contextGap)
        setDetailState('ready')
      })
      .catch((requestError: unknown) => {
        if (cancelled || isAbortError(requestError)) return
        const apiError = asApiError(requestError, 'Unable to load the diagnosis result.', 'DIAGNOSIS_LOAD_FAILED')
        setDetailError(apiError)
        setDetailState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [detailAttempt, expireSession, hydrateExecutionContext, projectId, recordContextReadModelGap, refreshProjects, rememberExecution, selectedAgentRunId])

  const handleContextNavigate = onContextNavigate ?? (() => undefined)
  return (
    <section className="diagnosis-page" aria-label={t('page.diagnosis.title')}>
      <div className="diagnosis-layout">
        <DiagnosisHistory
          accessDeniedDescription={t('auth.accessDeniedDescription')}
          currentPage={historyPage}
          filter={historyFilter}
          historyError={historyError}
          historyLoading={historyLoading}
          onFilterChange={(nextFilter) => {
            setHistoryFilter(nextFilter)
            setHistoryPage(1)
          }}
          onPageChange={(nextPage) => setHistoryPage(Math.max(1, Math.min(nextPage, pageCount)))}
          onQueryChange={(nextQuery) => {
            setHistoryQuery(nextQuery)
            setHistoryPage(1)
          }}
          onRetry={() => setHistoryAttempt((attempt) => attempt + 1)}
          onSelect={setSelectedAgentRunId}
          pageCount={pageCount}
          pageSize={HISTORY_PAGE_SIZE}
          query={historyQuery}
          runs={history}
          selectedAgentRunId={selectedAgentRunId}
          summaryByAgentRunId={summaryByAgentRunId}
          summaryLoadingIds={summaryLoadingIds}
          totalMatches={filteredHistory.length}
          visibleRuns={visibleHistory}
        />

        <div className="diagnosis-report-column">
          {detailState === 'loading' ? (
            <PageState
              description={ui('Reading the real DiagnosisReport from Python AgentLab.')}
              kind="loading"
              title={ui('Loading Diagnosis Result')}
            />
          ) : null}
          {detailState === 'error' ? (
            <PageState
              actionLabel={t('common.retry')}
              description={detailError?.status === 403 ? t('auth.accessDeniedDescription') : detailError?.message ?? ui('The diagnosis result API is unavailable.')}
              kind={detailError?.status === 403 ? 'forbidden' : 'error'}
              onAction={() => setDetailAttempt((attempt) => attempt + 1)}
              title={detailError?.status === 403 ? t('auth.accessDeniedTitle') : ui('Diagnosis Result unavailable')}
            />
          ) : null}
          {detailState === 'idle' ? <DiagnosisResultUnavailable agentRunId={initialAgentRunId} /> : null}
          {detailState === 'ready' && execution ? (
            <DiagnosisReport
              execution={execution}
              onOpenDiagnosisStudio={() => onOpenDiagnosisStudio?.(execution.runId)}
              onOpenSourceRun={() => onOpenSourceRun?.(execution.runId)}
              onViewTrace={() => {
                if (execution.traceId.trim()) onViewTrace?.(execution.traceId)
              }}
            />
          ) : null}
        </div>

        <EvidenceInspector execution={execution} />

        <ContextTrail
          onNavigate={handleContextNavigate}
          visibleGroups={['endpoint', 'testcase', 'run', 'diagnosis', 'report']}
        />
      </div>
    </section>
  )
}
