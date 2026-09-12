import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { PageState } from '../../components/common/PageState'
import { PageHeader } from '../../components/layout/PageHeader'
import { ApiError, agentApiFetch } from '../../lib/api-client'
import './benchmark.css'
import { isCurrentResult } from './benchmarkViewModel'
import { finalResultSummary, loadFinalResult, type FinalResultReport } from './finalResultAdapter'
import { FinalBenchmarkOverview } from './components/FinalBenchmarkOverview'
import { BenchmarkCategories, BenchmarkScorecards, BenchmarkOverview } from './components/BenchmarkOverview'
import { BenchmarkRuns } from './components/BenchmarkRuns'
import { BenchmarkSummary } from './components/BenchmarkSummary'
import { BenchmarkTabContent } from './components/BenchmarkTabContent'
import { BenchmarkDetailDialog } from './components/BenchmarkDetailDialog'
import { Full105History } from './components/Full105History'
import type {
  BenchmarkRunDetail,
  BenchmarkRunFilter,
  BenchmarkRunSummary,
  BenchmarkTab,
  BenchmarkTask,
} from './types'

const tabs: BenchmarkTab[] = ['Overview', 'Categories', 'Tasks', 'Failures', 'Reproducibility']

type LoadState = 'loading' | 'ready' | 'error'

function matchesRunFilter(status: BenchmarkRunSummary['status'], filter: BenchmarkRunFilter) {
  return filter === 'ALL' || status === filter
}

function metadataText(value: BenchmarkRunSummary['model']) {
  if (value.availability !== 'AVAILABLE') return value.availability
  if (typeof value.value === 'string') return value.value
  try {
    return JSON.stringify(value.value)
  } catch {
    return 'UNKNOWN'
  }
}

export function BenchmarkPage() {
  const { t, ui } = useConsoleLanguage()
  const [finalReport, setFinalReport] = useState<FinalResultReport | null>(null)
  const [apiUnavailable, setApiUnavailable] = useState(false)
  const [runs, setRuns] = useState<BenchmarkRunSummary[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<BenchmarkRunDetail | null>(null)
  const [tasks, setTasks] = useState<BenchmarkTask[]>([])
  const [runsState, setRunsState] = useState<LoadState>('loading')
  const [detailState, setDetailState] = useState<LoadState>('loading')
  const [tasksState, setTasksState] = useState<LoadState>('loading')
  const [error, setError] = useState<ApiError | null>(null)
  const [runQuery, setRunQuery] = useState('')
  const [runFilter, setRunFilter] = useState<BenchmarkRunFilter>('ALL')
  const [activeTab, setActiveTab] = useState<BenchmarkTab>('Overview')
  const [detailDialog, setDetailDialog] = useState<BenchmarkTab | 'Runs' | 'History' | null>(null)
  const [refreshNonce, setRefreshNonce] = useState(0)
  const [taskCategory, setTaskCategory] = useState('ALL')

  useEffect(() => {
    const controller = new AbortController()
    setRunsState('loading')
    setFinalReport(null)
    setError(null)
    void agentApiFetch<BenchmarkRunSummary[]>('/api/v1/benchmark/results', {
      signal: controller.signal,
    }).then((nextRuns) => {
      if (controller.signal.aborted) return
      setApiUnavailable(false)
      setRuns(nextRuns)
      setSelectedRunId((current) => (
        current && nextRuns.some((run) => run.evaluationRunId === current)
          ? current
          : nextRuns.find(run => run.role === 'CURRENT')?.evaluationRunId ?? nextRuns[0]?.evaluationRunId ?? null
      ))
      setRunsState('ready')
    }).catch((nextError: unknown) => {
      if (controller.signal.aborted) return
      setApiUnavailable(true)
      setRuns([])
      setSelectedRunId(null)
      setRunsState('error')
      setError(nextError instanceof ApiError
        ? nextError
        : new ApiError('Unable to load Benchmark artifacts.', 0, 'BENCHMARK_LOAD_FAILED'))
    })
    return () => controller.abort()
  }, [refreshNonce])

  useEffect(() => {
    if (!selectedRunId || runsState !== 'ready') {
      setDetail(null)
      setTasks([])
      setDetailState('ready')
      setTasksState('ready')
      return
    }

    const controller = new AbortController()
    setFinalReport(null)
    const loadPersistedResult = () => {
      const encodedRunId = encodeURIComponent(selectedRunId)
      void agentApiFetch<BenchmarkRunDetail>('/api/v1/benchmark/results/' + encodedRunId, {
        signal: controller.signal,
      }).then((nextDetail) => {
        if (controller.signal.aborted) return
        if (!isCurrentResult(controller.signal, selectedRunId, nextDetail, [])) throw new ApiError('Result identity mismatch', 0, 'BENCHMARK_IDENTITY_MISMATCH')
        setDetail(nextDetail)
        setDetailState('ready')
      }).catch((nextError: unknown) => {
        if (controller.signal.aborted) return
        setDetailState('error')
        setError(nextError instanceof ApiError ? nextError : new ApiError('Unable to load Benchmark result artifacts.', 0, 'BENCHMARK_DETAIL_LOAD_FAILED'))
      })
      void agentApiFetch<BenchmarkTask[]>('/api/v1/benchmark/results/' + encodedRunId + '/tasks', {
        signal: controller.signal,
      }).then((nextTasks) => {
        if (controller.signal.aborted) return
        if (!nextTasks.every(task => task.evaluationRunId === selectedRunId)) throw new ApiError('Task identity mismatch', 0, 'BENCHMARK_IDENTITY_MISMATCH')
        setTasks(nextTasks)
        setTasksState('ready')
      }).catch(() => {
        if (controller.signal.aborted) return
        setTasks([])
        setTasksState('error')
      })
    }
    if (selectedRunId === finalResultSummary.evaluationRunId) {
      setDetail(null)
      setTasks([])
      setDetailState('loading')
      setTasksState('loading')
      void loadFinalResult(selectedRunId).then(report => {
        if (controller.signal.aborted) return
        if (!report) { loadPersistedResult(); return }
        setFinalReport(report)
        setDetail(report.detail)
        setTasks(report.tasks)
        setDetailState('ready')
        setTasksState('ready')
      }).catch(() => {
        if (controller.signal.aborted) return
        loadPersistedResult()
      })
      return () => controller.abort()
    }
    setDetail(null)
    setTasks([])
    setDetailState('loading')
    setTasksState('loading')
    setError(null)
    loadPersistedResult()
    return () => controller.abort()
  }, [selectedRunId, refreshNonce, runsState])

  const normalizedQuery = runQuery.trim().toLowerCase()
  const visibleRuns = useMemo(() => runs.filter((run) => {
    const searchText = [
      run.evaluationRunId,
      run.datasetId,
      run.datasetVersion,
      run.datasetSplit ?? '',
      run.status,
      metadataText(run.model),
      metadataText(run.evaluator),
      ...run.prompt.map(metadataText),
    ].join(' ').toLowerCase()
    return matchesRunFilter(run.status, runFilter)
      && (!normalizedQuery || searchText.includes(normalizedQuery))
  }), [normalizedQuery, runFilter, runs])

  const selectedRun = runs.find((run) => run.evaluationRunId === selectedRunId) ?? null

  const selectRun = useCallback((evaluationRunId: string) => {
    if (evaluationRunId === selectedRunId) return
    setDetail(null)
    setTasks([])
    setDetailState('loading')
    setTasksState('loading')
    setTaskCategory('ALL')
    setSelectedRunId(evaluationRunId)
    setActiveTab('Overview')
  }, [selectedRunId])

  const openDetail = useCallback((tab: BenchmarkTab, category = 'ALL') => {
    setTaskCategory(category)
    setActiveTab(tab)
    setDetailDialog(tab)
  }, [])

  const refresh = useCallback(() => {
    setRunsState('loading')
    setFinalReport(null)
    setDetail(null)
    setTasks([])
    setRefreshNonce((value) => value + 1)
  }, [])

  return (
    <section className="benchmark-page benchmark-redesign" aria-label={t('page.benchmark.title')}>
      <div className="benchmark-page-heading">
      <PageHeader
        description={t('page.benchmark.description')}
        title={t('page.benchmark.title')}
      />

      <div className="benchmark-readonly-toolbar">
        <span className="benchmark-readonly-badge">{ui('READ-ONLY ARTIFACT')}</span>
        <button className="panel-action benchmark-refresh-button" disabled={runsState === 'loading'} onClick={refresh} type="button">
          <RefreshCw size={15} strokeWidth={1.8} /> {ui('Refresh')}
        </button>
      </div>
      </div>

      {apiUnavailable && <p className="benchmark-source-notice" role="status">{ui('Benchmark API unavailable; retry after the service recovers.')}</p>}
      {runsState === 'loading' ? (
        <PageState
          description={ui('Reading existing Benchmark result artifacts.')}
          kind="loading"
          title={ui('Loading Benchmark results')}
        />
      ) : null}
      {runsState === 'error' ? (
        <PageState
          actionLabel={t('common.retry')}
          description={error?.message ?? ui('The Benchmark result API could not be reached.')}
          kind="error"
          onAction={refresh}
          title={ui('Benchmark results unavailable')}
        />
      ) : null}
      {runsState === 'ready' && runs.length === 0 ? (
        <PageState
          description={ui('No completed Benchmark result artifacts are available.')}
          kind="empty"
          title={ui('No Benchmark results')}
        />
      ) : null}

      {runsState === 'ready' && runs.length > 0 ? <div className="benchmark-results-workspace">
        {selectedRun && <BenchmarkSummary run={selectedRun} runs={runs} onSelect={selectRun} tasks={tasks} tasksState={tasksState} />}
        <div className="benchmark-selected-result">
          {detailState === 'loading' ? <PageState description={ui('Reading the selected result artifact.')} kind="loading" title={ui('Loading result')} /> : null}
          {detailState === 'error' ? <PageState actionLabel={t('common.retry')} description={error?.message ?? ui('The selected Benchmark result could not be read.')} kind="error" onAction={refresh} title={ui('Result unavailable')} /> : null}
          {selectedRun && detail && detailState === 'ready' ? <>

            <div className="benchmark-detail-actions" aria-label={ui('Benchmark views')}>
              {tabs.filter(tab => tab !== 'Overview').map(tab => <button className="panel-action" key={tab} onClick={() => openDetail(tab)} type="button">{ui(tab)}</button>)}
              <button className="panel-action" onClick={() => setDetailDialog('Runs')} type="button">{ui('Published Runs')}</button>
            </div>
            <div className="benchmark-result-content is-overview">
                {finalReport ? <FinalBenchmarkOverview report={finalReport} onCategory={type => openDetail('Tasks', type)} onFailures={() => openDetail('Failures')} onHistory={() => setDetailDialog('History')} onReproducibility={() => openDetail('Reproducibility')} /> : <>
                <BenchmarkScorecards detail={detail} />
                <BenchmarkCategories detail={detail} tasks={tasks} tasksState={tasksState} onSelect={type => openDetail('Tasks', type)} />
                <BenchmarkOverview detail={detail} />
                </>}
            </div>
            <BenchmarkDetailDialog eyebrow={ui('Selected Benchmark Result')} onClose={() => setDetailDialog(null)} open={detailDialog !== null && detailDialog !== 'Runs' && detailDialog !== 'History'} title={ui(activeTab)}>
              {activeTab === 'Overview' ? null : <BenchmarkTabContent finalReport={finalReport ?? undefined} key={detail.evaluationRunId} detail={detail} tasks={tasks} tasksState={tasksState} tab={activeTab} category={taskCategory} onCategoryChange={setTaskCategory} />}
            </BenchmarkDetailDialog>
            <BenchmarkDetailDialog eyebrow={ui('APIOps Bench')} onClose={() => setDetailDialog(null)} open={detailDialog === 'Runs'} title={ui('Published Runs')}>
              <BenchmarkRuns filter={runFilter} onFilterChange={setRunFilter} onQueryChange={setRunQuery} onSelect={(id) => { selectRun(id); setDetailDialog(null) }} query={runQuery} runs={visibleRuns} selectedViewId={selectedRunId} />
            </BenchmarkDetailDialog>
            <BenchmarkDetailDialog eyebrow={ui('Verified formal runs')} onClose={() => setDetailDialog(null)} open={detailDialog === 'History'} title={ui('Full-105 Benchmark History')}>
              <Full105History />
            </BenchmarkDetailDialog>
          </> : null}
        </div>
      </div> : null}
    </section>
  )
}
