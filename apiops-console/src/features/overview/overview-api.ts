import { agentApiFetch, apiFetch, ApiError, rawAgentApiFetch, rawApiFetch } from '../../lib/api-client'
import type { RuntimeRunSummary } from '../evaluation/types'
import type { DiagnosisExecutionResponse } from '../diagnosis/types'
import type { RunSummary } from '../runs/types'
import type { HealthItem, HealthItemId, HealthStatus, RecentDiagnosis } from './types'

type RunSummaryResponse = Omit<RunSummary, 'runId' | 'durationMs'> & {
  runId: number | string
  durationMs: number | string | null
}

type JsonRecord = Record<string, unknown>

function asRecord(value: unknown): JsonRecord | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : null
}

function asString(value: unknown) {
  return typeof value === 'string' ? value : null
}

/** Map only source statuses that the Overview is allowed to display. */
export function mapHealthStatus(value: unknown): HealthStatus {
  const status = asString(value)?.trim().toUpperCase()

  switch (status) {
    case 'UP':
      return 'UP'
    case 'DOWN':
    case 'OUT_OF_SERVICE':
      return 'DOWN'
    case 'DEGRADED':
      return 'DEGRADED'
    case 'UNKNOWN':
      return 'UNKNOWN'
    default:
      return 'UNKNOWN'
  }
}

function item(
  id: HealthItemId,
  name: string,
  status: HealthStatus,
  source: string,
  sourceAvailable = true,
  checkedAt: string | null = null,
): HealthItem {
  return { checkedAt, id, name, source, sourceAvailable, status }
}

export function unavailableHealthItem(id: HealthItemId, name: string, source: string, checkedAt: string | null = null) {
  return item(id, name, 'UNKNOWN', source, false, checkedAt)
}

/** Convert the raw Java actuator payload into the Java-owned platform status only. */
export function parseJavaHealth(payload: unknown, checkedAt = new Date().toISOString()): HealthItem {
  const root = asRecord(payload)
  return item('java', 'Java Platform', mapHealthStatus(root?.status), 'Java /actuator/health', true, checkedAt)
}

/** Python AgentLab exposes status=ok; that successful source maps to canonical UP. */
export function parsePythonHealth(payload: unknown, checkedAt = new Date().toISOString()): HealthItem {
  const root = asRecord(payload)
  const sourceStatus = root?.status === 'ok' ? 'UP' : root?.status
  return item('python', 'Python AgentLab', mapHealthStatus(sourceStatus), 'Python /health', true, checkedAt)
}

export async function fetchJavaHealth(signal?: AbortSignal) {
  // Spring Boot returns 503 with a useful JSON body when actuator status is DOWN.
  const payload = await rawApiFetch<unknown>('/actuator/health', {
    allowHttpStatuses: [503],
    signal,
  })
  return parseJavaHealth(payload)
}

export async function fetchPythonHealth(signal?: AbortSignal) {
  const payload = await rawAgentApiFetch<unknown>('/health', { signal })
  return parsePythonHealth(payload)
}

export async function fetchRecentJavaRuns(projectId: string, signal?: AbortSignal) {
  const response = await apiFetch<RunSummaryResponse[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/test-runs`,
    { signal },
  )

  return response.map((run) => ({
    ...run,
    durationMs: run.durationMs === null ? null : Number(run.durationMs),
    runId: Number(run.runId),
  }))
}

async function fetchDiagnosisDetail(agentRunId: string, signal?: AbortSignal) {
  return agentApiFetch<DiagnosisExecutionResponse>(
    `/api/v1/diagnosis/runs/${encodeURIComponent(agentRunId)}`,
    { signal },
  )
}

function timestampValue(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function reportSummary(result: PromiseSettledResult<DiagnosisExecutionResponse>) {
  if (result.status !== 'fulfilled') return null
  const report = result.value.report
  if (result.value.status !== 'COMPLETED' || typeof report?.summary !== 'string' || !report.summary.trim()) return null
  return report.summary
}

export async function fetchRecentDiagnoses(projectId: string, signal?: AbortSignal): Promise<RecentDiagnosis[]> {
  const runtimeRuns = await agentApiFetch<RuntimeRunSummary[]>(
    `/api/v1/evaluation/runtime/runs?projectId=${encodeURIComponent(projectId)}`,
    { signal },
  )
  const diagnosisRuns = runtimeRuns
    .filter((run) => run.executionType === 'DIAGNOSIS')
    .sort((left, right) => timestampValue(right.startedAt) - timestampValue(left.startedAt))
    .slice(0, 5)

  const completedRuns = diagnosisRuns.filter((run) => run.status === 'COMPLETED')
  const detailResults = await Promise.allSettled(
    completedRuns.map((run) => fetchDiagnosisDetail(run.agentRunId, signal)),
  )
  const authorizationFailure = detailResults.find(
    (result): result is PromiseRejectedResult => (
      result.status === 'rejected'
      && result.reason instanceof ApiError
      && (result.reason.status === 401 || result.reason.status === 403)
    ),
  )
  if (authorizationFailure) throw authorizationFailure.reason

  const summaries = new Map<string, string>()
  completedRuns.forEach((run, index) => {
    const summary = reportSummary(detailResults[index])
    if (summary) summaries.set(run.agentRunId, summary)
  })

  return diagnosisRuns.map((run) => ({
    agentRunId: run.agentRunId,
    runId: run.runId,
    startedAt: run.startedAt,
    status: run.status,
    summary: summaries.get(run.agentRunId) ?? null,
  }))
}
