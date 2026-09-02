import { ChevronDown, ChevronRight, FileCheck2, Filter, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { PageState } from '../../components/common/PageState'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { agentApiFetch, apiFetch, ApiError } from '../../lib/api-client'
import { formatTime } from '../runs/presentation'
import { RunStatusBadge } from '../runs/components/RunStatusBadge'
import type { RunStatus, RunSummary, TestReport } from '../runs/types'
import { isDiagnosableStatus } from '../runs/types'
import type { DiagnosisExecutionResponse } from '../diagnosis/types'
import { DiagnosisRuntimeSelector, type DiagnosisRuntime } from './components/DiagnosisRuntimeSelector'
import { DiagnosisWorkflowProgress } from './components/DiagnosisWorkflowProgress'
import { ExecutionEvidence } from './components/ExecutionEvidence'
import { HumanApprovalPanel } from './components/HumanApprovalPanel'

type DiagnosisAgentExecutionPageProps = {
  initialRunId: string | null
  returnTo?: 'Runs' | 'Diagnosis'
  onClose?: () => void
  onViewResult: (agentRunId: string) => void
  onViewRunReport?: (runId: number) => void
}

type LoadState = 'loading' | 'ready' | 'error'
type ActionState = 'idle' | 'starting' | 'resuming'
type StudioFilter = 'ALL' | 'FAILED' | 'READY' | 'RUNNING' | 'DIAGNOSED'

const filterOptions: Array<{ value: StudioFilter; label: string }> = [
  { value: 'ALL', label: 'All' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'READY', label: 'Ready' },
  { value: 'RUNNING', label: 'Running' },
  { value: 'DIAGNOSED', label: 'Diagnosed' },
]

const statusGroupOrder: RunStatus[] = [
  'ASSERTION_FAILED',
  'EXECUTION_FAILED',
  'TIMEOUT',
  'RUNNING',
  'SUCCESS',
  'CANCELLED',
  'PENDING',
]

function parseRunId(value: string | null) {
  if (!value) return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function normalizeRunSummary(run: RunSummary): RunSummary {
  return {
    ...run,
    runId: Number(run.runId),
    durationMs: run.durationMs === null ? null : Number(run.durationMs),
  }
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function asApiError(error: unknown, fallback: string) {
  return error instanceof ApiError ? error : new ApiError(fallback, 0, 'NETWORK_ERROR')
}

function filterMatches(run: RunSummary, filter: StudioFilter, diagnosedRunIds: ReadonlySet<number>) {
  if (filter === 'ALL') return true
  if (filter === 'FAILED' || filter === 'READY') return isDiagnosableStatus(run.status)
  if (filter === 'RUNNING') return run.status === 'RUNNING'
  return diagnosedRunIds.has(run.runId)
}

function groupRuns(runs: RunSummary[]) {
  return statusGroupOrder
    .map((status) => ({ status, runs: runs.filter((run) => run.status === status) }))
    .filter((group) => group.runs.length > 0)
}

function runFailureLabel(run: RunSummary) {
  return run.failureType && run.failureType !== 'NONE' ? run.failureType : run.status
}

type AllRunsPanelProps = {
  runs: RunSummary[]
  totalRuns: number
  selectedRunId: number | null
  query: string
  filter: StudioFilter
  diagnosedRunIds: ReadonlySet<number>
  onQueryChange: (query: string) => void
  onFilterChange: (filter: StudioFilter) => void
  onSelect: (runId: number) => void
}

function AllRunsPanel({
  diagnosedRunIds,
  filter,
  onFilterChange,
  onQueryChange,
  onSelect,
  query,
  runs,
  selectedRunId,
  totalRuns,
}: AllRunsPanelProps) {
  const { language, ui } = useConsoleLanguage()
  const locale = language === 'zh-CN' ? 'zh-CN' : 'en-US'
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const groupedRuns = groupRuns(runs)

  const toggleGroup = (status: RunStatus) => {
    setExpandedGroups((current) => ({
      ...current,
      [status]: !(current[status] ?? status !== 'SUCCESS'),
    }))
  }

  return (
    <aside className="diagnosis-studio-all-runs panel" aria-labelledby="all-runs-title">
      <header className="diagnosis-studio-panel-header">
        <div>
          <span className="diagnosis-studio-section-number">1.</span>
          <h2 id="all-runs-title">{ui('All Runs')}</h2>
        </div>
        <span className="diagnosis-studio-count">{totalRuns}</span>
      </header>

      <div className="diagnosis-studio-run-toolbar">
        <label className="diagnosis-studio-search">
          <Search size={15} strokeWidth={1.8} />
          <span className="sr-only">{ui('Search runs')}</span>
          <input
            aria-label={ui('Search runs')}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={ui('Search runs...')}
            value={query}
          />
        </label>
        <div className="diagnosis-studio-filter-row" role="group" aria-label={ui('Diagnosis filters')}>
          {filterOptions.map((option) => {
            const diagnosedFilterUnavailable = option.value === 'DIAGNOSED' && diagnosedRunIds.size === 0
            return (
              <button
                aria-pressed={filter === option.value}
                className={`diagnosis-studio-filter${filter === option.value ? ' is-active' : ''}`}
                disabled={diagnosedFilterUnavailable}
                key={option.value}
                onClick={() => onFilterChange(option.value)}
                title={diagnosedFilterUnavailable ? ui('No diagnosis is known in this Console session yet.') : undefined}
                type="button"
              >
                {ui(option.label)}
              </button>
            )
          })}
        </div>
        <label className="diagnosis-studio-group-select">
          <Filter size={14} strokeWidth={1.8} />
          <span>{ui('Group by')}:</span>
          <select aria-label={ui('Group by')} disabled value="failureType" onChange={() => undefined}>
            <option value="failureType">{ui('Failure Type')}</option>
          </select>
          <ChevronDown size={14} strokeWidth={1.8} />
        </label>
      </div>

      <div className="diagnosis-studio-run-list" aria-label={ui('Runs list')}>
        {groupedRuns.length ? groupedRuns.map((group) => {
          const expanded = expandedGroups[group.status] ?? group.status !== 'SUCCESS'
          const groupKey = group.status.toLowerCase()
          return (
            <section className={`diagnosis-studio-run-group diagnosis-studio-run-group-${groupKey}`} key={group.status}>
              <button
                aria-expanded={expanded}
                className="diagnosis-studio-run-group-heading"
                onClick={() => toggleGroup(group.status)}
                type="button"
              >
                <ChevronDown className={expanded ? 'is-expanded' : undefined} size={13} strokeWidth={1.8} />
                <span className="diagnosis-studio-group-dot" />
                <strong>{ui(group.status)}</strong>
                <span>({group.runs.length})</span>
              </button>
              {expanded ? (
                <div className="diagnosis-studio-run-group-items">
                  {group.runs.map((run) => (
                    <div
                      aria-pressed={run.runId === selectedRunId}
                      className={`diagnosis-studio-run-row${run.runId === selectedRunId ? ' is-selected' : ''}`}
                      key={run.runId}
                      onClick={() => onSelect(run.runId)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          onSelect(run.runId)
                        }
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="diagnosis-studio-run-row-topline">
                        <strong>#{run.runId}</strong>
                        <RunStatusBadge status={run.status} />
                        <span>{formatTime(run.startedAt ?? run.createdAt, locale)}</span>
                        <ChevronRight size={14} strokeWidth={1.8} />
                      </div>
                      <div className="diagnosis-studio-run-row-title">
                        <strong>{run.testCaseName}</strong>
                        <span>{run.caseId}</span>
                      </div>
                      <div className="diagnosis-studio-run-row-meta">
                        <span>{run.apiId}</span>
                        <code>{runFailureLabel(run)}</code>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          )
        }) : (
          <div className="diagnosis-studio-runs-empty">{totalRuns ? ui('No runs match the current filters.') : ui('No executions')}</div>
        )}
      </div>

      <footer className="diagnosis-studio-run-footer">
        {runs.length} {ui('of')} {totalRuns} {ui('runs')}
      </footer>
    </aside>
  )
}

export function DiagnosisAgentExecutionPage({
  initialRunId,
  onClose,
  onViewResult,
  onViewRunReport,
  returnTo,
}: DiagnosisAgentExecutionPageProps) {
  const { t, ui } = useConsoleLanguage()
  const { expireSession } = useAuth()
  const { activateContext, diagnoses, recordDiagnosis, recordReport, recordRun } = useContextTrail()
  const { currentProject, refreshProjects } = useProject()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [runsState, setRunsState] = useState<LoadState>('loading')
  const [runsError, setRunsError] = useState<ApiError | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<number | null>(parseRunId(initialRunId))
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StudioFilter>('ALL')
  const [testReport, setTestReport] = useState<TestReport | null>(null)
  const [reportError, setReportError] = useState<ApiError | null>(null)
  const [execution, setExecution] = useState<DiagnosisExecutionResponse | null>(null)
  const [runtime, setRuntime] = useState<DiagnosisRuntime>('PYTHON_AGENTLAB')
  const [actionState, setActionState] = useState<ActionState>('idle')
  const [editedArguments, setEditedArguments] = useState('{}')
  const [isEditing, setIsEditing] = useState(false)
  const [notice, setNotice] = useState('')
  const selectedRunIdRef = useRef<number | null>(parseRunId(initialRunId))
  const selectionVersionRef = useRef(0)
  const runtimeRef = useRef<DiagnosisRuntime>('PYTHON_AGENTLAB')
  const runtimeVersionRef = useRef(0)

  const projectId = currentProject?.projectId ?? null
  const selectedRun = runs.find((run) => run.runId === selectedRunId) ?? null
  const diagnosedRunIds = useMemo(
    () => new Set(diagnoses.map((diagnosis) => diagnosis.runId)),
    [diagnoses],
  )

  const handleApiFailure = useCallback((error: unknown, fallback: string) => {
    const apiError = asApiError(error, fallback)
    if (apiError.status === 401) expireSession()
    if (apiError.status === 403) void refreshProjects()
    return apiError
  }, [expireSession, refreshProjects])

  const fetchRuns = useCallback(async (nextProjectId: string, signal?: AbortSignal) => {
    const response = await apiFetch<RunSummary[]>(`/api/v1/projects/${encodeURIComponent(nextProjectId)}/test-runs`, { signal })
    return response.map(normalizeRunSummary)
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

  const rememberExecution = useCallback((nextExecution: DiagnosisExecutionResponse) => {
    const diagnosisTarget = {
      agentRunId: nextExecution.agentRunId,
      id: nextExecution.agentRunId,
      runId: nextExecution.runId,
      type: 'diagnosis' as const,
    }
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
    } else {
      activateContext(diagnosisTarget)
    }
  }, [activateContext, recordDiagnosis, recordReport])

  useEffect(() => {
    let cancelled = false
    selectionVersionRef.current += 1
    selectedRunIdRef.current = null
    setRuns([])
    setSelectedRunId(null)
    setTestReport(null)
    setExecution(null)
    setRunsError(null)
    setReportError(null)
    setNotice('')
    setQuery('')
    setFilter('ALL')

    if (!projectId) {
      setRunsState('ready')
      return () => { cancelled = true }
    }

    setRunsState('loading')
    const controller = new AbortController()
    void fetchRuns(projectId, controller.signal)
      .then((nextRuns) => {
        if (cancelled) return
        rememberRuns(nextRuns)
        const preferredId = parseRunId(initialRunId)
        const preferred = preferredId === null ? null : nextRuns.find((run) => run.runId === preferredId) ?? null
        const firstDiagnosable = nextRuns.find((run) => isDiagnosableStatus(run.status))
        const nextSelectedRun = preferred ?? firstDiagnosable ?? nextRuns[0] ?? null
        setRuns(nextRuns)
        selectionVersionRef.current += 1
        selectedRunIdRef.current = nextSelectedRun?.runId ?? null
        setSelectedRunId(nextSelectedRun?.runId ?? null)
        if (nextSelectedRun) {
          activateContext({
            type: 'run',
            id: String(nextSelectedRun.runId),
            runId: nextSelectedRun.runId,
            caseId: nextSelectedRun.caseId,
            apiId: nextSelectedRun.apiId,
          })
        }
        setRunsState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        setRunsError(handleApiFailure(error, 'Unable to load Java Runner executions'))
        setRunsState('error')
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [activateContext, fetchRuns, handleApiFailure, initialRunId, projectId, rememberRuns])

  useEffect(() => {
    let cancelled = false
    setTestReport(null)
    setReportError(null)
    setExecution(null)
    setNotice('')
    setIsEditing(false)
    setEditedArguments('{}')

    if (!projectId || !selectedRun) return () => { cancelled = true }

    const controller = new AbortController()
    void apiFetch<TestReport>(`/api/v1/projects/${encodeURIComponent(projectId)}/test-runs/${selectedRun.runId}/report`, { signal: controller.signal })
      .then((report) => {
        if (!cancelled) setTestReport(report)
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        setReportError(handleApiFailure(error, 'Unable to load Java TestReport'))
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [handleApiFailure, projectId, selectedRun?.runId])

  const selectRun = (runId: number) => {
    selectionVersionRef.current += 1
    selectedRunIdRef.current = runId
    setSelectedRunId(runId)
    setTestReport(null)
    setReportError(null)
    setExecution(null)
    setNotice('')
    setIsEditing(false)
    setEditedArguments('{}')
    setActionState('idle')
    const nextRun = runs.find((run) => run.runId === runId)
    if (nextRun) {
      activateContext({
        type: 'run',
        id: String(nextRun.runId),
        runId: nextRun.runId,
        caseId: nextRun.caseId,
        apiId: nextRun.apiId,
      })
    }
  }

  const startDiagnosis = async () => {
    if (!projectId || !selectedRun || runtime !== 'PYTHON_AGENTLAB' || !isDiagnosableStatus(selectedRun.status) || actionState !== 'idle') return
    if (execution && !['FAILED', 'REJECTED'].includes(execution.status)) return

    const requestRunId = selectedRun.runId
    const requestSelectionVersion = selectionVersionRef.current
    const requestRuntimeVersion = runtimeVersionRef.current
    setActionState('starting')
    setNotice('Calling the real Python Diagnosis Workflow…')
    try {
      const nextExecution = await agentApiFetch<DiagnosisExecutionResponse>('/api/v1/diagnosis/runs', {
        body: JSON.stringify({ projectId: Number(projectId), runId: selectedRun.runId }),
        method: 'POST',
      })
      if (selectedRunIdRef.current !== requestRunId || selectionVersionRef.current !== requestSelectionVersion || runtimeRef.current !== 'PYTHON_AGENTLAB' || runtimeVersionRef.current !== requestRuntimeVersion) return
      setExecution(nextExecution)
      rememberExecution(nextExecution)
      setEditedArguments(JSON.stringify(nextExecution.approvalRequest?.arguments ?? {}, null, 2))
      setIsEditing(false)
      setNotice(nextExecution.status === 'APPROVAL_REQUIRED' ? 'Guardrails paused the real workflow for human approval.' : 'The real DiagnosisReport is ready.')
    } catch (error: unknown) {
      const apiError = handleApiFailure(error, 'Unable to start the Python diagnosis workflow')
      if (selectedRunIdRef.current === requestRunId && selectionVersionRef.current === requestSelectionVersion && runtimeVersionRef.current === requestRuntimeVersion) {
        setNotice(`${apiError.code}: ${apiError.message}`)
      }
    } finally {
      if (selectionVersionRef.current === requestSelectionVersion && runtimeVersionRef.current === requestRuntimeVersion) setActionState('idle')
    }
  }

  const resumeDiagnosis = async (decision: 'APPROVE' | 'EDIT' | 'REJECT') => {
    if (runtime !== 'PYTHON_AGENTLAB' || !execution || actionState !== 'idle') return
    const requestRunId = execution.runId
    const requestSelectionVersion = selectionVersionRef.current
    const requestRuntimeVersion = runtimeVersionRef.current
    let parsedArguments: Record<string, unknown> | undefined
    if (decision === 'EDIT') {
      try {
        const value: unknown = JSON.parse(editedArguments)
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Arguments must be a JSON object')
        parsedArguments = value as Record<string, unknown>
      } catch {
        setNotice('Edited arguments must be a valid JSON object.')
        return
      }
    }
    setActionState('resuming')
    setNotice(`Submitting ${decision} to the existing HITL workflow…`)
    try {
      const nextExecution = await agentApiFetch<DiagnosisExecutionResponse>(`/api/v1/diagnosis/runs/${encodeURIComponent(execution.agentRunId)}/resume`, {
        body: JSON.stringify({ decision, ...(parsedArguments ? { editedArguments: parsedArguments } : {}) }),
        method: 'POST',
      })
      if (selectedRunIdRef.current !== requestRunId || selectionVersionRef.current !== requestSelectionVersion || runtimeRef.current !== 'PYTHON_AGENTLAB' || runtimeVersionRef.current !== requestRuntimeVersion) return
      setExecution(nextExecution)
      rememberExecution(nextExecution)
      setEditedArguments(JSON.stringify(nextExecution.approvalRequest?.arguments ?? parsedArguments ?? {}, null, 2))
      setIsEditing(false)
      setNotice(nextExecution.status === 'COMPLETED' ? 'The real DiagnosisReport is ready.' : `Workflow status: ${nextExecution.status}`)
    } catch (error: unknown) {
      const apiError = handleApiFailure(error, 'Unable to resume the Python diagnosis workflow')
      if (selectedRunIdRef.current === requestRunId && selectionVersionRef.current === requestSelectionVersion && runtimeVersionRef.current === requestRuntimeVersion) {
        setNotice(`${apiError.code}: ${apiError.message}`)
      }
    } finally {
      if (selectionVersionRef.current === requestSelectionVersion && runtimeVersionRef.current === requestRuntimeVersion) setActionState('idle')
    }
  }

  const handleRuntimeChange = (nextRuntime: DiagnosisRuntime) => {
    runtimeRef.current = nextRuntime
    runtimeVersionRef.current += 1
    setRuntime(nextRuntime)
  }

  const handleTrailNavigation = (target: ContextTrailTarget) => {
    if (target.type === 'run') {
      selectRun(target.runId)
      return
    }
    if (target.type === 'diagnosis') {
      onViewResult(target.agentRunId)
      return
    }
    if (target.type === 'report') onViewResult(target.agentRunId)
  }

  const visibleRuns = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return runs.filter((run) => {
      const searchable = `${run.runId} ${run.caseId} ${run.apiId} ${run.testCaseName} ${run.status} ${run.failureType ?? ''}`.toLowerCase()
      return (!normalizedQuery || searchable.includes(normalizedQuery)) && filterMatches(run, filter, diagnosedRunIds)
    })
  }, [diagnosedRunIds, filter, query, runs])

  const canStartDiagnosis = Boolean(
    selectedRun
    && isDiagnosableStatus(selectedRun.status)
    && runtime === 'PYTHON_AGENTLAB'
    && actionState === 'idle'
    && (!execution || execution.status === 'FAILED' || execution.status === 'REJECTED'),
  )
  const reportStatus = reportError ? 'error' : testReport ? 'ready' : selectedRun ? 'loading' : 'idle'
  const layoutClass = runtime === 'PYTHON_AGENTLAB' ? 'diagnosis-studio-layout--python' : 'diagnosis-studio-layout--java'

  return (
    <section className="diagnosis-execution-page" aria-label={t('page.diagnosisStudio.title')}>
      {returnTo && onClose ? (
        <div className="diagnosis-studio-toolbar">
          <button className="panel-action" onClick={onClose} type="button">{ui('Back to')} {returnTo === 'Runs' ? t('nav.runs') : t('nav.diagnosis')}</button>
        </div>
      ) : null}

      {runsState === 'loading' ? <PageState description="Reading persisted executions from Java Platform." kind="loading" title="Loading runs" /> : null}
      {runsState === 'error' ? (
        <PageState
          actionLabel={t('common.retry')}
          description={runsError?.message ?? 'Java Runner executions are unavailable.'}
          kind="error"
          onAction={() => {
            if (!projectId) return
            setRunsState('loading')
            void fetchRuns(projectId)
              .then((nextRuns) => {
                rememberRuns(nextRuns)
                setRuns(nextRuns)
                const preferredId = parseRunId(initialRunId)
                const preferred = preferredId === null ? null : nextRuns.find((run) => run.runId === preferredId) ?? null
                const nextSelectedRun = preferred ?? nextRuns.find((run) => isDiagnosableStatus(run.status)) ?? nextRuns[0] ?? null
                selectionVersionRef.current += 1
                selectedRunIdRef.current = nextSelectedRun?.runId ?? null
                setSelectedRunId(nextSelectedRun?.runId ?? null)
                setRunsState('ready')
              })
              .catch((error: unknown) => {
                setRunsError(handleApiFailure(error, 'Unable to load Java Runner executions'))
                setRunsState('error')
              })
          }}
          title="Runs unavailable"
        />
      ) : null}
      {runsState === 'ready' && !runs.length ? <PageState description="Java Platform returned no persisted executions for this project." kind="empty" title="No executions" /> : null}

      {runsState === 'ready' && runs.length > 0 ? (
        <div className={`diagnosis-studio-layout ${layoutClass}`}>
          <AllRunsPanel
            diagnosedRunIds={diagnosedRunIds}
            filter={filter}
            onFilterChange={setFilter}
            onQueryChange={setQuery}
            onSelect={selectRun}
            query={query}
            runs={visibleRuns}
            selectedRunId={selectedRunId}
            totalRuns={runs.length}
          />

          <div className="diagnosis-studio-main-column">
            <section className="diagnosis-studio-selective panel" aria-labelledby="selective-execution-title">
              <header className="diagnosis-studio-panel-header">
                <div>
                  <span className="diagnosis-studio-section-number">2.</span>
                  <h2 id="selective-execution-title">{ui('Selective Execution')}</h2>
                </div>
              </header>

              {selectedRun ? (
                <>
                  <div className="diagnosis-studio-selected-summary">
                    <div><span>{ui('Run ID')}</span><strong>#{selectedRun.runId}</strong></div>
                    <div><span>{ui('TestCase')}</span><strong>{selectedRun.testCaseName}<small>{selectedRun.caseId}</small></strong></div>
                    <div><span>{ui('API')}</span><strong>{selectedRun.apiId}</strong></div>
                    <div><span>{ui('Failure Type')}</span><code>{runFailureLabel(selectedRun)}</code></div>
                    <div><span>{ui('Java Report')}</span><strong className="diagnosis-studio-report-value">{reportStatus === 'loading' ? ui('Loading TestReport') : reportStatus === 'error' ? ui('Report unavailable') : testReport ? testReport.reportId : '—'}</strong></div>
                    <div><span>{ui('Current State')}</span><strong className={isDiagnosableStatus(selectedRun.status) ? 'is-ready' : 'is-unavailable'}>{isDiagnosableStatus(selectedRun.status) ? ui('Ready to diagnose') : ui(selectedRun.status)}</strong></div>
                  </div>

                  <DiagnosisRuntimeSelector
                    execution={runtime === 'PYTHON_AGENTLAB' ? execution : null}
                    onChange={handleRuntimeChange}
                    runtime={runtime}
                  />

                  <div className="diagnosis-studio-action-row">
                    <button
                      className="diagnosis-execution-primary-button"
                      disabled={!canStartDiagnosis}
                      onClick={() => { void startDiagnosis() }}
                      type="button"
                    >
                      {actionState === 'starting' ? ui('Starting Diagnosis…') : ui('Start Diagnosis')}
                    </button>
                    <button
                      className="diagnosis-execution-secondary-button"
                      disabled={!onViewRunReport}
                      onClick={() => { if (onViewRunReport) onViewRunReport(selectedRun.runId) }}
                      type="button"
                    >
                      <FileCheck2 size={15} strokeWidth={1.8} /> {ui('View Run Report')}
                    </button>
                  </div>
                  <div className={`diagnosis-studio-action-note${runtime === 'JAVA_PLATFORM' ? ' is-warning' : ''}`} role="status">
                    {runtime === 'JAVA_PLATFORM'
                      ? ui('Java Platform browser diagnosis is not wired. No diagnosis request will be sent.')
                      : !isDiagnosableStatus(selectedRun.status)
                        ? ui('Start Diagnosis is available only for failed or timed-out runs.')
                        : execution?.status === 'APPROVAL_REQUIRED'
                          ? ui('The Python workflow is paused for human approval.')
                          : notice || ui('Python AgentLab is ready to run against this Java TestReport.')}
                  </div>
                </>
              ) : (
                <div className="diagnosis-studio-selection-empty">{ui('Select a run from All Runs to inspect its execution evidence.')}</div>
              )}
            </section>

            <ExecutionEvidence
              execution={execution}
              projectId={projectId}
              run={selectedRun}
              runtime={runtime}
              testReport={testReport}
            />
          </div>

          <div className="diagnosis-studio-control-column">
            <HumanApprovalPanel
              busy={actionState === 'resuming'}
              editedArguments={editedArguments}
              execution={runtime === 'PYTHON_AGENTLAB' ? execution : null}
              isEditing={isEditing}
              notice=""
              onApprove={() => { void resumeDiagnosis(isEditing ? 'EDIT' : 'APPROVE') }}
              onArgumentsChange={setEditedArguments}
              onEdit={() => setIsEditing(true)}
              onReject={() => { void resumeDiagnosis('REJECT') }}
              onViewResult={() => { if (execution) onViewResult(execution.agentRunId) }}
              runtime={runtime}
            />
            <DiagnosisWorkflowProgress
              runtime={runtime}
              runtimeLabel={runtime === 'PYTHON_AGENTLAB' ? execution?.workflow : undefined}
              steps={runtime === 'PYTHON_AGENTLAB' ? execution?.steps ?? [] : []}
            />
          </div>

          <ContextTrail
            compact
            onNavigate={handleTrailNavigation}
            visibleGroups={['endpoint', 'testcase', 'run', 'diagnosis', 'report']}
          />
        </div>
      ) : null}
    </section>
  )
}
