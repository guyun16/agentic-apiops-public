import type { BenchmarkConfigurationValue, BenchmarkMetric, BenchmarkRunDetail, BenchmarkTask } from './types'

export type SnapshotIdentity = {
  sourceEvaluationRunId: string
  evaluationRunId: string
  detail: { evaluationRunId: string }
  tasks: { evaluationRunId: string }[]
}

export function snapshotForEvaluationRun<T extends SnapshotIdentity>(report: T, selectedEvaluationRunId: string): T | null {
  if (report.sourceEvaluationRunId !== selectedEvaluationRunId) return null
  if (report.evaluationRunId !== report.sourceEvaluationRunId) return null
  if (report.detail.evaluationRunId !== report.sourceEvaluationRunId) return null
  if (report.tasks.some(task => task.evaluationRunId !== report.sourceEvaluationRunId)) return null
  return report
}

export const categories: Record<string, string> = {
  TESTCASE_GENERATION: 'TestCase Generation',
  FAILURE_DIAGNOSIS: 'Failure Diagnosis',
  TOOL_SAFETY: 'Tool Safety',
  RAG_EVIDENCE_RETRIEVAL: 'RAG Evidence Retrieval',
  E2E_APIOPS: 'End-to-End APIOps',
}

export function configurationText(field: BenchmarkConfigurationValue): string {
  if (field.availability !== 'AVAILABLE') return field.availability
  if (field.value == null) return 'MISSING'
  return typeof field.value === 'string' ? field.value : JSON.stringify(field.value)
}

export function configurationSummary(field: BenchmarkConfigurationValue): string {
  if (field.availability !== 'AVAILABLE' || field.value === null || typeof field.value !== 'object') return configurationText(field)
  const value = field.value as Record<string, unknown>
  const parts = typeof value.model === 'string'
    ? [value.provider, value.model]
    : [value.name, value.version]
  const summary = parts.filter((part): part is string => typeof part === 'string' && part.length > 0).join(' · ')
  return summary || configurationText(field)
}

export function formatMetric(metric?: BenchmarkMetric): string {
  if (!metric) return 'MISSING'
  if (metric.state !== 'VALUE') return metric.state === 'NOT_APPLICABLE' ? 'N/A' : metric.state
  if (metric.rate != null) return percent(metric.rate)
  if (metric.value == null) return 'MISSING'
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(metric.value) + (metric.unit ? ` ${metric.unit}` : '')
}

export function percent(value: number | null) {
  return value === null ? 'MISSING' : `${(value * 100).toFixed(1)}%`
}

export function outcome(task: BenchmarkTask): string {
  return task.formalOutcome?.status ?? task.taskSuccess?.status ?? 'MISSING'
}

export function filterTasks(tasks: BenchmarkTask[], query: string, category: string, result: string) {
  const search = query.trim().toLowerCase()
  return tasks.filter(task => (category === 'ALL' || task.taskType === category)
    && (result === 'ALL' || outcome(task) === result)
    && (!search || [task.benchmarkTaskId, task.caseId, task.failureReason ?? '', task.taskType].join(' ').toLowerCase().includes(search)))
}

export function categoryRows(tasks: BenchmarkTask[], executedTaskCount: number) {
  const complete = tasks.length === executedTaskCount
  return [...new Set([...Object.keys(categories), ...tasks.map(task => task.taskType)])].map(type => {
    const members = tasks.filter(task => task.taskType === type)
    const counts: Record<string, number> = {}
    for (const task of members) counts[outcome(task)] = (counts[outcome(task)] ?? 0) + 1
    return { type, label: categories[type] ?? type, recognized: type in categories, complete, count: members.length, counts }
  })
}

// This API exposes no comparison compatibility record. Artifact references alone
// are not evidence that a second run is a comparable baseline.
export function comparisonView(detail: BenchmarkRunDetail) {
  return { available: false as const, metrics: detail.aggregateMetrics.filter(metric =>
    metric.state === 'VALUE' && metric.rate !== null && metric.rate >= 0 && metric.rate <= 1) }
}

export function isCurrentResult(signal: AbortSignal, runId: string, detail: BenchmarkRunDetail, tasks: BenchmarkTask[]) {
  return !signal.aborted && detail.evaluationRunId === runId && tasks.every(task => task.evaluationRunId === runId)
}

export function failureGroups(tasks: BenchmarkTask[]) {
  return [
    { title: 'Formal FAIL', tone: 'fail', members: tasks.filter(task => outcome(task) === 'FAIL') },
    { title: 'UNKNOWN / Uncertain', tone: 'unknown', members: tasks.filter(task => outcome(task) === 'UNKNOWN') },
    { title: 'Other outcomes / Execution exceptions', tone: 'neutral', members: tasks.filter(task => !['FAIL', 'UNKNOWN'].includes(outcome(task)) && (task.status !== 'SUCCESS' || outcome(task) === 'MISSING')) },
  ]
}

// Result distribution only: preserves every outcome and never recomputes a metric.
export function categoryDistribution(row: ReturnType<typeof categoryRows>[number]) {
  if (!row.complete) return []
  const statuses = [...new Set(['PASS', 'FAIL', 'UNKNOWN', ...Object.keys(row.counts)])]
  return statuses.map(status => ({ status, label: status === 'NOT_APPLICABLE' ? 'N/A' : status, count: row.counts[status] ?? 0, width: row.count > 0 ? (row.counts[status] ?? 0) / row.count * 100 : 0 }))
}
