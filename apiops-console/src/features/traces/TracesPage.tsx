import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { PageHeader } from '../../components/layout/PageHeader'
import { PageState } from '../../components/common/PageState'
import { ApiError, agentApiFetch } from '../../lib/api-client'
import { SelectedStepInspector } from './components/SelectedStepInspector'
import { TraceExplorer } from './components/TraceExplorer'
import { TraceSummary } from './components/TraceSummary'
import { TraceWaterfall } from './components/TraceWaterfall'
import { groupTraceRecords, type TraceApiRecord } from './trace-api'
import type { TraceFilter, TraceInspectorTab, TraceRecord } from './types'

type TraceLoadState = 'loading' | 'ready' | 'error'

type TracesPageProps = {
  onSelected?: (traceId: string) => void
  initialTraceId?: string | null
  onContextNavigate?: (target: ContextTrailTarget) => void
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function asApiError(error: unknown) {
  return error instanceof ApiError
    ? error
    : new ApiError('Unable to load traces.', 0, 'TRACES_LOAD_FAILED')
}

function matchesFilter(trace: TraceRecord, filter: TraceFilter) {
  if (filter === 'ALL') return true
  if (filter === 'SUCCESS') return trace.status === 'SUCCESS'
  if (filter === 'FAILED') return ['FAILED', 'REJECTED', 'DENIED'].includes(trace.status)
  if (filter === 'PYTHON' || filter === 'JAVA') return trace.steps.some((step) => step.source === filter)
  return trace.tags.includes(filter)
}

export function TracesPage({ initialTraceId = null, onContextNavigate, onSelected }: TracesPageProps) {
  const { expireSession } = useAuth()
  const { t, ui } = useConsoleLanguage()
  const { activateContext, diagnoses, runs } = useContextTrail()
  const { currentProject, refreshProjects } = useProject()
  const [traces, setTraces] = useState<TraceRecord[]>([])
  const [loadState, setLoadState] = useState<TraceLoadState>('loading')
  const [loadError, setLoadError] = useState<ApiError | null>(null)
  const [reloadAttempt, setReloadAttempt] = useState(0)
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null)
  const [selectedStepId, setSelectedStepId] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<TraceFilter>('ALL')
  const [activeTab, setActiveTab] = useState<TraceInspectorTab>('Overview')
  const [expandedStepIds, setExpandedStepIds] = useState<Set<string>>(new Set())
  const [isStepModalOpen, setIsStepModalOpen] = useState(false)

  const projectId = currentProject?.projectId ?? null

  const fetchTraces = useCallback(async (nextProjectId: string, signal: AbortSignal) => {
    const records = await agentApiFetch<TraceApiRecord[]>(
      `/api/v1/traces?projectId=${encodeURIComponent(nextProjectId)}`,
      { signal },
    )
    return groupTraceRecords(records)
  }, [])

  useEffect(() => {
    let cancelled = false
    setTraces([])
    setSelectedTraceId(null)
    setSelectedStepId('')
    setExpandedStepIds(new Set())
    setIsStepModalOpen(false)
    setLoadError(null)

    if (!projectId) {
      setLoadState('ready')
      return () => { cancelled = true }
    }

    setLoadState('loading')
    const controller = new AbortController()
    void fetchTraces(projectId, controller.signal)
      .then((nextTraces) => {
        if (cancelled) return
        setTraces(nextTraces)
        const initialTrace = initialTraceId
          ? nextTraces.find((trace) => trace.id === initialTraceId || trace.traceId === initialTraceId)
          : null
        setSelectedTraceId(initialTrace?.id ?? nextTraces[0]?.id ?? null)
        setLoadState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = asApiError(error)
        setTraces([])
        setSelectedTraceId(null)
        setLoadError(apiError)
        setLoadState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, fetchTraces, initialTraceId, projectId, refreshProjects, reloadAttempt])

  const normalizedQuery = query.trim().toLowerCase()
  const visibleTraces = useMemo(() => traces.filter((trace) => {
    const searchText = `${trace.name} ${trace.agentRunId} ${trace.traceId} ${trace.runId}`.toLowerCase()
    return matchesFilter(trace, filter) && (!normalizedQuery || searchText.includes(normalizedQuery))
  }), [filter, normalizedQuery, traces])

  useEffect(() => {
    if (!visibleTraces.length) {
      setSelectedTraceId(null)
      setSelectedStepId('')
      return
    }
    if (!visibleTraces.some((trace) => trace.id === selectedTraceId)) {
      setSelectedTraceId(visibleTraces[0].id)
    }
  }, [selectedTraceId, visibleTraces])

  const selectedTrace = visibleTraces.find((trace) => trace.id === selectedTraceId) ?? null

  useEffect(() => {
    if (!selectedTrace) {
      setSelectedStepId('')
      setExpandedStepIds(new Set())
      setIsStepModalOpen(false)
      return
    }
    setSelectedStepId('')
    setExpandedStepIds(new Set(selectedTrace.steps.filter((step) => step.expandable).map((step) => step.id)))
    setActiveTab('Overview')
  }, [selectedTrace?.id])

  const selectedStep = selectedTrace?.steps.find((step) => step.id === selectedStepId) ?? null

  const selectedStepIndex = selectedTrace && selectedStep
    ? selectedTrace.steps.findIndex((step) => step.id === selectedStep.id)
    : -1

  const traceContextTarget = useMemo<ContextTrailTarget | null>(() => {
    if (!selectedTrace || !/^\d+$/.test(selectedTrace.runId)) return null
    const runId = Number(selectedTrace.runId)
    if (!Number.isSafeInteger(runId)) return null

    const diagnosis = diagnoses.find((item) => item.runId === runId && item.agentRunId === selectedTrace.agentRunId)
    if (diagnosis) {
      return {
        type: 'diagnosis',
        id: diagnosis.id,
        agentRunId: diagnosis.agentRunId,
        runId: diagnosis.runId,
      }
    }

    const run = runs.find((item) => item.runId === runId)
    return run
      ? { type: 'run', id: run.id, runId: run.runId, caseId: run.caseId, apiId: run.apiId }
      : null
  }, [diagnoses, runs, selectedTrace])

  useEffect(() => {
    if (traceContextTarget) activateContext(traceContextTarget)
  }, [activateContext, traceContextTarget])

  const selectTrace = (traceId: string) => {
    const nextTrace = visibleTraces.find((trace) => trace.id === traceId)
    if (!nextTrace) return
    setSelectedTraceId(traceId)
    onSelected?.(traceId)
    setSelectedStepId('')
    setExpandedStepIds(new Set(nextTrace.steps.filter((step) => step.expandable).map((step) => step.id)))
    setActiveTab('Overview')
    setIsStepModalOpen(false)
  }

  const selectStep = (stepId: string) => {
    if (!selectedTrace?.steps.some((step) => step.id === stepId)) return
    setSelectedStepId(stepId)
    setActiveTab('Overview')
    setIsStepModalOpen(true)
  }

  const moveSelectedStep = (offset: -1 | 1) => {
    if (!selectedTrace || selectedStepIndex < 0) return
    const nextStep = selectedTrace.steps[selectedStepIndex + offset]
    if (!nextStep) return
    setSelectedStepId(nextStep.id)
    setActiveTab('Overview')
  }

  const toggleStep = (stepId: string) => {
    setExpandedStepIds((current) => {
      const next = new Set(current)
      if (next.has(stepId)) next.delete(stepId)
      else next.add(stepId)
      return next
    })
  }

  const pageHeader = (
    <div className="traces-page-header">
      <PageHeader
        description={t('page.traces.description')}
        title={t('page.traces.title')}
      />
      <button className="traces-refresh-button" onClick={() => setReloadAttempt((attempt) => attempt + 1)} type="button">
        <RefreshCw size={15} strokeWidth={1.8} />
        {ui('Refresh')}
      </button>
    </div>
  )

  if (loadState === 'loading') {
    return (
      <section className="traces-page" aria-label={t('page.traces.title')}>
        {pageHeader}
        <PageState
          description={ui('Reading observed AgentLab trace records for the current project.')}
          kind="loading"
          title={ui('Loading traces')}
        />
      </section>
    )
  }

  if (loadState === 'error') {
    return (
      <section className="traces-page" aria-label={t('page.traces.title')}>
        {pageHeader}
        <PageState
          actionLabel={t('common.retry')}
          description={loadError?.status === 403 ? t('auth.accessDeniedDescription') : loadError?.message ?? ui('The trace read API is unavailable.')}
          kind={loadError?.status === 403 ? 'forbidden' : 'error'}
          onAction={() => setReloadAttempt((attempt) => attempt + 1)}
          title={loadError?.status === 403 ? t('auth.accessDeniedTitle') : ui('Traces unavailable')}
        />
      </section>
    )
  }

  if (!traces.length) {
    return (
      <section className="traces-page" aria-label={t('page.traces.title')}>
        {pageHeader}
        <PageState
          description={ui('No observed trace records exist for the current project.')}
          kind="empty"
          title={ui('No traces found.')}
        />
      </section>
    )
  }

  return (
    <section className="traces-page" aria-label={t('page.traces.title')}>
      {pageHeader}

      <div className="traces-layout">
        <TraceExplorer
          filter={filter}
          onFilterChange={setFilter}
          onQueryChange={setQuery}
          onSelect={selectTrace}
          query={query}
          selectedTraceId={selectedTrace?.id ?? ''}
          traces={visibleTraces}
        />

        <div className="traces-workspace">
          {selectedTrace ? (
            <>
              <TraceSummary trace={selectedTrace} />
              <TraceWaterfall
                expandedStepIds={expandedStepIds}
                onCollapseAll={() => setExpandedStepIds(new Set())}
                onExpandAll={() => setExpandedStepIds(new Set(selectedTrace.steps.filter((step) => step.expandable).map((step) => step.id)))}
                onStepSelect={selectStep}
                onToggleStep={toggleStep}
                selectedStepId={selectedStep?.id ?? ''}
                trace={selectedTrace}
              />
            </>
          ) : (
            <PageState
              description={ui('No traces match the current filters.')}
              kind="empty"
              title={ui('No traces found.')}
            />
          )}
        </div>

        <ContextTrail onNavigate={(target) => onContextNavigate?.(target)} />
      </div>

      {selectedStep && isStepModalOpen ? (
        <SelectedStepInspector
          activeTab={activeTab}
          hasNext={selectedStepIndex >= 0 && selectedTrace ? selectedStepIndex < selectedTrace.steps.length - 1 : false}
          hasPrevious={selectedStepIndex > 0}
          onClose={() => setIsStepModalOpen(false)}
          onNext={() => moveSelectedStep(1)}
          onPrevious={() => moveSelectedStep(-1)}
          onTabChange={setActiveTab}
          step={selectedStep}
        />
      ) : null}
    </section>
  )
}
