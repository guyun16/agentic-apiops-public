export type RunStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'ASSERTION_FAILED' | 'EXECUTION_FAILED' | 'TIMEOUT' | 'CANCELLED'

export type RunMethod = 'GET' | 'POST' | 'DELETE'

export type AssertionStatus = 'PASS' | 'FAIL'

export type RunFilter = 'ALL' | 'SUCCESS' | 'FAILED' | 'RUNNING' | 'PENDING' | 'CANCELLED'

export type FailureType =
  | 'NONE'
  | 'ASSERTION_MISMATCH'
  | 'ASSERTION_EVALUATION_ERROR'
  | 'HTTP_STATUS_ERROR'
  | 'TIMEOUT'
  | 'NETWORK_ERROR'
  | 'REQUEST_BUILD_ERROR'
  | 'INVALID_TARGET_URI'
  | 'DNS_ERROR'
  | 'CONNECT_ERROR'
  | 'TLS_ERROR'
  | 'IO_ERROR'
  | 'SCHEMA_INVALID'
  | 'BUSINESS_ERROR'
  | 'TOOL_ERROR'
  | 'SYSTEM_ERROR'
  | 'UNKNOWN'

export type RunTab = 'Summary' | 'Test Report' | 'Timeline'

export type RunAssertion = {
  id: string
  type: string
  title: string
  expected: string
  actual: string
  details: string
  status: AssertionStatus
}

export type RunStep = {
  id: string
  name: string
  status: RunStatus
  failureType: FailureType
  method?: RunMethod
  path?: string
  duration: string
  responseStatus?: number | string
  assertions: RunAssertion[]
}

export type RunCase = {
  id: string
  name: string
  status: RunStatus
  failureType: FailureType
  summary?: string
  steps: RunStep[]
}

export type HeaderValue = {
  name: string
  value: string
}

export type RunRequest = {
  method: RunMethod
  url: string
  headers: HeaderValue[]
  body: string
}

export type RunResponse = {
  status: number | string
  statusText: string
  duration: string
  headers: HeaderValue[]
  body: string
}

export type TimelineStep = {
  label: string
  offset: string
  tone: 'neutral' | 'success' | 'accent' | 'danger'
}

export type RunRecord = {
  id: string
  status: RunStatus
  failureType: FailureType
  method: RunMethod
  endpoint: string
  summary: string
  relativeTime: string
  duration: string
  httpStatus: number | string
  started: string
  completed: string
  assertionsPassed: number
  assertionsTotal: number
  environment: string
  executedBy: string
  caseId: string
  traceId: string
  triggeredBy: string
  request: RunRequest
  response: RunResponse
  assertions: RunAssertion[]
  cases?: RunCase[]
  timeline: TimelineStep[]
}

/** Java RunSummaryVO; this is the only collection model used by the real Runs explorer. */
export type RunSummary = {
  runId: number
  caseId: string
  apiId: string
  testCaseName: string
  status: RunStatus
  failureType: FailureType | null
  createdAt: string | null
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
}

export type TestReportAssertion = {
  type: string
  passed: boolean
  expected: unknown
  actual: unknown
  message: string | null
}

export type HttpSnapshotBody = {
  headers: Record<string, string[]>
  body: string | null
  bodyState: 'captured' | 'omitted' | 'empty'
  truncated: boolean
}

export type HttpExchangeSnapshot = {
  request: HttpSnapshotBody & { method: string; url: string }
  response: (HttpSnapshotBody & { statusCode: number }) | null
}

export type TestReportStep = {
  stepId: string
  status: RunStatus
  failureType: FailureType
  responseStatusCode: number | null
  durationMs: number | null
  assertionResults: TestReportAssertion[]
  httpExchange?: HttpExchangeSnapshot | null
}

export type TestReportCase = {
  caseId: string
  status: RunStatus
  failureType: FailureType
  steps: TestReportStep[]
}

export type TestReport = {
  projectId: number
  taskId: number
  runId: number
  reportId: string
  status: RunStatus
  startedAt: string
  finishedAt: string | null
  summary: {
    totalCases: number
    totalSteps: number
    totalAssertions: number
    passedAssertions: number
    failedAssertions: number
    failureType: FailureType
  }
  cases: TestReportCase[]
}

/** Deliberately omits taskId: progress identity is transport data, not a Console surface. */
export type RunProgress = {
  runId: number
  total: number
  completed: number
  running: number
  success: number
  assertionFailed: number
  executionFailed: number
  timeout: number
  cancelled: number
  status: RunStatus
  updatedAt: string
}

export type RunLiveState = 'idle' | 'connecting' | 'live' | 'disconnected'

export function isDiagnosableStatus(status: RunStatus) {
  return status === 'ASSERTION_FAILED' || status === 'EXECUTION_FAILED' || status === 'TIMEOUT'
}
