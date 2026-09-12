import { apiFetch } from '../../lib/api-client'
import type { FailureType, RunStatus, RunSummary } from './types'

type ExactRunResponse = {
  projectId: number
  taskId: number
  runId: number
  caseId: string
  apiId: string
  testCaseName: string
  status: RunStatus
  failureType: FailureType
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  reportId: string | null
}

export type ExactRun = RunSummary & Pick<ExactRunResponse, 'projectId' | 'taskId' | 'reportId'>

export async function fetchExactRun(projectId: string | number, runId: number, signal?: AbortSignal): Promise<ExactRun> {
  const run = await apiFetch<ExactRunResponse>(
    `/api/v1/projects/${encodeURIComponent(String(projectId))}/test-runs/${runId}`,
    { signal },
  )
  return {
    ...run,
    createdAt: null,
    durationMs: run.durationMs === null ? null : Number(run.durationMs),
    projectId: Number(run.projectId),
    runId: Number(run.runId),
    taskId: Number(run.taskId),
  }
}

export function includeExactRun(recentRuns: RunSummary[], exactRun: ExactRun | null) {
  if (!exactRun) return recentRuns
  const recent = recentRuns.find((run) => run.runId === exactRun.runId)
  return [{ ...exactRun, createdAt: recent?.createdAt ?? exactRun.createdAt },
    ...recentRuns.filter((run) => run.runId !== exactRun.runId)]
}
