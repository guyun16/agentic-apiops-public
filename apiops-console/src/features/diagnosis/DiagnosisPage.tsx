import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ContextReadModelGap, type ContextTrailEndpoint, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { PageState } from '../../components/common/PageState'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { agentApiFetch, apiFetch, ApiError } from '../../lib/api-client'
import { DiagnosisHistory } from './components/DiagnosisHistory'
import { DiagnosisReport } from './components/DiagnosisReport'
import { EvidenceInspector } from './components/EvidenceInspector'
import { resolveEndpointIdentityForRun } from '../../app/contextTrailModel'
import {
  diagnosisHistoryPath,
  filterDiagnosisHistory,
  resolveDiagnosisSelection,
  sortDiagnosisHistory,
} from './diagnosisHistoryModel'
import type { DiagnosisExecutionResponse, DiagnosisHistoryFilter, DiagnosisRunSummary } from './types'
import { fetchExactRun } from '../runs/run-api'

type DiagnosisPageProps = {
  onSelected?: (agentRunId: string) => void
  initialAgentRunId?: string | null
  onOpenSourceRun?: (runId: number) => void
  onOpenDiagnosisStudio?: (runId: number) => void
  onViewTrace?: (traceId: string) => void
  onContextNavigate?: (target: ContextTrailTarget) => void
}

type LoadState = 'idle' | 'loading' | 'ready' | 'error'

const HISTORY_PAGE_SIZE = 6

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
  onSelected,
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

  const [history, setHistory] = useState<DiagnosisRunSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<ApiError | null>(null)
  const [historyAttempt, setHistoryAttempt] = useState(0)
  const [selectedAgentRunId, setSelectedAgentRunId] = useState<string | null>(initialAgentRunId)
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyFilter, setHistoryFilter] = useState<DiagnosisHistoryFilter>('ALL')
  const [historyPage, setHistoryPage] = useState(1)
  const [execution, setExecution] = useState<DiagnosisExecutionResponse | null>(null)
  const [detailState, setDetailState] = useState<LoadState>(initialAgentRunId ? 'loading' : 'idle')
  const [detailError, setDetailError] = useState<ApiError | null>(null)
  const [detailAttempt, setDetailAttempt] = useState(0)

  const hydrateExecutionContext = useCallback(async (
    nextExecution: DiagnosisExecutionResponse,
    signal: AbortSignal,
  ): Promise<ContextReadModelGap | null> => {
    const [runResult, endpointsResult] = await Promise.allSettled([
      fetchExactRun(String(projectId), nextExecution.runId, signal),
      apiFetch<ApiMetadataSummaryResponse[]>(`/api/v1/projects/${encodeURIComponent(String(projectId))}/openapi/apis`, { signal }),
    ])
    if (runResult.status === 'rejected' && !(runResult.reason instanceof DOMException && runResult.reason.name === 'AbortError')) {
      const error = runResult.reason
      if (error instanceof ApiError && error.status === 401) expireSession()
      if (error instanceof ApiError && error.status === 403) void refreshProjects()
    }
    if (endpointsResult.status === 'rejected' && !(endpointsResult.reason instanceof DOMException && endpointsResult.reason.name === 'AbortError')) {
      const error = endpointsResult.reason
      if (error instanceof ApiError && error.status === 401) expireSession()
      if (error instanceof ApiError && error.status === 403) void refreshProjects()
    }

    const owningRun = runResult.status === 'fulfilled' ? runResult.value : null
    const javaEndpoints = endpointsResult.status === 'fulfilled'
      ? endpointsResult.value.map(normalizeEndpointMetadata)
      : []
    if (owningRun) {
      const run = owningRun
      recordRun({
        apiId: run.apiId,
        caseId: run.caseId,
        createdAt: run.createdAt,
        name: run.testCaseName,
        runId: run.runId,
        status: run.status,
      })
    }
    javaEndpoints.forEach(recordEndpoint)

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
        ? `Java exact Run query did not return owning run ${nextExecution.runId}; no ancestor was inferred.`
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

    if (!projectId) {
      setHistoryLoading(false)
      return () => { cancelled = true }
    }

    const controller = new AbortController()
    void agentApiFetch<DiagnosisRunSummary[]>(
      diagnosisHistoryPath(projectId),
      { signal: controller.signal },
    )
      .then((response) => {
        if (cancelled) return
        const diagnosisRuns = sortDiagnosisHistory(response)
        setHistory(diagnosisRuns)
        setSelectedAgentRunId((currentId) => {
          return resolveDiagnosisSelection(initialAgentRunId ?? currentId, diagnosisRuns)
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
    return filterDiagnosisHistory(history, historyFilter, historyQuery)
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
    setSelectedAgentRunId((currentId) => resolveDiagnosisSelection(currentId, filteredHistory))
  }, [filteredHistory, historyError, historyLoading])

  useEffect(() => {
    let cancelled = false
    setExecution(null)
    setDetailError(null)

    if (
      !projectId
      || historyLoading
      || historyError
      || !selectedAgentRunId
      || !history.some((run) => run.agentRunId === selectedAgentRunId)
    ) {
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
  }, [detailAttempt, expireSession, history, historyError, historyLoading, hydrateExecutionContext, projectId, recordContextReadModelGap, refreshProjects, rememberExecution, selectedAgentRunId])

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
          onSelect={(id) => { setSelectedAgentRunId(id); onSelected?.(id) }}
          pageCount={pageCount}
          pageSize={HISTORY_PAGE_SIZE}
          query={historyQuery}
          runs={history}
          selectedAgentRunId={selectedAgentRunId}
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
