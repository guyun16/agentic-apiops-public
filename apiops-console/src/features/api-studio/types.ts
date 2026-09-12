export type HttpMethod = string

export type ApiMetadataSummary = {
  apiId: string
  apiDocId: string
  operationId: string
  method: string
  path: string
  summary: string | null
  tags: unknown
  deprecated: boolean
}

export type ApiMetadataParameter = {
  name: string
  location: string
  required: boolean
  description: string | null
  schema: unknown
  example: unknown
}

export type ApiMetadataRequestSchema = {
  required: boolean
  mediaType: string
  schema: unknown
}

export type ApiMetadataResponseSchema = {
  statusCode: string
  description: string | null
  mediaType: string
  schema: unknown
}

export type ExpectedResponse = ApiMetadataResponseSchema & {
  example: unknown | null
  why: string
}

export type ApiMetadataExampleOwner = {
  type: string
  parameterName: string | null
  parameterLocation: string | null
  mediaType: string | null
  statusCode: string | null
} | null

export type ApiMetadataExample = {
  owner: ApiMetadataExampleOwner
  exampleName: string
  summary: string | null
  description: string | null
  value: unknown
}

export type ApiMetadataDetail = {
  apiId: string
  apiDocId: string
  operationId: string
  method: string
  path: string
  summary: string | null
  description: string | null
  tags: unknown
  servers: unknown
  security: unknown
  deprecated: boolean
  parameters: ApiMetadataParameter[]
  requestSchemas: ApiMetadataRequestSchema[]
  responseSchemas: ApiMetadataResponseSchema[]
  examples: ApiMetadataExample[]
}

export function formatMetadataJson(value: unknown): string {
  if (value === null || value === undefined) {
    return '—'
  }

  if (typeof value === 'string') {
    return value
  }

  try {
    return JSON.stringify(value, null, 2) ?? '—'
  } catch {
    return String(value)
  }
}

export function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—'
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return '—'
    }

    if (value.every((item) => item === null || ['string', 'number', 'boolean'].includes(typeof item))) {
      return value.map((item) => String(item)).join(', ')
    }
  }

  return formatMetadataJson(value)
}

export type ApiResponse = {
  status: string
  title: string
  description: string
  tone: 'success' | 'warning' | 'danger' | 'neutral'
  schema?: string
  example?: string
}

export type ApiParameter = {
  name: string
  location: 'path' | 'query' | 'header'
  required: boolean
  description: string
  schema: string
  example?: string
}

export type ApiExample = {
  name: string
  owner: string
  summary: string
  value: string
}

export type ApiEndpoint = {
  id: string
  apiDocId: string
  service: string
  method: HttpMethod
  path: string
  title: string
  description: string
  operationId: string
  version: string
  documentVersionNo: number
  openapiVersion: string
  security: string
  securityRequirements: string[]
  servers: string[]
  tags: string[]
  deprecated: boolean
  parameters: ApiParameter[]
  requestSchema?: string
  examples: ApiExample[]
  requestBodyExample: string
  responses: ApiResponse[]
}

/** Persisted ApiDocument status currently emitted by the Java OpenAPI contract. */
export type ApiDocumentStatus = 'ACTIVE'

/** Frontend-only lifecycle for the import interaction; never a persisted ApiDocument status. */
export type ApiDocumentImportPhase = 'PROCESSING' | 'COMPLETED' | 'FAILED'

export type ApiDocument = {
  apiDocId: string
  projectId: number
  sourceKey: string
  documentName: string
  openapiVersion: string
  title: string
  apiVersion: string
  documentFormat: string
  contentHash: string
  versionNo: number
  status: ApiDocumentStatus
  createdAt: string
  updatedAt: string
}

export type OpenApiImportResponse = {
  projectId: number
  sourceKey: string
  filename: string
  fileSize: number
  contentHash: string
  openapiVersion: string
}

export type ApiDocumentVersion = {
  apiDocId: string
  sourceKey: string
  documentName: string
  openapiVersion: string
  title: string
  apiVersion: string
  documentFormat: 'JSON' | 'YAML'
  versionNo: number
  status: ApiDocumentStatus
  importedAt: string
  updatedAt: string
  endpointIds: string[]
  errorCode?: 'INVALID_OPENAPI' | 'UNSUPPORTED_OPENAPI_VERSION' | 'REMOTE_REF_NOT_ALLOWED'
  errorSummary?: string
}

export type ApiService = {
  id: string
  name: string
  endpointIds: string[]
}

export type StrategyId =
  | 'HAPPY_PATH'
  | 'MISSING_REQUIRED'
  | 'BOUNDARY'
  | 'AUTH_FAILURE'
  | 'IDEMPOTENCY'
  | 'BUSINESS_ERROR'

export type TestCaseAgentRuntime = 'JAVA_AGENT' | 'PYTHON_AGENTLAB'

export type AgentRuntimeOption = {
  id: TestCaseAgentRuntime
  label: string
  implementation: string
  workflow: string
  generatedBy: string
}

export type StrategyOption = {
  id: StrategyId
  label: string
}

export type StrategyAvailability = {
  applicable: boolean
  reason: string
}

export type GenerationStatus = 'ACCEPTED' | 'GENERATING' | 'VALIDATING' | 'REPAIRING' | 'REJECTED' | 'FAILED'

export type GenerateTestCaseModelCall = {
  modelCallId: string
  repairOfModelCallId: string | null
}

export type GenerateTestCaseResponse = {
  agentRunId: string
  promptName: string
  promptVersion: string
  modelCalls: GenerateTestCaseModelCall[]
  candidate: Record<string, unknown>
}

export type RunnerBatchSubmission = {
  batchId: string
  taskIds: number[]
  runIds: number[]
}

export type RunnerSubmissionIdentity = {
  batchId: string
  taskId: number
  runId: number
}

export function runnerRequestForValidatedTestCase(
  status: GenerationStatus | null,
  candidate: Record<string, unknown> | null,
) {
  return status === 'ACCEPTED' && candidate ? { testCases: [candidate] } : null
}

export function singleRunnerSubmission(submission: RunnerBatchSubmission): RunnerSubmissionIdentity {
  const taskId = Number(submission.taskIds[0])
  const runId = Number(submission.runIds[0])
  if (submission.taskIds.length !== 1 || submission.runIds.length !== 1
    || !Number.isInteger(taskId) || taskId <= 0 || !Number.isInteger(runId) || runId <= 0) {
    throw new Error('Java Runner returned an invalid single-TestCase submission identity')
  }
  return { batchId: submission.batchId, taskId, runId }
}

/** A previous validation never authorizes a different editor snapshot. */
export function runnerRequestForEditor(
  status: GenerationStatus | null,
  candidate: Record<string, unknown> | null,
  draft: string,
  validatedDraft: string | null,
) {
  if (validatedDraft === null || draft !== validatedDraft) return null
  return runnerRequestForValidatedTestCase(status, candidate)
}

export type GenerationOutcome = {
  requiresRepair: boolean
  finalStatus: Extract<GenerationStatus, 'ACCEPTED' | 'REJECTED'>
  repairAttempts: number
}
