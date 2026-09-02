import { RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'
import { PageState } from '../../components/common/PageState'
import { PageHeader } from '../../components/layout/PageHeader'
import { agentApiFetch, ApiError } from '../../lib/api-client'
import { EvaluationOverviewPanels } from './components/EvaluationOverviewPanels'
import { EvaluationRuns } from './components/EvaluationRuns'
import { EvaluationSummary } from './components/EvaluationSummary'
import {
  EvaluationLatencyTab,
  EvaluationOverviewTab,
  EvaluationTokenCostTab,
  EvaluationToolTab,
  EvaluationValidationTab,
} from './components/EvaluationTabContent'
import type { EvaluationRunFilter, EvaluationTab, RuntimeEvaluationSummary, RuntimeRunDetail, RuntimeRunStatus, RuntimeRunSummary } from './types'

const tabs: EvaluationTab[] = ['Overview', 'Validation', 'Tool Execution', 'Latency', 'Token & Cost']

type LoadState = 'loading' | 'ready' | 'error'

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function matchesRunFilter(status: RuntimeRunStatus, filter: EvaluationRunFilter) {
  return filter === 'ALL' || status === filter
}

export function EvaluationPage() {
  const { t, ui } = useConsoleLanguage()
  const { expireSession } = useAuth()
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
  const [error, setError] = useState<ApiError | null>(null)
  const [detailError, setDetailError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)

  const projectId = currentProject?.projectId ?? null
  const projectQuery = projectId ? `?projectId=${encodeURIComponent(projectId)}` : ''

  useEffect(() => {
    if (projectsLoading) return

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
  }, [expireSession, projectQuery, projectsLoading, refreshProjects, attempt])

  const normalizedRunQuery = runQuery.trim().toLowerCase()
  const visibleRuns = useMemo(() => runs.filter((run) => {
    const searchText = [
      run.agentRunId,
      run.traceId,
      run.executionType,
      run.status,
      run.provider,
      run.model,
      run.apiId ?? '',
      run.runId ?? '',
    ].join(' ').toLowerCase()
    return matchesRunFilter(run.status, runFilter) && (!normalizedRunQuery || searchText.includes(normalizedRunQuery))
  }), [normalizedRunQuery, runFilter, runs])

  useEffect(() => {
    if (visibleRuns.length > 0 && !visibleRuns.some((run) => run.agentRunId === selectedRunId)) {
      setSelectedRunId(visibleRuns[0].agentRunId)
      setActiveTab('Overview')
    }
    if (visibleRuns.length === 0 && runs.length === 0) setSelectedRunId(null)
  }, [runs.length, selectedRunId, visibleRuns])

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
        if (cancelled) return
        setDetail(nextDetail)
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
  }, [expireSession, selectedRunId, attempt])

  const selectRun = (runId: string) => {
    setSelectedRunId(runId)
    setActiveTab('Overview')
  }

  const refresh = () => setAttempt((current) => current + 1)
  const selectedRun = detail && detail.agentRunId === selectedRunId ? detail : null

  return (
    <section className="evaluation-page" aria-label={t('page.evaluation.title')}>
      <PageHeader
        description={t('page.evaluation.description')}
        title={t('page.evaluation.title')}
      />

      {loadState === 'loading' ? <PageState description={ui('Reading runtime facts from Python AgentLab.')} kind="loading" title={ui('Loading Runtime Evaluation')} /> : null}
      {loadState === 'error' ? <PageState actionLabel={t('common.retry')} description={error?.message ?? ui('The Python runtime evaluation API could not be reached.')} kind="error" onAction={refresh} title={ui('Runtime Evaluation unavailable')} /> : null}
      {loadState === 'ready' && summary ? (
        <>
          <div className="evaluation-toolbar">
            <span>{ui('Runtime facts only · no Benchmark or Ground Truth metrics')}</span>
            <button className="evaluation-action-button" onClick={refresh} type="button">
              <RefreshCw size={15} strokeWidth={1.8} /> {ui('Refresh')}
            </button>
          </div>
          <div className="evaluation-layout">
            <EvaluationRuns
              filter={runFilter}
              onFilterChange={setRunFilter}
              onQueryChange={setRunQuery}
              onSelect={selectRun}
              query={runQuery}
              runs={visibleRuns}
              selectedRunId={selectedRunId}
            />

            <div className="evaluation-workspace">
              {selectedRun ? <EvaluationSummary run={selectedRun} /> : (
                <section className="evaluation-summary panel"><p className="evaluation-empty-state">{ui('No runtime run selected.')}</p></section>
              )}
              <EvaluationOverviewPanels summary={summary} />
              <div className="evaluation-tabs-panel panel">
                <div className="evaluation-tabs" role="tablist" aria-label={ui('Runtime Evaluation views')}>
                  {tabs.map((tab) => (
                    <button
                      aria-selected={activeTab === tab}
                      className={`evaluation-tab${activeTab === tab ? ' is-active' : ''}`}
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      role="tab"
                      type="button"
                    >
                      {ui(tab)}
                    </button>
                  ))}
                </div>
                <div className="evaluation-tab-content">
                  {detailLoading ? <p className="evaluation-empty-state">{ui('Loading selected runtime facts...')}</p> : null}
                  {detailError ? <p className="evaluation-empty-state">{detailError.message}</p> : null}
                  {!detailLoading && !detailError ? (
                    <>
                      {activeTab === 'Overview' ? <EvaluationOverviewTab detail={selectedRun} summary={summary} /> : null}
                      {activeTab === 'Validation' ? <EvaluationValidationTab detail={selectedRun} summary={summary} /> : null}
                      {activeTab === 'Tool Execution' ? <EvaluationToolTab detail={selectedRun} summary={summary} /> : null}
                      {activeTab === 'Latency' ? <EvaluationLatencyTab detail={selectedRun} summary={summary} /> : null}
                      {activeTab === 'Token & Cost' ? <EvaluationTokenCostTab detail={selectedRun} summary={summary} /> : null}
                    </>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </section>
  )
}
