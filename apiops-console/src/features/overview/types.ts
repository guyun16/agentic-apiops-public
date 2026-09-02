import type { RuntimeRunStatus } from '../evaluation/types'

export type HealthStatus = 'UP' | 'DOWN' | 'DEGRADED' | 'UNKNOWN'

export type HealthItemId = 'java' | 'python'

export type HealthItem = {
  id: HealthItemId
  name: string
  status: HealthStatus
  source: string
  sourceAvailable: boolean
  checkedAt: string | null
}

export type RecentDiagnosis = {
  agentRunId: string
  runId: number | null
  status: RuntimeRunStatus
  startedAt: string
  summary: string | null
}
