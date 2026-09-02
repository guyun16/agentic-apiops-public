import type { TestReport } from '../runs/types'

export type DiagnosisExecutionStatus = 'COMPLETED' | 'APPROVAL_REQUIRED' | 'FAILED' | 'REJECTED'

export type DiagnosisHistoryFilter = 'ALL' | 'COMPLETED' | 'APPROVAL_REQUIRED' | 'FAILED'

export type DiagnosisStepState = 'COMPLETED' | 'ACTIVE' | 'PENDING' | 'REJECTED'

export type DiagnosisHypothesis = {
  statement: string
  confidence: 'LOW' | 'MEDIUM' | 'HIGH'
  evidenceRefs: Array<{ itemId: string }>
}

export type DiagnosisReportPayload = {
  schemaVersion: '0.1.0'
  reportId: string
  agentRunId: string
  projectId: number
  runId: number
  failureType: string
  summary: string
  rootCauseHypotheses: DiagnosisHypothesis[]
  sufficientEvidence: boolean
  limitations: string[]
  recommendedChecks: string[]
  traceId: string
}

export type DiagnosisExecutionStep = {
  id: string
  label: string
  detail: string
  state: DiagnosisStepState
}

export type DiagnosisContextSummary = {
  evidenceItems: number
  contextCharacters: number
  modelCalls: number
  toolCalls: number
}

export type DiagnosisApprovalRequest = {
  toolName: string
  risk: string
  reason: string
  arguments: Record<string, unknown>
  scope: {
    workflowId: string
    projectId: string
    toolIntentId: string
    argumentsFingerprint: string
  }
}

export type DiagnosisFailure = {
  code: string
  message: string
}

export type DiagnosisExecutionResponse = {
  status: DiagnosisExecutionStatus
  runtime: 'PYTHON_AGENTLAB'
  implementation: 'REAL'
  workflow: string
  provider: string
  model: string
  projectId: number
  runId: number
  taskId: number
  reportId: string
  agentRunId: string
  traceId: string
  workflowId: string
  testReport: TestReport
  report: DiagnosisReportPayload | null
  toolIntentId: string | null
  toolCallId: string | null
  approvalRequest: DiagnosisApprovalRequest | null
  steps: DiagnosisExecutionStep[]
  context: DiagnosisContextSummary
  failure: DiagnosisFailure | null
}
