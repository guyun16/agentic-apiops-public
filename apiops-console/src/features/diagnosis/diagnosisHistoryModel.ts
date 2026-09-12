import type { DiagnosisHistoryFilter, DiagnosisRunSummary } from './types'

export function diagnosisHistoryPath(projectId: number | string) {
  return `/api/v1/diagnosis/runs?projectId=${encodeURIComponent(projectId)}`
}

function historySearchText(run: DiagnosisRunSummary) {
  return [
    run.agentRunId,
    run.traceId,
    run.status,
    run.provider,
    run.model,
    run.projectId,
    run.apiId,
    run.runId,
    run.reportId,
    run.diagnosisReportId,
    run.summary,
  ].filter((value) => value !== null && value !== undefined).join(' ').toLowerCase()
}

export function sortDiagnosisHistory(runs: readonly DiagnosisRunSummary[]) {
  return [...runs].sort((left, right) => {
    const timestampDifference = Date.parse(right.updatedAt) - Date.parse(left.updatedAt)
    return timestampDifference || right.agentRunId.localeCompare(left.agentRunId)
  })
}

export function filterDiagnosisHistory(
  runs: readonly DiagnosisRunSummary[],
  filter: DiagnosisHistoryFilter,
  query: string,
) {
  const normalizedQuery = query.trim().toLowerCase()
  return runs.filter((run) => {
    const matchesFilter = filter === 'ALL' || run.status === filter
    return matchesFilter && (!normalizedQuery || historySearchText(run).includes(normalizedQuery))
  })
}

export function resolveDiagnosisSelection(
  preferredAgentRunId: string | null | undefined,
  runs: readonly DiagnosisRunSummary[],
) {
  if (preferredAgentRunId && runs.some((run) => run.agentRunId === preferredAgentRunId)) {
    return preferredAgentRunId
  }
  return runs[0]?.agentRunId ?? null
}
