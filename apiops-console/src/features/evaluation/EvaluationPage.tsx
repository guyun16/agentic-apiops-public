import { Activity, Clock3, Database, Gauge, RefreshCw, Scale, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ContextTrailEndpoint, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { PageState } from '../../components/common/PageState'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { PageHeader } from '../../components/layout/PageHeader'
import { agentApiFetch, apiFetch, ApiError } from '../../lib/api-client'
import { fetchExactRun } from '../runs/run-api'
import { EvaluationRuns } from './components/EvaluationRuns'
import { EvaluationSummary } from './components/EvaluationSummary'
import {
  EvaluationCostLatencyTab,
  EvaluationDeterministicTab,
  EvaluationJudgeTab,
  EvaluationOverviewTab,
  EvaluationRuntimeFactsTab,
} from './components/EvaluationTabContent'
import { filterRuntimeRuns, resolveRuntimeEndpoint, resolveSelectedRunId, runtimeContextTarget, selectedRuntimeRun } from './evaluationViewModel'
import type { EvaluationRunFilter, EvaluationTab, RuntimeEvaluationSummary, RuntimeRunDetail, RuntimeRunSummary } from './types'

type EvaluationPageProps = {
  onContextNavigate?: (target: ContextTrailTarget) => void
  onViewDiagnosis?: (agentRunId: string) => void
  onViewRun?: (runId: number) => void
  onViewTrace?: (traceId: string) => void
}

type LoadState = 'loading' | 'ready' | 'error'
type TrailState = 'idle' | 'loading' | 'linked' | 'unavailable'

type ApiMetadataSummaryResponse = {
  apiId: string | number
  apiDocId: string | number
  operationId: string
  method: string
  path: string
  summary: string | null
}

const tabs: Array<{ id: EvaluationTab; icon: typeof Activity }> = [
  { id: 'Overview', icon: Activity },
  { id: 'Deterministic', icon: Scale },
  { id: 'LLM Judge', icon: Sparkles },
  { id: 'Runtime Facts', icon: Database },
  { id: 'Cost & Latency', icon: Clock3 },
]

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
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

export function EvaluationPage({ onContextNavigate, onViewDiagnosis, onViewRun, onViewTrace }: EvaluationPageProps) {
  const { t, ui } = useConsoleLanguage()
  const { expireSession } = useAuth()
  const {
    activateContext,
    recordDiagnosis,
    recordEndpoint,
    recordObservedTestCase,
    recordReport,
    recordRun,
  } = useContextTrail()
  const { currentProject, loading: projectsLoading, refreshProjects } = useProject()
  const [summary, setSummary] = useState<RuntimeEvaluationSummary | null>(null)
  const [runs, setRuns] = useState<RuntimeRunSummary[]>([])
  const [detail, setDetail] = useState<RuntimeRunDetail | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [runQuery, setRunQuery] = useState('')
  const [runFilter, setRunFilter] = useState<EvaluationRunFilter>('ALL')
  const [activeTab, setActiveTab] = useState<EvaluationTab>('Overview')
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [detailLoading, setDetailLoading] = useState(false)
  const [trailState, setTrailState] = useState<TrailState>('idle')
  const [error, setError] = useState<ApiError | null>(null)
  const [detailError, setDetailError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)

  const projectId = currentProject?.projectId ?? null
  const projectQuery = projectId === null ? '' : `?projectId=${encodeURIComponent(projectId)}`

  useEffect(() => {
    if (projectsLoading || projectId === null) return

    let cancelled = false
    const controller = new AbortController()
    setLoadState('loading')
    setError(null)

    void Promise.all([
      agentApiFetch<RuntimeEvaluationSummary>(`/api/v1/evaluation/runtime/summary${projectQuery}`, { signal: controller.signal }),
      agentApiFetch<RuntimeRunSummary[]>(`/api/v1/evaluation/runtime/runs${projectQuery}`, { signal: controller.signal }),
    ])
      .then(([nextSummary, nextRuns]) => {
        if (cancelled) return
        setSummary(nextSummary)
        setRuns(nextRuns)
        setSelectedRunId((currentId) => nextRuns.some((run) => run.agentRunId === currentId) ? currentId : nextRuns[0]?.agentRunId ?? null)
        setLoadState('ready')
      })
      .catch((requestError: unknown) => {
        if (cancelled || isAbortError(requestError)) return
        const apiError = requestError instanceof ApiError
          ? requestError
          : new ApiError('Unable to load runtime evaluation data.', 0, 'RUNTIME_EVALUATION_LOAD_FAILED')
        setError(apiError)
        setLoadState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [attempt, expireSession, projectId, projectQuery, projectsLoading, refreshProjects])

  const visibleRuns = useMemo(
    () => filterRuntimeRuns(runs, runFilter, runQuery),
    [runFilter, runQuery, runs],
  )

  useEffect(() => {
    setSelectedRunId((currentId) => resolveSelectedRunId(currentId, visibleRuns))
  }, [runs, visibleRuns])

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null)
      setDetailError(null)
      return
    }

    let cancelled = false
    const controller = new AbortController()
    setDetailLoading(true)
    setDetailError(null)
    setDetail(null)

    void agentApiFetch<RuntimeRunDetail>(`/api/v1/evaluation/runtime/runs/${encodeURIComponent(selectedRunId)}`, { signal: controller.signal })
      .then((nextDetail) => {
        if (!cancelled) setDetail(nextDetail)
      })
      .catch((requestError: unknown) => {
        if (cancelled || isAbortError(requestError)) return
        const apiError = requestError instanceof ApiError
          ? requestError
          : new ApiError('Unable to load runtime run details.', 0, 'RUNTIME_RUN_LOAD_FAILED')
        setDetailError(apiError)
        if (apiError.status === 401) expireSession()
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [attempt, expireSession, selectedRunId])

  useEffect(() => {
    setTrailState('idle')
    if (!detail || detail.executionType !== 'DIAGNOSIS' || detail.runId === null || projectId === null) return

    let cancelled = false
    const controller = new AbortController()
    setTrailState('loading')

    void Promise.allSettled([
      fetchExactRun(projectId, detail.runId, controller.signal),
      apiFetch<ApiMetadataSummaryResponse[]>(`/api/v1/projects/${encodeURIComponent(projectId)}/openapi/apis`, { signal: controller.signal }),
    ]).then(([runsResult, endpointsResult]) => {
      if (cancelled) return
      const endpoints = endpointsResult.status === 'fulfilled' ? endpointsResult.value.map(normalizeEndpointMetadata) : []

      const owningRun = runsResult.status === 'fulfilled' ? runsResult.value : null
      const target = runtimeContextTarget(detail, owningRun)
      if (!owningRun || !target) {
        setTrailState('unavailable')
        return
      }

      recordRun({
        apiId: owningRun.apiId,
        caseId: owningRun.caseId,
        createdAt: owningRun.createdAt,
        name: owningRun.testCaseName,
        runId: owningRun.runId,
        status: owningRun.status,
      })
      const endpoint = resolveRuntimeEndpoint(owningRun.apiId, endpoints)
      if (endpoint) recordEndpoint(endpoint)
      recordObservedTestCase({
        apiDocId: endpoint?.apiDocId ?? '',
        apiId: endpoint?.id ?? owningRun.apiId,
        id: owningRun.caseId,
        name: owningRun.testCaseName,
        runId: owningRun.runId,
      })
      recordDiagnosis({
        agentRunId: detail.agentRunId,
        id: detail.agentRunId,
        reportId: detail.reportId,
        runId: owningRun.runId,
        status: detail.status,
      })
      if (detail.reportId) {
        recordReport({
          agentRunId: detail.agentRunId,
          id: detail.reportId,
          reportId: detail.reportId,
          runId: owningRun.runId,
        })
      }
      activateContext(target)
      setTrailState('linked')
    }).catch((requestError: unknown) => {
      if (!cancelled && !isAbortError(requestError)) setTrailState('unavailable')
    })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [activateContext, detail, projectId, recordDiagnosis, recordEndpoint, recordObservedTestCase, recordReport, recordRun])

  const selectRun = (runId: string) => {
    setSelectedRunId(runId)
    setActiveTab('Overview')
  }

  const refresh = () => setAttempt((current) => current + 1)
  const selectedRun = selectedRuntimeRun(detail, selectedRunId)
  const hasTrail = trailState === 'linked'

  return (
    <section className="evaluation-page" aria-label={t('page.evaluation.title')}>
      <div className="evaluation-page-heading">
        <PageHeader description={t('page.evaluation.description')} title={t('page.evaluation.title')} />
        <button className="evaluation-action-button" onClick={refresh} type="button"><RefreshCw size={15} strokeWidth={1.8} /> {ui('Refresh')}</button>
      </div>

      <div className="evaluation-source-banner">
        <span className="evaluation-source-icon"><Gauge size={17} strokeWidth={1.8} /></span>
        <div><strong>{ui('Python AgentLab Evaluation')}</strong><small>{ui('Runtime Agent Run analysis only. Evaluation and Benchmark remain separate; runtime facts, deterministic evaluation, and model-based evaluation are not interchangeable.')}</small></div>
        {summary ? <span className="evaluation-source-count">{summary.runCount} {ui('runs')}</span> : null}
      </div>

      {loadState === 'loading' ? <PageState description={ui('Reading runtime facts from Python AgentLab.')} kind="loading" title={ui('Loading Runtime Evaluation')} /> : null}
      {loadState === 'error' ? <PageState actionLabel={t('common.retry')} description={error?.message ?? ui('The Python runtime evaluation API could not be reached.')} kind="error" onAction={refresh} title={ui('Runtime Evaluation unavailable')} /> : null}
      {loadState === 'ready' && summary ? (
        <div className="evaluation-layout">
          <EvaluationRuns allRuns={runs} filter={runFilter} onFilterChange={setRunFilter} onQueryChange={setRunQuery} onSelect={selectRun} query={runQuery} runs={visibleRuns} selectedRunId={selectedRunId} />

          <div className="evaluation-workspace">
            {detailLoading ? <section className="evaluation-summary panel"><p className="evaluation-empty-state">{ui('Loading selected runtime facts...')}</p></section> : null}
            {detailError ? <section className="evaluation-summary panel"><p className="evaluation-empty-state">{detailError.message}</p></section> : null}
            {!detailLoading && !detailError && selectedRun ? (
              <EvaluationSummary onViewDiagnosis={onViewDiagnosis} onViewRun={onViewRun} onViewTrace={onViewTrace} run={selectedRun} />
            ) : null}
            {!detailLoading && !detailError && !selectedRun ? (
              <section className="evaluation-summary panel"><p className="evaluation-empty-state">{runs.length ? ui('No runtime run matches the current filters.') : ui('No runtime Evaluation runs are available for this project.')}</p></section>
            ) : null}

            <section className="evaluation-tabs-panel panel" aria-label={ui('Evaluation workspace')}>
              <div className="evaluation-tabs" role="tablist" aria-label={ui('Evaluation views')}>
                {tabs.map(({ icon: Icon, id }) => (
                  <button aria-selected={activeTab === id} className={`evaluation-tab${activeTab === id ? ' is-active' : ''}`} key={id} onClick={() => setActiveTab(id)} role="tab" type="button">
                    <Icon size={15} strokeWidth={1.8} /> {ui(id)}
                  </button>
                ))}
              </div>
              <div className="evaluation-tab-content">
                {selectedRun ? (
                  <>
                    {activeTab === 'Overview' ? <EvaluationOverviewTab detail={selectedRun} /> : null}
                    {activeTab === 'Deterministic' ? <EvaluationDeterministicTab detail={selectedRun} /> : null}
                    {activeTab === 'LLM Judge' ? <EvaluationJudgeTab detail={selectedRun} /> : null}
                    {activeTab === 'Runtime Facts' ? <EvaluationRuntimeFactsTab detail={selectedRun} /> : null}
                    {activeTab === 'Cost & Latency' ? <EvaluationCostLatencyTab detail={selectedRun} /> : null}
                  </>
                ) : <p className="evaluation-empty-state">{ui('Select a runtime run to inspect its Evaluation workspace.')}</p>}
              </div>
            </section>
          </div>

          <div className="evaluation-context-column">
            <ContextTrail onNavigate={(target) => onContextNavigate?.(target)} visibleGroups={hasTrail ? ['endpoint', 'testcase', 'run', 'diagnosis', 'report'] : []} />
            <p>{trailState === 'loading' ? ui('Resolving existing business context...') : hasTrail ? ui('Evaluation adds analysis only; it does not add Context Trail nodes.') : ui('No linked business context was resolved for this Agent Run.')}</p>
          </div>
        </div>
      ) : null}
    </section>
  )
}
