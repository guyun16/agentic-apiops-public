export type TraceStatus = 'SUCCESS' | 'FAILED' | 'REJECTED' | 'DENIED' | 'RUNNING' | 'INTERRUPTED'

export type TraceFilter = 'ALL' | 'SUCCESS' | 'FAILED' | 'TOOL' | 'MODEL' | 'PYTHON' | 'JAVA'

export type TraceSource = 'PYTHON' | 'JAVA'

export type TraceInspectorTab = 'Overview' | 'Input' | 'Output' | 'Attributes'

export type TraceStepKind = 'AGENT' | 'TASK' | 'MODEL' | 'TOOL'

export type TraceStepStatus = 'SUCCESS' | 'FAILED' | 'WAITING' | 'REJECTED' | 'DENIED' | 'RUNNING' | 'INTERRUPTED'

export type TraceAttribute = {
  label: string
  value: string
}

export type TraceModelCallFacts = {
  modelCallId: string
  provider: string
  model: string
  runtime: string
  implementation: string
  promptName: string
  promptVersion: string
  startedAt: string
  durationLabel: string
  status: TraceStepStatus
  inputTokens?: number
  outputTokens?: number
  totalTokens?: number
  cost?: string
  attempt?: number
  errorType?: string
}

export type TraceToolActivityPhase = 'INTENT' | 'APPROVAL' | 'GATEWAY' | 'RESULT'

export type TraceToolActivityFacts = {
  phase: TraceToolActivityPhase
  toolName: string
  toolIntentId?: string
  toolCallId?: string
  requestId?: string
  risk?: string
  preflightDecision?: string
  approvalOutcome?: string
  authorizationResult?: string
  guardDecision?: string
  status?: string
  latencyLabel?: string
  sanitized?: boolean
  truncated?: boolean
  hasData?: boolean
  toolResultStatus?: string
  resultSummary?: string
  violationCode?: string
}

export type TraceApprovalFacts = {
  toolIntentId: string
  decision?: string
  reason?: string
}

export type TraceEvidenceItem = {
  sourceType: string
  sourceId: string
  documentId?: string
  chunkId?: string
  location?: string
  relevanceScore?: number
  citation?: string
}

export type TraceContextEvidenceFacts = {
  ragQueryId?: string
  query?: string
  contextSources: string[]
  totalChars?: number
  maxTotalChars?: number
  truncated?: boolean
  memoryId?: string
  evidence: TraceEvidenceItem[]
}

export type TraceObservationFacts = {
  contextEvidenceCount: number
  evidenceReferenceCount: number
  toolIntentCount: number
  guardCount: number
  hitlCount: number
  javaToolResultCount: number
  finalStatus: TraceStatus
  finalResult: string
}

export type TraceStepDetail = {
  status: TraceStepStatus
  durationLabel: string
  toolCallId?: string
  toolIntentId?: string
  requestId?: string
  agentRunId?: string
  agentStepId?: string
  modelCallId?: string
  ragQueryId?: string
  decision?: string
  traceId: string
  parentStep: string
  source: TraceSource
  startTime: string
  endTime: string
  input: string
  output: string
  attributes: TraceAttribute[]
  modelCall?: TraceModelCallFacts
  toolActivity?: TraceToolActivityFacts
  approval?: TraceApprovalFacts
  contextEvidence?: TraceContextEvidenceFacts
}

export type TraceStep = {
  id: string
  index: string
  name: string
  source: TraceSource
  status: TraceStepStatus
  kind: TraceStepKind
  startMs: number
  durationMs: number
  depth: number
  parentId?: string
  expandable?: boolean
  detail: TraceStepDetail
}

export type TraceIdentity = {
  label: 'traceId' | 'agentRunId' | 'runId'
  value: string
}

export type TraceRecord = {
  id: string
  status: TraceStatus
  name: string
  agentRunId: string
  traceId: string
  runId: string
  startedAt?: string
  steps: TraceStep[]
  stepCount: number
  durationLabel: string
  durationMs: number
  relativeTime: string
  tags: Array<'TOOL' | 'MODEL'>
  modelCalls: number
  toolCalls: number
  environment: string
  agentRuntime: string
  correlatedSystems: string
  identities: TraceIdentity[]
  observationFacts?: TraceObservationFacts
}
