import type { ContextTrailEndpoint, ContextTrailTarget } from '../../app/ContextTrailContext'
import type { RunSummary } from '../runs/types'
import type {
  EvaluationRunFilter,
  RuntimeMetric,
  RuntimeMetricStatus,
  RuntimeRunDetail,
  RuntimeRunStatus,
  RuntimeRunSummary,
} from './types'

export const evaluationRunFilters: ReadonlyArray<{ id: EvaluationRunFilter; label: string }> = [
  { id: 'ALL', label: 'All' },
  { id: 'COMPLETED', label: 'Completed' },
  { id: 'RUNNING', label: 'Running' },
  { id: 'APPROVAL_REQUIRED', label: 'Approval Required' },
  { id: 'FAILED', label: 'Failed' },
  { id: 'REJECTED', label: 'Rejected' },
]

export function formatMetricStatus(status: RuntimeMetricStatus | undefined) {
  return status === 'NOT_APPLICABLE' ? 'N/A' : status ?? 'UNKNOWN'
}

export function formatRuntimeMetric(metric: RuntimeMetric | undefined, options: { compactDuration?: boolean; percentage?: boolean } = {}) {
  if (!metric || metric.status !== 'VALUE' || metric.value === null) return formatMetricStatus(metric?.status)
  if (options.percentage) return `${(metric.value * 100).toFixed(0)}%`
  if (options.compactDuration && metric.unit === 'ms') {
    return metric.value >= 1000 ? `${(metric.value / 1000).toFixed(2)} s` : `${Math.round(metric.value)} ms`
  }
  const rendered = Number.isInteger(metric.value) ? metric.value.toLocaleString() : metric.value.toFixed(1)
  return metric.unit ? `${rendered} ${metric.unit}` : rendered
}

export function filterRuntimeRuns(runs: RuntimeRunSummary[], filter: EvaluationRunFilter, query: string) {
  const normalizedQuery = query.trim().toLowerCase()
  return runs.filter((run) => {
    const searchText = [
      run.agentRunId,
      run.traceId,
      run.executionType,
      run.status,
      run.provider,
      run.model,
      run.apiId ?? '',
      run.runId ?? '',
      run.reportId ?? '',
    ].join(' ').toLowerCase()
    return (filter === 'ALL' || run.status === filter) && (!normalizedQuery || searchText.includes(normalizedQuery))
  })
}

export function countRuntimeRuns(runs: RuntimeRunSummary[]) {
  const counts: Record<EvaluationRunFilter, number> = {
    ALL: runs.length,
    COMPLETED: 0,
    RUNNING: 0,
    APPROVAL_REQUIRED: 0,
    FAILED: 0,
    REJECTED: 0,
  }
  runs.forEach((run) => { counts[run.status] += 1 })
  return counts
}

export function resolveSelectedRunId(
  currentId: string | null,
  visibleRuns: RuntimeRunSummary[],
) {
  if (visibleRuns.some((run) => run.agentRunId === currentId)) return currentId
  if (visibleRuns.length > 0) return visibleRuns[0].agentRunId
  return null
}

export function selectedRuntimeRun(detail: RuntimeRunDetail | null, selectedRunId: string | null) {
  return detail?.agentRunId === selectedRunId ? detail : null
}

export function evaluationCoverage(detail: RuntimeRunDetail) {
  return {
    deterministic: detail.evaluationResult
      ? { label: 'AVAILABLE', reason: `EvaluationResult ${detail.evaluationResult.evaluation_id}`, tone: 'success' as const }
      : { label: 'NOT EVALUATED', reason: 'Ground Truth unavailable', tone: 'neutral' as const },
    judge: detail.judgeResults.length > 0
      ? { label: 'AVAILABLE', reason: `${detail.judgeResults.length} persisted JudgeResult`, tone: 'success' as const }
      : { label: 'NOT EVALUATED', reason: 'No persisted JudgeResult', tone: 'neutral' as const },
  }
}

export function resolveRuntimeEndpoint(
  runApiId: string | number,
  endpoints: ContextTrailEndpoint[],
) {
  const sourceValue = String(runApiId)
  const uniqueEndpoints = endpoints.filter((endpoint, index, items) => (
    items.findIndex((item) => item.id === endpoint.id && item.apiDocId === endpoint.apiDocId) === index
  ))
  const canonicalMatches = uniqueEndpoints.filter((endpoint) => endpoint.id === sourceValue)
  if (canonicalMatches.length === 1) return canonicalMatches[0]
  if (canonicalMatches.length > 1) return null

  const operationMatches = uniqueEndpoints.filter((endpoint) => endpoint.operationId === sourceValue)
  return operationMatches.length === 1 ? operationMatches[0] : null
}

export function validationSummary(detail: RuntimeRunDetail) {
  const metrics = ['validJson', 'schemaValid', 'contractAccepted'].map((key) => detail.metrics[key])
  const counts = metrics.reduce<Record<RuntimeMetricStatus, number>>((result, metric) => {
    result[metric?.status ?? 'UNKNOWN'] += 1
    return result
  }, { VALUE: 0, NOT_APPLICABLE: 0, UNKNOWN: 0, ERROR: 0 })

  if (counts.ERROR > 0) return { label: 'ERROR', note: `${counts.ERROR} validation fact error`, tone: 'danger' as const }
  if (counts.NOT_APPLICABLE === metrics.length) return { label: 'N/A', note: 'Not applicable to this execution type', tone: 'neutral' as const }
  if (counts.UNKNOWN > 0) return { label: 'UNKNOWN', note: `${counts.UNKNOWN} validation fact unavailable`, tone: 'warning' as const }
  const passed = metrics.filter((metric) => metric?.value === 1).length
  const failed = metrics.filter((metric) => metric?.status === 'VALUE' && metric.value !== 1).length
  return {
    label: `${passed} / ${metrics.length} PASS`,
    note: failed > 0 ? `${failed} validation fact failed` : 'All validation facts passed',
    tone: failed > 0 ? 'danger' as const : 'success' as const,
  }
}

export function runtimeNavigation(run: RuntimeRunSummary) {
  return {
    diagnosisAgentRunId: run.executionType === 'DIAGNOSIS' && run.runId !== null ? run.agentRunId : null,
    runId: run.runId,
    traceId: run.traceId || null,
  }
}

export function runtimeContextTarget(
  detail: RuntimeRunDetail,
  owningRun: RunSummary | null,
): ContextTrailTarget | null {
  if (detail.executionType !== 'DIAGNOSIS' || detail.runId === null || !owningRun || owningRun.runId !== detail.runId) return null
  if (detail.reportId) {
    return {
      type: 'report',
      id: detail.reportId,
      reportId: detail.reportId,
      agentRunId: detail.agentRunId,
      runId: detail.runId,
    }
  }
  return {
    type: 'diagnosis',
    id: detail.agentRunId,
    agentRunId: detail.agentRunId,
    runId: detail.runId,
  }
}

export function statusTone(status: RuntimeRunStatus | RuntimeMetricStatus) {
  if (status === 'COMPLETED' || status === 'VALUE') return 'success'
  if (status === 'RUNNING') return 'accent'
  if (status === 'APPROVAL_REQUIRED' || status === 'UNKNOWN') return 'warning'
  if (status === 'NOT_APPLICABLE') return 'neutral'
  return 'danger'
}
