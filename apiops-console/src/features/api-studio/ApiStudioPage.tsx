import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { useContextTrail, type ContextTrailTarget } from '../../app/ContextTrailContext'
import { useProject } from '../../app/ProjectContext'
import { ContextTrail } from '../../components/layout/ContextTrail'
import { ApiError, agentApiFetch, apiFetch } from '../../lib/api-client'
import { ApiExplorer } from './components/ApiExplorer'
import { EndpointHeader } from './components/EndpointHeader'
import { GeneratedDslPanel } from './components/GeneratedDslPanel'
import { RequestResponsePanel } from './components/RequestResponsePanel'
import { TestCaseGeneratorPanel } from './components/TestCaseGeneratorPanel'
import {
  agentRuntimeOptions,
  defaultAgentRuntime,
  defaultStrategy,
  strategyOptions,
} from './mock-data'
import {
  runnerRequestForEditor,
  singleRunnerSubmission,
  type ApiDocument,
  type ApiMetadataDetail,
  type ApiMetadataResponseSchema,
  type ApiMetadataSummary,
  type ExpectedResponse,
  type GenerationStatus,
  type GenerateTestCaseResponse,
  type OpenApiImportResponse,
  type RunnerBatchSubmission,
  type RunnerSubmissionIdentity,
  type StrategyAvailability,
  type StrategyId,
  type TestCaseAgentRuntime,
} from './types'
import { fetchExactRun } from '../runs/run-api'
import { readStudioDraft, readStudioSelection, studioDraftKey, writeStudioDraft, writeStudioSelection } from './studioDrafts'

type EndpointLoadState = 'loading' | 'ready' | 'error'
type MetadataDetailLoadState = 'idle' | EndpointLoadState
type ApiStudioContextTarget = Extract<ContextTrailTarget, { type: 'endpoint' | 'testcase' }>

type ApiStudioPageProps = {
  contextTarget: ApiStudioContextTarget | null
  onContextNavigate: (target: ContextTrailTarget) => void
  onViewRun: (runId: number) => void
  onEndpointSelected?: (apiId: string, apiDocId: string) => void
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function apiErrorFor(error: unknown, fallback: string) {
  return error instanceof ApiError ? error : new ApiError(fallback, 0, 'NETWORK_ERROR')
}

function normalizeApiMetadataSummary(summary: ApiMetadataSummary): ApiMetadataSummary {
  return {
    ...summary,
    apiId: String(summary.apiId),
    apiDocId: String(summary.apiDocId),
    method: summary.method.trim().toUpperCase(),
  }
}

function normalizeApiDocument(document: ApiDocument): ApiDocument {
  return {
    ...document,
    apiDocId: String(document.apiDocId),
    projectId: Number(document.projectId),
    versionNo: Number(document.versionNo),
    createdAt: document.createdAt ? String(document.createdAt) : '',
    updatedAt: document.updatedAt ? String(document.updatedAt) : '',
  }
}

function normalizeApiMetadataDetail(detail: ApiMetadataDetail): ApiMetadataDetail {
  return {
    ...detail,
    apiId: String(detail.apiId),
    apiDocId: String(detail.apiDocId),
    method: detail.method.trim().toUpperCase(),
    parameters: detail.parameters ?? [],
    requestSchemas: detail.requestSchemas ?? [],
    responseSchemas: detail.responseSchemas ?? [],
    examples: detail.examples ?? [],
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isDocumentedStatus(value: string, predicate: (status: number) => boolean) {
  const normalized = value.trim()
  if (!/^\d{3}$/.test(normalized)) return false
  const status = Number(normalized)
  return status >= 100 && status <= 599 && predicate(status)
}

const boundaryIntegerKeys = new Set([
  'minLength',
  'maxLength',
  'minItems',
  'maxItems',
  'minProperties',
  'maxProperties',
])
const boundaryNumberKeys = new Set([
  'minimum',
  'maximum',
  'exclusiveMinimum',
  'exclusiveMaximum',
  'multipleOf',
])

function isBoundaryConstraint(key: string, value: unknown) {
  if (key === 'enum') return Array.isArray(value) && value.length > 0
  if (boundaryIntegerKeys.has(key)) {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0
  }
  if (boundaryNumberKeys.has(key)) return typeof value === 'number'
  return false
}

function hasBoundaryConstraint(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasBoundaryConstraint)
  if (!isRecord(value)) return false

  return Object.entries(value).some(([key, child]) => (
    isBoundaryConstraint(key, child)
    || (key !== 'enum' && hasBoundaryConstraint(child))
  ))
}

function hasSecurityDeclaration(value: unknown) {
  return Array.isArray(value) && value.some((item) => isRecord(item) && Object.keys(item).length > 0)
}

function responseExample(detail: ApiMetadataDetail, response: ApiMetadataResponseSchema) {
  return detail.examples.find((example) => (
    example.owner?.type === 'RESPONSE_SCHEMA'
    && example.owner.statusCode === response.statusCode
    && (!example.owner.mediaType || !response.mediaType || example.owner.mediaType === response.mediaType)
  ))?.value ?? null
}

function responseEvidenceText(detail: ApiMetadataDetail, response: ApiMetadataResponseSchema) {
  const example = responseExample(detail, response)
  let exampleText = ''
  try {
    exampleText = example === null ? '' : JSON.stringify(example)
  } catch {
    exampleText = ''
  }
  return `${response.description ?? ''} ${exampleText}`
}

function isClientError(response: ApiMetadataResponseSchema) {
  return isDocumentedStatus(response.statusCode, (status) => status >= 400 && status <= 499)
}

function findExpectedResponse(detail: ApiMetadataDetail, strategy: StrategyId): ExpectedResponse | null {
  const documented = detail.responseSchemas
  const validationResponse = documented.find((response) => (
    isClientError(response) && /required|validation|invalid|bad request|unprocessable|constraint|range/i.test(responseEvidenceText(detail, response))
  ))
  let response: ApiMetadataResponseSchema | undefined
  let why = ''

  if (strategy === 'HAPPY_PATH') {
    response = documented.find((item) => isDocumentedStatus(item.statusCode, (status) => status >= 200 && status <= 299))
    why = 'Selected from the endpoint’s documented 2xx responses.'
  } else if (strategy === 'MISSING_REQUIRED') {
    response = validationResponse
    why = 'Required request metadata is present and this is the documented validation response.'
  } else if (strategy === 'BOUNDARY') {
    response = validationResponse
    why = 'A request boundary is documented and this is the documented invalid-input response.'
  } else if (strategy === 'AUTH_FAILURE') {
    response = documented.find((item) => isDocumentedStatus(item.statusCode, (status) => status === 401 || status === 403))
    why = 'The endpoint declares security and documents this authentication failure response.'
  } else if (strategy === 'IDEMPOTENCY') {
    response = documented.find((item) => /\b(?:idempotent|idempotency|duplicate|replay|already processed|request key)\b/i.test(responseEvidenceText(detail, item)))
    why = 'Selected from the endpoint’s documented idempotency-related response evidence.'
  } else {
    response = documented.find((item) => isDocumentedStatus(item.statusCode, (status) => status >= 300))
    why = 'Selected from the endpoint’s documented non-2xx response mapping.'
  }

  if (!response) return null
  return {
    ...response,
    example: responseExample(detail, response),
    why,
  }
}

function getStrategyAvailability(detail: ApiMetadataDetail | null): Record<StrategyId, StrategyAvailability> {
  const unavailable: StrategyAvailability = {
    applicable: false,
    reason: 'Metadata evidence is not available.',
  }

  if (!detail) {
    return strategyOptions.reduce((result, option) => {
      result[option.id] = unavailable
      return result
    }, {} as Record<StrategyId, StrategyAvailability>)
  }

  const hasSuccessResponse = detail.responseSchemas.some((response) =>
    isDocumentedStatus(response.statusCode, (status) => status >= 200 && status <= 299))
  const hasBusinessErrorResponse = detail.responseSchemas.some((response) =>
    isDocumentedStatus(response.statusCode, (status) => status < 200 || status >= 300))
  const hasRequiredRequestField = detail.parameters.some((parameter) => parameter.required)
    || detail.requestSchemas.some((schema) => schema.required)
  const hasRequestBoundary = detail.parameters.some((parameter) => hasBoundaryConstraint(parameter.schema))
    || detail.requestSchemas.some((schema) => hasBoundaryConstraint(schema.schema))
  const hasIdempotencyDocumentation = /\b(?:idempotent|idempotency)\b/i.test(
    `${detail.summary ?? ''} ${detail.description ?? ''}`,
  )

  const evidence: Record<StrategyId, { applicable: boolean; reason: string }> = {
    HAPPY_PATH: { applicable: hasSuccessResponse, reason: 'Requires a documented 2xx response.' },
    MISSING_REQUIRED: { applicable: hasRequiredRequestField, reason: 'Requires a documented required request field.' },
    BOUNDARY: { applicable: hasRequestBoundary, reason: 'Requires a documented request boundary.' },
    AUTH_FAILURE: { applicable: hasSecurityDeclaration(detail.security), reason: 'Requires a documented security requirement.' },
    IDEMPOTENCY: { applicable: hasIdempotencyDocumentation, reason: 'Requires explicit idempotency documentation.' },
    BUSINESS_ERROR: { applicable: hasBusinessErrorResponse, reason: 'Requires a documented non-2xx response.' },
  }

  return strategyOptions.reduce((result, option) => {
    const expected = findExpectedResponse(detail, option.id)
    const base = evidence[option.id]
    result[option.id] = {
      applicable: base.applicable && Boolean(expected),
      reason: !base.applicable
        ? base.reason
        : expected
          ? ''
          : 'Requires a documented Expected Response for this strategy.',
    }
    return result
  }, {} as Record<StrategyId, StrategyAvailability>)
}

function MetadataDetailState({
  error,
  onRetry,
  state,
}: {
  error: ApiError | null
  onRetry: () => void
  state: MetadataDetailLoadState
}) {
  const { t, ui } = useConsoleLanguage()

  if (state === 'idle') {
    return (
      <section className="studio-empty-state" role="status">
        <strong>{ui('Select an endpoint')}</strong>
        <span>{ui('Select an endpoint to inspect its Java metadata.')}</span>
      </section>
    )
  }

  if (state === 'loading') {
    return (
      <section className="studio-empty-state" role="status" aria-live="polite">
        <strong>{ui('Loading endpoint metadata...')}</strong>
        <span>{ui('Reading the selected endpoint from Java Platform.')}</span>
      </section>
    )
  }

  if (state === 'error') {
    return (
      <section className="studio-empty-state" role="alert">
        <strong>{ui('Endpoint metadata unavailable')}</strong>
        <span>{error?.message ?? ui('Unable to load endpoint metadata.')}</span>
        <button className="button button-secondary" type="button" onClick={onRetry}>
          {t('common.retry')}
        </button>
      </section>
    )
  }

  return null
}

export function ApiStudioPage({ contextTarget, onContextNavigate, onViewRun, onEndpointSelected }: ApiStudioPageProps) {
  const { expireSession, currentUser } = useAuth()
  const { ui } = useConsoleLanguage()
  const { currentProject, refreshProjects } = useProject()
  const { activateContext, recordEndpoint, recordFinalizedTestCase, recordRun } = useContextTrail()
  const [documents, setDocuments] = useState<ApiDocument[]>([])
  const [documentsState, setDocumentsState] = useState<EndpointLoadState>('loading')
  const [documentsError, setDocumentsError] = useState<ApiError | null>(null)
  const [documentsReload, setDocumentsReload] = useState(0)
  const [selectedApiDocId, setSelectedApiDocId] = useState<string | null>(null)
  const [selectedApiId, setSelectedApiId] = useState<string | null>(null)
  const [apiSummaries, setApiSummaries] = useState<ApiMetadataSummary[]>([])
  const [apiSummariesState, setApiSummariesState] = useState<EndpointLoadState>('loading')
  const [apiSummariesError, setApiSummariesError] = useState<ApiError | null>(null)
  const [apiSummariesReload, setApiSummariesReload] = useState(0)
  const [apiDetail, setApiDetail] = useState<ApiMetadataDetail | null>(null)
  const [apiDetailState, setApiDetailState] = useState<MetadataDetailLoadState>('idle')
  const [apiDetailError, setApiDetailError] = useState<ApiError | null>(null)
  const [apiDetailReload, setApiDetailReload] = useState(0)
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyId | null>(defaultStrategy)
  const [selectedAgentRuntime, setSelectedAgentRuntime] = useState<TestCaseAgentRuntime>(defaultAgentRuntime)
  const [generatedByRuntime, setGeneratedByRuntime] = useState<TestCaseAgentRuntime | null>(null)
  const [generatedDsl, setGeneratedDsl] = useState('')
  const [validatedDsl, setValidatedDsl] = useState<string | null>(null)
  const [validationMessage, setValidationMessage] = useState<string | null>(null)
  const [validatedTestCase, setValidatedTestCase] = useState<Record<string, unknown> | null>(null)
  const [generationStatus, setGenerationStatus] = useState<GenerationStatus | null>(null)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [repairAttempts, setRepairAttempts] = useState(0)
  const [runnerSubmission, setRunnerSubmission] = useState<RunnerSubmissionIdentity | null>(null)
  const [runnerError, setRunnerError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const generationController = useRef<AbortController | null>(null)
  const generationRequestId = useRef(0)
  const submissionController = useRef<AbortController | null>(null)
  const [draftStorageFailed, setDraftStorageFailed] = useState(false)
  const importedDocumentRef = useRef<OpenApiImportResponse | null>(null)
  const isGenerating = generationStatus === 'GENERATING'

  const projectId = currentProject?.projectId ?? null
  const draftKey = currentUser && projectId && selectedApiDocId && selectedApiId
    ? studioDraftKey(currentUser.id, projectId, {
      apiDocId: selectedApiDocId, apiId: selectedApiId, strategy: selectedStrategy, runtime: selectedAgentRuntime,
    }) : null
  const currentDraftKey = useRef(draftKey)
  currentDraftKey.current = draftKey
  const strategyAvailability = useMemo(
    () => getStrategyAvailability(apiDetailState === 'ready' ? apiDetail : null),
    [apiDetail, apiDetailState],
  )
  const expectedResponse = useMemo(
    () => apiDetailState === 'ready' && apiDetail && selectedStrategy
      ? findExpectedResponse(apiDetail, selectedStrategy)
      : null,
    [apiDetail, apiDetailState, selectedStrategy],
  )

  const clearGenerationResult = useCallback(() => {
    submissionController.current?.abort()
    submissionController.current = null
    generationController.current?.abort()
    generationController.current = null
    generationRequestId.current += 1
    setGeneratedDsl('')
    setValidatedDsl(null)
    setValidationMessage(null)
    setValidatedTestCase(null)
    setGeneratedByRuntime(null)
    setGenerationStatus(null)
    setGenerationError(null)
    setRepairAttempts(0)
    setRunnerSubmission(null)
    setRunnerError(null)
    setIsSubmitting(false)
  }, [])

  const fetchApiSummaries = useCallback(async (nextProjectId: string, signal: AbortSignal) => {
    const response = await apiFetch<ApiMetadataSummary[]>(
      `/api/v1/projects/${encodeURIComponent(nextProjectId)}/openapi/apis`,
      { signal },
    )
    return response.map(normalizeApiMetadataSummary)
  }, [])

  const fetchDocuments = useCallback(async (nextProjectId: string, signal: AbortSignal) => {
    const response = await apiFetch<ApiDocument[]>(
      `/api/v1/projects/${encodeURIComponent(nextProjectId)}/openapi/documents`,
      { signal },
    )
    return response.map(normalizeApiDocument)
  }, [])

  useEffect(() => {
    importedDocumentRef.current = null
    const saved = currentUser && projectId ? readStudioSelection(currentUser.id, projectId) : null
    setDocuments([])
    setSelectedApiDocId(saved?.apiDocId ?? null)
    setApiSummaries([])
    setSelectedApiId(saved?.apiId ?? null)
    setSelectedStrategy(saved?.strategy ?? defaultStrategy)
    setSelectedAgentRuntime(saved?.runtime ?? defaultAgentRuntime)
  }, [projectId, currentUser?.id])

  useEffect(() => {
    clearGenerationResult()
    const draft = draftKey ? readStudioDraft(draftKey) : null
    if (draft !== null) {
      setGeneratedDsl(draft)
      setValidationMessage('Draft restored. Validate it with Java before running.')
    }
  }, [clearGenerationResult, draftKey])

  useEffect(() => {
    if (!currentUser || !projectId || !selectedApiDocId || !selectedApiId
      || apiDetailState !== 'ready' || apiDetail?.apiId !== selectedApiId || apiDetail?.apiDocId !== selectedApiDocId) return
    writeStudioSelection(currentUser.id, projectId, {
      apiDocId: selectedApiDocId, apiId: selectedApiId, strategy: selectedStrategy, runtime: selectedAgentRuntime,
    })
    onEndpointSelected?.(selectedApiId, selectedApiDocId)
  }, [currentUser?.id, projectId, selectedApiDocId, selectedApiId, selectedStrategy, selectedAgentRuntime, apiDetail, apiDetailState, onEndpointSelected])

  useEffect(() => () => {
    generationController.current?.abort()
    submissionController.current?.abort()
  }, [])

  useEffect(() => {
    if (!draftStorageFailed) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [draftStorageFailed])

  useEffect(() => {
    let cancelled = false
    setDocumentsError(null)

    if (!projectId) {
      setDocumentsState('ready')
      return () => { cancelled = true }
    }

    setDocumentsState('loading')
    const controller = new AbortController()
    void fetchDocuments(projectId, controller.signal)
      .then((nextDocuments) => {
        if (cancelled) return
        const imported = importedDocumentRef.current
        const importedDocument = imported && nextDocuments.find((document) =>
          document.sourceKey === imported.sourceKey && document.contentHash === imported.contentHash)
        setDocuments(nextDocuments)
        setSelectedApiDocId((currentId) => importedDocument?.apiDocId
          ?? (nextDocuments.some((document) => document.apiDocId === currentId)
            ? currentId
            : nextDocuments[0]?.apiDocId ?? null))
        if (importedDocument) importedDocumentRef.current = null
        setDocumentsState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = apiErrorFor(error, 'Unable to load OpenAPI documents')
        setDocuments([])
        setSelectedApiDocId(null)
        setDocumentsError(apiError)
        setDocumentsState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [documentsReload, expireSession, fetchDocuments, projectId, refreshProjects])

  useEffect(() => {
    let cancelled = false
    setApiSummariesError(null)

    if (!projectId) {
      setApiSummariesState('ready')
      return () => { cancelled = true }
    }

    setApiSummariesState('loading')
    const controller = new AbortController()
    void fetchApiSummaries(projectId, controller.signal)
      .then((nextSummaries) => {
        if (cancelled) return
        setApiSummaries(nextSummaries)
        setApiSummariesState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = apiErrorFor(error, 'Unable to load API endpoints')
        setApiSummaries([])
        setSelectedApiId(null)
        setApiSummariesError(apiError)
        setApiSummariesState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [expireSession, fetchApiSummaries, projectId, refreshProjects, apiSummariesReload])

  useEffect(() => {
    if (apiSummariesState !== 'ready') return
    if (!selectedApiDocId) {
      setSelectedApiId(null)
      return
    }

    const scopedSummaries = apiSummaries.filter((summary) => summary.apiDocId === selectedApiDocId)
    setSelectedApiId((currentId) => scopedSummaries.some((summary) => summary.apiId === currentId)
      ? currentId
      : scopedSummaries[0]?.apiId ?? null)
  }, [apiSummaries, apiSummariesState, selectedApiDocId])

  useEffect(() => {
    if (!contextTarget || apiSummariesState !== 'ready') return

    const targetApiId = contextTarget.type === 'endpoint' ? contextTarget.id : contextTarget.apiId
    const targetSummary = apiSummaries.find((summary) => (
      summary.apiId === targetApiId
      && (!contextTarget.apiDocId || summary.apiDocId === contextTarget.apiDocId)
    )) ?? apiSummaries.find((summary) => summary.apiId === targetApiId)
    if (!targetSummary) return

    setSelectedApiDocId(targetSummary.apiDocId)
    setSelectedApiId(targetSummary.apiId)
  }, [apiSummaries, apiSummariesState, contextTarget])

  useEffect(() => {
    let cancelled = false
    setApiDetail(null)
    setApiDetailError(null)

    if (!projectId || !selectedApiId) {
      setApiDetailState('idle')
      return () => { cancelled = true }
    }

    setApiDetailState('loading')
    const controller = new AbortController()
    void apiFetch<ApiMetadataDetail>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/openapi/apis/${encodeURIComponent(selectedApiId)}`,
      { signal: controller.signal },
    )
      .then((detail) => {
        if (cancelled) return
        const nextDetail = normalizeApiMetadataDetail(detail)
        setApiDetail(nextDetail)
        recordEndpoint({
          apiDocId: nextDetail.apiDocId,
          id: nextDetail.apiId,
          method: nextDetail.method,
          operationId: nextDetail.operationId,
          path: nextDetail.path,
          summary: nextDetail.summary,
        })
        activateContext({ type: 'endpoint', id: nextDetail.apiId, apiDocId: nextDetail.apiDocId })
        setApiDetailState('ready')
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        const apiError = apiErrorFor(error, 'Unable to load endpoint metadata')
        setApiDetail(null)
        setApiDetailError(apiError)
        setApiDetailState('error')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [activateContext, expireSession, projectId, recordEndpoint, refreshProjects, selectedApiId, apiDetailReload])

  useEffect(() => {
    if (!contextTarget || apiDetailState !== 'ready' || !apiDetail) return

    const targetApiId = contextTarget.type === 'endpoint' ? contextTarget.id : contextTarget.apiId
    if (apiDetail.apiId !== targetApiId) return

    if (contextTarget.type === 'testcase') {
      const targetStrategy = strategyOptions.find((option) => option.id === contextTarget.strategy)
      if (targetStrategy && strategyAvailability[targetStrategy.id]?.applicable) {
        setSelectedStrategy(targetStrategy.id)
      }

      if (contextTarget.dsl) {
        const targetRuntime: TestCaseAgentRuntime = contextTarget.generator === 'PYTHON_AGENTLAB'
          ? 'PYTHON_AGENTLAB'
          : 'JAVA_AGENT'
        setSelectedAgentRuntime(targetRuntime)
        try {
          const candidate = JSON.parse(contextTarget.dsl) as unknown
          if (!isRecord(candidate)) throw new Error('TestCase must be an object')
          if (currentUser && projectId) {
            const key = studioDraftKey(currentUser.id, projectId, {
              apiDocId: apiDetail.apiDocId, apiId: apiDetail.apiId,
              strategy: targetStrategy && strategyAvailability[targetStrategy.id]?.applicable ? targetStrategy.id : selectedStrategy,
              runtime: targetRuntime,
            })
            setDraftStorageFailed(!writeStudioDraft(key, contextTarget.dsl))
          }
          setGeneratedDsl(contextTarget.dsl)
          setValidatedTestCase(null)
          setValidatedDsl(null)
          setValidationMessage('Validate this restored TestCase before running it.')
          setGeneratedByRuntime(targetRuntime)
          setGenerationStatus(null)
          setGenerationError(null)
          setRepairAttempts(0)
        } catch {
          clearGenerationResult()
        }
      } else {
        clearGenerationResult()
      }
    }

    activateContext(contextTarget)
  }, [activateContext, apiDetail, apiDetailState, clearGenerationResult, contextTarget, strategyAvailability])

  useEffect(() => {
    if (apiDetailState !== 'ready') return
    if (selectedStrategy && strategyAvailability[selectedStrategy]?.applicable) return
    const firstApplicable = strategyOptions.find((option) => strategyAvailability[option.id]?.applicable)
    setSelectedStrategy(firstApplicable?.id ?? null)
  }, [apiDetailState, selectedStrategy, strategyAvailability])

  const selectApiDocument = (apiDocId: string) => {
    if (!documents.some((document) => document.apiDocId === apiDocId)) return
    setSelectedApiDocId(apiDocId)
  }

  const importOpenApi = useCallback(async (
    file: File,
    sourceKey: string,
    signal: AbortSignal,
  ): Promise<OpenApiImportResponse> => {
    if (!projectId) throw new ApiError('No project selected', 0, 'PROJECT_NOT_SELECTED')

    const form = new FormData()
    form.set('sourceKey', sourceKey)
    form.set('file', file)

    try {
      const response = await apiFetch<OpenApiImportResponse>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/openapi/documents`,
        { body: form, method: 'POST', signal },
      )
      importedDocumentRef.current = response
      setDocumentsReload((value) => value + 1)
      setApiSummariesReload((value) => value + 1)
      return response
    } catch (error) {
      const apiError = apiErrorFor(error, 'Unable to import OpenAPI document')
      if (apiError.status === 401) expireSession()
      if (apiError.status === 403) void refreshProjects()
      throw apiError
    }
  }, [expireSession, projectId, refreshProjects])

  const selectStrategy = (strategy: StrategyId) => {
    if (!strategyAvailability[strategy]?.applicable) return
    setSelectedStrategy(strategy)
  }

  const selectAgentRuntime = (runtime: TestCaseAgentRuntime) => {
    if (runtime === selectedAgentRuntime) return
    setSelectedAgentRuntime(runtime)
  }

  const generateTestCase = async () => {
    const strategy = selectedStrategy
    if (
      isGenerating
      || isSubmitting
      || !projectId
      || !selectedApiId
      || apiDetailState !== 'ready'
      || !apiDetail
      || !strategy
      || !strategyAvailability[strategy]?.applicable
    ) return

    generationController.current?.abort()
    const controller = new AbortController()
    generationController.current = controller
    const requestId = ++generationRequestId.current

    setGenerationStatus('GENERATING')
    setGenerationError(null)
    setGeneratedDsl('')
    setValidatedDsl(null)
    setValidationMessage(null)
    setValidatedTestCase(null)
    setGeneratedByRuntime(null)
    setRepairAttempts(0)
    setRunnerSubmission(null)
    setRunnerError(null)

    try {
      const path = `/api/v1/projects/${encodeURIComponent(projectId)}/openapi/apis/${encodeURIComponent(selectedApiId)}/testcases:generate`
      const init = {
        body: JSON.stringify({
          strategy,
        }),
        method: 'POST' as const,
        signal: controller.signal,
      }
      const response = selectedAgentRuntime === 'JAVA_AGENT'
        ? await apiFetch<GenerateTestCaseResponse>(path, init)
        : await agentApiFetch<GenerateTestCaseResponse>(path, init)
      if (controller.signal.aborted || requestId !== generationRequestId.current) return

      setGeneratedDsl(JSON.stringify(response.candidate, null, 2))
      if (draftKey) setDraftStorageFailed(!writeStudioDraft(draftKey, JSON.stringify(response.candidate, null, 2)))
      setValidatedDsl(JSON.stringify(response.candidate, null, 2))
      setValidatedTestCase(response.candidate)
      setGeneratedByRuntime(selectedAgentRuntime)
      setRepairAttempts(Math.max(0, (response.modelCalls ?? []).length - 1))
      setGenerationStatus('ACCEPTED')

      const generatedCaseId = typeof response.candidate.caseId === 'string' ? response.candidate.caseId : ''
      if (generatedCaseId) {
        const generatedCaseName = typeof response.candidate.name === 'string'
          ? response.candidate.name
          : apiDetail.operationId + ' · ' + strategy
        const generatedDslValue = JSON.stringify(response.candidate, null, 2)
        recordFinalizedTestCase({
          apiDocId: apiDetail.apiDocId,
          apiId: apiDetail.apiId,
          dsl: generatedDslValue,
          generator: selectedAgentRuntime,
          id: generatedCaseId,
          name: generatedCaseName,
          strategy,
          status: 'ACCEPTED',
        })
        activateContext({
          apiDocId: apiDetail.apiDocId,
          apiId: apiDetail.apiId,
          dsl: generatedDslValue,
          generator: selectedAgentRuntime,
          id: generatedCaseId,
          strategy,
          type: 'testcase',
        })
      }
    } catch (error: unknown) {
      if (controller.signal.aborted || requestId !== generationRequestId.current || isAbortError(error)) return
      const apiError = apiErrorFor(error, 'Unable to generate a TestCase')
      setGeneratedDsl('')
      setGeneratedByRuntime(null)
      setGenerationError(apiError.message)
      setGenerationStatus(apiError.status === 422 || apiError.code === 'A0001' ? 'REJECTED' : 'FAILED')
      if (apiError.status === 401) expireSession()
      if (apiError.status === 403) void refreshProjects()
    } finally {
      if (generationController.current === controller) generationController.current = null
    }
  }

  const editDsl = (value: string) => {
    if (draftKey) setDraftStorageFailed(!writeStudioDraft(draftKey, value))
    generationController.current?.abort()
    generationRequestId.current += 1
    setGeneratedDsl(value)
    setValidatedDsl(null)
    setValidatedTestCase(null)
    setGenerationStatus(null)
    setGenerationError(null)
    setValidationMessage('Changes require Java validation before execution.')
    setRunnerSubmission(null)
    setRunnerError(null)
  }

  const validateDsl = async () => {
    if (!projectId || !selectedApiId || isSubmitting || isGenerating) return
    generationController.current?.abort()
    const controller = new AbortController()
    generationController.current = controller
    const requestId = ++generationRequestId.current
    const snapshot = generatedDsl
    setValidatedTestCase(null)
    setValidatedDsl(null)
    setGenerationStatus('VALIDATING')
    setValidationMessage(null)
    try {
      const candidate = JSON.parse(snapshot) as unknown
      if (!isRecord(candidate)) throw new Error('TestCase must be a JSON object')
      const response = await apiFetch<{ valid: boolean; errors: { path: string; code: string; message: string }[] }>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/openapi/apis/${encodeURIComponent(selectedApiId)}/testcases:validate`,
        { body: JSON.stringify(candidate), method: 'POST', signal: controller.signal },
      )
      if (controller.signal.aborted || requestId !== generationRequestId.current) return
      if (!response.valid) {
        setGenerationStatus('REJECTED')
        setValidationMessage(response.errors.map((error) => `${error.path}: ${error.message}`).join('\n') || 'Java validation rejected this TestCase.')
        return
      }
      setValidatedTestCase(candidate)
      setValidatedDsl(snapshot)
      setGenerationStatus('ACCEPTED')
      setValidationMessage('Current TestCase passed Java validation.')
      if (typeof candidate.caseId === 'string' && apiDetail) {
        recordFinalizedTestCase({
          apiDocId: apiDetail.apiDocId, apiId: apiDetail.apiId,
          id: candidate.caseId, name: String(candidate.name ?? candidate.caseId),
          dsl: snapshot, generator: generatedByRuntime ?? selectedAgentRuntime,
          strategy: String(candidate.strategy ?? selectedStrategy ?? ''), status: 'ACCEPTED',
        })
      }
    } catch (error: unknown) {
      if (controller.signal.aborted || requestId !== generationRequestId.current) return
      setGenerationStatus('REJECTED')
      setValidationMessage(error instanceof Error ? error.message : 'Unable to validate TestCase')
      if (error instanceof ApiError && error.status === 401) expireSession()
      if (error instanceof ApiError && error.status === 403) void refreshProjects()
    } finally {
      if (generationController.current === controller) generationController.current = null
    }
  }

  const runTest = async () => {
    const request = runnerRequestForEditor(generationStatus, validatedTestCase, generatedDsl, validatedDsl)
    if (!projectId || !request || isSubmitting || submissionController.current || validatedDsl !== generatedDsl) return

    const controller = new AbortController()
    submissionController.current = controller
    const isCurrent = () => !controller.signal.aborted && currentDraftKey.current === draftKey

    setIsSubmitting(true)
    setRunnerSubmission(null)
    setRunnerError(null)
    try {
      const response = await apiFetch<RunnerBatchSubmission>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/test-batches`,
        { body: JSON.stringify(request), method: 'POST', signal: controller.signal },
      )
      if (!isCurrent()) return
      const identity = singleRunnerSubmission(response)
      setRunnerSubmission(identity)

      try {
        const run = await fetchExactRun(projectId, identity.runId, controller.signal)
        if (!isCurrent()) return
        recordRun({
          apiId: run.apiId,
          caseId: run.caseId,
          createdAt: run.createdAt,
          name: run.testCaseName,
          runId: run.runId,
          status: run.status,
        })
        activateContext({
          type: 'run',
          id: String(run.runId),
          runId: run.runId,
          caseId: run.caseId,
          apiId: run.apiId,
        })
      } catch (error: unknown) {
        if (!isCurrent()) return
        const apiError = apiErrorFor(error, 'Unable to read submitted Run')
        if (apiError.status === 401) expireSession()
        if (apiError.status === 403) void refreshProjects()
      }
    } catch (error: unknown) {
      if (!isCurrent()) return
      const apiError = apiErrorFor(error, 'Unable to submit TestCase to Java Runner')
      setRunnerError(apiError.message)
      if (apiError.status === 401) expireSession()
      if (apiError.status === 403) void refreshProjects()
    } finally {
      if (submissionController.current === controller) submissionController.current = null
      if (isCurrent()) setIsSubmitting(false)
    }
  }

  return (
    <div className="api-studio-page">
      <div className="studio-layout">
        <ApiExplorer
          apiSummaries={apiSummaries}
          apiSummariesError={apiSummariesError}
          apiSummariesState={apiSummariesState}
          currentProjectId={projectId}
          documents={documents}
          documentsError={documentsError}
          documentsState={documentsState}
          onImport={importOpenApi}
          onRetryDocuments={() => setDocumentsReload((value) => value + 1)}
          onRetryApiSummaries={() => setApiSummariesReload((value) => value + 1)}
          onSelectDocument={selectApiDocument}
          onSelectApi={setSelectedApiId}
          selectedApiDocId={selectedApiDocId}
          selectedApiId={selectedApiId}
        />
        <section className="studio-api-workspace endpoint-detail-panel panel" aria-label={ui('Endpoint Detail')}>
          {apiDetailState === 'ready' && apiDetail ? (
            <>
              <EndpointHeader
                detail={apiDetail}
                expectedResponse={expectedResponse}
                selectedStrategy={selectedStrategy}
              />
              <RequestResponsePanel
                detail={apiDetail}
                expectedResponse={expectedResponse}
                selectedStrategy={selectedStrategy}
              />
            </>
          ) : (
            <MetadataDetailState
              error={apiDetailError}
              onRetry={() => setApiDetailReload((value) => value + 1)}
              state={apiDetailState}
            />
          )}
        </section>
        <section className="studio-agent-workspace testcase-workspace-panel panel" aria-label={ui('TestCase Workspace')}>
          <TestCaseGeneratorPanel
            canGenerate={Boolean(
              projectId
              && !isSubmitting
              && selectedApiId
              && apiDetailState === 'ready'
              && apiDetail
              && selectedStrategy
              && strategyAvailability[selectedStrategy]?.applicable,
            )}
            isGenerating={isGenerating}
            onGenerate={generateTestCase}
            onRuntimeChange={selectAgentRuntime}
            onStrategyChange={selectStrategy}
            selectedAgentRuntime={selectedAgentRuntime}
            selectedStrategy={selectedStrategy}
            strategyAvailability={strategyAvailability}
          />
          <GeneratedDslPanel
            draftStorageFailed={draftStorageFailed}
            canRun={validatedDsl === generatedDsl && Boolean(runnerRequestForEditor(generationStatus, validatedTestCase, generatedDsl, validatedDsl))}
            isValidating={generationStatus === 'VALIDATING'}
            isGenerating={isGenerating}
            onEdit={editDsl}
            onValidate={() => { void validateDsl() }}
            validationMessage={validationMessage}
            dsl={generatedDsl}
            generatedBy={agentRuntimeOptions.find((option) => option.id === generatedByRuntime)?.generatedBy ?? ''}
            generationError={generationError}
            generationStatus={generationStatus}
            isSubmitting={isSubmitting}
            onRun={() => { void runTest() }}
            onViewRun={onViewRun}
            repairAttempts={repairAttempts}
            runnerError={runnerError}
            runnerSubmission={runnerSubmission}
          />
        </section>
        <ContextTrail compact onNavigate={onContextNavigate} />
      </div>
    </div>
  )
}
