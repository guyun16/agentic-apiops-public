import type { DiagnosisRunSummary } from '../diagnosis/types'

// An unfinished workflow takes priority over newer terminal attempts.
export function findRecoverableDiagnosis(history: readonly DiagnosisRunSummary[], projectId: string, runId: number) {
  const matches = history.filter((item) => String(item.projectId) === projectId && item.runId === runId)
  const active = matches.filter((item) => item.status === 'RUNNING' || item.status === 'APPROVAL_REQUIRED')
  return [...(active.length ? active : matches)].sort((a, b) =>
    Date.parse(b.createdAt) - Date.parse(a.createdAt) || b.agentRunId.localeCompare(a.agentRunId),
  )[0] ?? null
}
