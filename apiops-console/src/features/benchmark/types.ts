export type BenchmarkRunStatus = 'COMPLETED' | 'FAILED'

export type BenchmarkRunFilter = 'ALL' | BenchmarkRunStatus

export type BenchmarkTab = 'Overview' | 'Categories' | 'Tasks' | 'Failures' | 'Reproducibility'

export type BenchmarkTaskStatus = 'SUCCESS' | 'FAILED' | 'TIMEOUT' | 'ABORTED'

export type BenchmarkExecutionMode = 'DETERMINISTIC_FIXTURE' | 'REAL_MODEL' | 'UNKNOWN'

export type BenchmarkMetricState = 'VALUE' | 'NOT_APPLICABLE' | 'UNKNOWN' | 'ERROR' | 'MISSING'

export type BenchmarkMetadataAvailability = 'AVAILABLE' | 'UNAVAILABLE' | 'UNKNOWN'

export type BenchmarkConfigurationValue = {
  value: unknown | null
  availability: BenchmarkMetadataAvailability
  source: string
  reason: string | null
}

export type BenchmarkMetric = {
  metric: string
  state: BenchmarkMetricState
  value: number | null
  mean: number | null
  rate: number | null
  unit: string | null
  reason: string | null
  totalCount: number | null
  applicableCount: number | null
  valueCount: number | null
  notApplicableCount: number | null
  unknownCount: number | null
  errorCount: number | null
}

export type BenchmarkTaskSuccess = {
  status: 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE' | null
  rate: number | null
  passCount: number | null
  failCount: number | null
  unknownCount: number | null
  notApplicableCount: number | null
}

export type BenchmarkTaskCondition = {
  name: string
  metric: string | null
  metricStatus: string | null
  status: 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE'
  required: boolean
  reason: string
}

export type BenchmarkMetricResult = {
  metric: string
  status: 'VALUE' | 'NOT_APPLICABLE' | 'UNKNOWN' | 'ERROR'
  value: number | null
  unit: string | null
  reason: string | null
  details: string[]
}

export type BenchmarkTask = {
  formalOutcome?: {
    revision: string
    status: 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE'
    split: string
    authority: string
    sourceRef: string
    metrics: { metric: string; status: BenchmarkMetricState; value: number | null; expectedValue: number | null; reason: string | null }[]
  }
  evaluationRunId: string
  benchmarkTaskId: string
  caseId: string
  taskType: string
  status: BenchmarkTaskStatus
  executionMode: BenchmarkExecutionMode
  failureStage: string | null
  failureCategory: string | null
  failureCode: string | null
  failureReason: string | null
  evaluationId: string | null
  agentRunId: string
  traceId: string
  runId: number | null
  reportId: string | null
  durationMs: number | null
  modelLatencyMs: number | null
  promptTokens: number | null
  completionTokens: number | null
  totalTokens: number | null
  taskSuccess: {
    status: 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE'
    conditions: BenchmarkTaskCondition[]
    passCount: number
    failCount: number
    unknownCount: number
    notApplicableCount: number
  } | null
  metrics: BenchmarkMetricResult[]
  artifactRef: string | null
}

export type BenchmarkArtifactReferences = {
  run: string | null
  baselineRun: string | null
  baselineConfig: string | null
  reproducibility: string | null
  evaluationCsv: string | null
  baselineReport: string | null
  failureInventory: string | null
  collateralDamage: string | null
  taskResults: string[]
}

export type BenchmarkRunSummary = {
  displayName: string
  role: 'BASELINE' | 'IMPROVED' | 'CURRENT' | 'HISTORY'
  displayOrder: number
  benchmarkRevision?: string
  resultSource?: 'VERIFIED_ARTIFACT_SNAPSHOT'
  evaluationRunId: string
  datasetId: string
  datasetVersion: string
  datasetSplit: string | null
  taskSchemaVersion: string
  status: BenchmarkRunStatus
  selectedTaskCount: number
  executedTaskCount: number
  evaluatedTaskCount: number
  completedTaskCount: number
  failedTaskCount: number
  startedAt: string
  completedAt: string
  model: BenchmarkConfigurationValue
  prompt: BenchmarkConfigurationValue[]
  evaluator: BenchmarkConfigurationValue
  benchmarkConfigVersion: string | null
  dataSource: 'ARTIFACT'
}

export type BenchmarkRunDetail = BenchmarkRunSummary & {
  aggregateMetrics: BenchmarkMetric[]
  taskSuccess: BenchmarkTaskSuccess
  artifactReferences: BenchmarkArtifactReferences
}
