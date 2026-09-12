export type RuntimeMetricStatus = 'VALUE' | 'NOT_APPLICABLE' | 'UNKNOWN' | 'ERROR'

export type RuntimeRunStatus = 'COMPLETED' | 'RUNNING' | 'FAILED' | 'APPROVAL_REQUIRED' | 'REJECTED'

export type RuntimeExecutionType = 'DIAGNOSIS' | 'TESTCASE_GENERATION'

export type RuntimeMetric = {
  status: RuntimeMetricStatus
  value: number | null
  unit: string | null
  reason: string | null
}

export type RuntimeMetricAggregate = {
  metric: string
  status: RuntimeMetricStatus
  totalCount: number
  applicableCount: number
  valueCount: number
  notApplicableCount: number
  unknownCount: number
  errorCount: number
  unit: string | null
  mean: number | null
  rate: number | null
  reason: string | null
}

export type RuntimeExecutionCounts = {
  total: number
  success: number
  failure: number
  running: number
  approvalRequired: number
  rejected: number
  unknown: number
}

export type RuntimeToolCounts = {
  attempted: number
  success: number
  failed: number
  denied: number
  timeout: number
  unknown: number
  notApplicable: number
}

export type RuntimeSafetyCounts = {
  explicitOutcomes: Record<string, number>
  unknown: number
}

export type RuntimeRunSummary = {
  agentRunId: string
  traceId: string
  executionType: RuntimeExecutionType
  status: RuntimeRunStatus
  provider: string
  model: string
  projectId: number | null
  apiId: string | null
  runId: number | null
  reportId: string | null
  startedAt: string
  finishedAt: string | null
}

export type EvaluationMetricResult = {
  metric: string
  status: RuntimeMetricStatus
  value: number | null
  unit: string | null
  reason: string | null
  details: string[]
}

export type EvaluationResult = {
  evaluation_id: string
  case_id: string
  trace_id: string
  agent_run_id: string
  ground_truth_id: string
  ground_truth_version: string
  evaluator_version: string
  metrics: EvaluationMetricResult[]
}

export type JudgeResult = {
  judge_result_id: string
  judge_case_id: string
  trace_id: string
  agent_run_id: string
  dimension: string
  score: number
  reason: string
  configuration: {
    rubric: {
      rubric_id: string
      version: string
      dimension: string
      criteria: string[]
    }
    prompt: {
      name: string
      version: string
    }
    model_identity: {
      provider: string
      model: string
      deployment: string | null
      version: string | null
    }
  }
}

export type RuntimeRunDetail = RuntimeRunSummary & {
  metrics: Record<string, RuntimeMetric>
  toolCounts: RuntimeToolCounts
  safetyStatus: RuntimeMetricStatus
  safetyOutcome: string | null
  safetyReason: string | null
  traceRecordCount: number
  failureCode: string | null
  failureMessage: string | null
  evaluationResult: EvaluationResult | null
  judgeResults: JudgeResult[]
}

export type RuntimeEvaluationSummary = {
  runtime: 'PYTHON_AGENTLAB'
  runCount: number
  execution: RuntimeExecutionCounts
  metrics: Record<string, RuntimeMetricAggregate>
  tool: RuntimeToolCounts
  safety: RuntimeSafetyCounts
}

export type EvaluationRunFilter = 'ALL' | RuntimeRunStatus

export type EvaluationTab = 'Overview' | 'Deterministic' | 'LLM Judge' | 'Runtime Facts' | 'Cost & Latency'
