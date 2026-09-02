export type ContextTrailEndpoint = {
  id: string
  apiDocId: string
  operationId: string
  method: string
  path: string
  summary: string | null
}

export type EndpointIdentityResolutionKind =
  | 'EXACT_API_ID'
  | 'UNIQUE_OPERATION_ID'
  | 'AMBIGUOUS_OPERATION_ID'
  | 'NOT_FOUND'

export type EndpointIdentityResolution = {
  endpoint: ContextTrailEndpoint | null
  resolution: EndpointIdentityResolutionKind
  sourceValue: string
}

export type ContextTrailTestCase = {
  id: string
  apiId: string
  apiDocId: string
  name: string
  strategy?: string
  generator?: string
  dsl?: string
  runIds: number[]
}

export type ContextTrailRun = {
  id: string
  runId: number
  caseId: string
  apiId: string
  name: string
  status: string
  createdAt: string
  diagnosisIds: string[]
}

export type ContextTrailDiagnosis = {
  id: string
  agentRunId: string
  runId: number
  status: string
  reportId: string | null
}

export type ContextTrailReport = {
  id: string
  reportId: string
  agentRunId: string
  runId: number
}

export type ContextTrailTarget =
  | { type: 'endpoint'; id: string; apiDocId: string }
  | {
      type: 'testcase'
      id: string
      apiId: string
      apiDocId: string
      strategy?: string
      dsl?: string
      generator?: string
    }
  | { type: 'run'; id: string; runId: number; caseId: string; apiId: string }
  | { type: 'diagnosis'; id: string; agentRunId: string; runId: number }
  | { type: 'report'; id: string; reportId: string; agentRunId: string; runId: number }

/** The canonical selection state. Entity records remain cached separately. */
export type ActiveContext = {
  endpointId: string | null
  endpointApiDocId: string | null
  endpointResolution: EndpointIdentityResolution | null
  caseId: string | null
  runId: number | null
  agentRunId: string | null
  reportId: string | null
}

export type ContextTrailCache = {
  endpoints: ContextTrailEndpoint[]
  testCases: ContextTrailTestCase[]
  runs: ContextTrailRun[]
  diagnoses: ContextTrailDiagnosis[]
  reports: ContextTrailReport[]
}

export type ContextReadModelGap = {
  targetType: Extract<ContextTrailTarget, { type: 'run' | 'diagnosis' | 'report' }>['type']
  runId: number | null
  agentRunId: string | null
  reportId: string | null
  missing: Array<'endpoint' | 'testcase' | 'run' | 'diagnosis' | 'report'>
  reason: string
}

const emptyActiveContext: ActiveContext = {
  endpointId: null,
  endpointApiDocId: null,
  endpointResolution: null,
  caseId: null,
  runId: null,
  agentRunId: null,
  reportId: null,
}

function uniqueEndpointRecords(endpoints: ContextTrailEndpoint[]) {
  const seen = new Set<string>()
  return endpoints.filter((endpoint) => {
    const key = `${endpoint.id}::${endpoint.apiDocId}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function resolveEndpointIdentityForRun(
  runApiId: string | number,
  endpoints: ContextTrailEndpoint[],
): EndpointIdentityResolution {
  const sourceValue = String(runApiId)
  const uniqueEndpoints = uniqueEndpointRecords(endpoints)
  const canonicalMatches = uniqueEndpoints.filter((endpoint) => endpoint.id === sourceValue)
  if (canonicalMatches.length === 1) {
    return { endpoint: canonicalMatches[0], resolution: 'EXACT_API_ID', sourceValue }
  }
  if (canonicalMatches.length > 1) {
    return { endpoint: null, resolution: 'AMBIGUOUS_OPERATION_ID', sourceValue }
  }

  const operationMatches = uniqueEndpoints.filter((endpoint) => endpoint.operationId === sourceValue)
  if (operationMatches.length === 1) {
    return { endpoint: operationMatches[0], resolution: 'UNIQUE_OPERATION_ID', sourceValue }
  }
  if (operationMatches.length > 1) {
    return { endpoint: null, resolution: 'AMBIGUOUS_OPERATION_ID', sourceValue }
  }
  return { endpoint: null, resolution: 'NOT_FOUND', sourceValue }
}

function exactEndpointResolution(endpoint: ContextTrailEndpoint, sourceValue = endpoint.id): EndpointIdentityResolution {
  return { endpoint, resolution: 'EXACT_API_ID', sourceValue }
}

function findTestCase(cache: ContextTrailCache, id: string, apiId: string, apiDocId: string) {
  return cache.testCases.find((testCase) => (
    testCase.id === id
    && testCase.apiId === apiId
    && testCase.apiDocId === apiDocId
  )) ?? null
}

function findUniqueTestCaseForRun(
  cache: ContextTrailCache,
  run: Pick<ContextTrailRun, 'caseId' | 'apiId'> | null,
  endpointResolution: EndpointIdentityResolution,
) {
  if (!run) return null
  const expectedApiId = endpointResolution.endpoint?.id ?? run.apiId
  const expectedApiDocId = endpointResolution.endpoint?.apiDocId ?? null
  const matches = cache.testCases.filter((testCase) => (
    testCase.id === run.caseId
    && testCase.apiId === expectedApiId
    && (!expectedApiDocId || testCase.apiDocId === expectedApiDocId)
  ))
  return matches.length === 1 ? matches[0] : null
}

function findRun(cache: ContextTrailCache, target: Extract<ContextTrailTarget, { type: 'run' }>) {
  return cache.runs.find((run) => (
    run.runId === target.runId
    && run.caseId === target.caseId
    && run.apiId === target.apiId
  )) ?? null
}

function findDiagnosis(cache: ContextTrailCache, agentRunId: string, runId: number) {
  return cache.diagnoses.find((diagnosis) => diagnosis.agentRunId === agentRunId && diagnosis.runId === runId) ?? null
}

function findReport(cache: ContextTrailCache, reportId: string, agentRunId: string, runId: number) {
  return cache.reports.find((report) => (
    report.reportId === reportId
    && report.agentRunId === agentRunId
    && report.runId === runId
  )) ?? null
}

function activeContextForEndpoint(
  endpoint: Pick<ContextTrailEndpoint, 'id' | 'apiDocId'>,
  resolvedEndpoint: ContextTrailEndpoint | null,
): ActiveContext {
  return {
    ...emptyActiveContext,
    endpointId: endpoint.id,
    endpointApiDocId: endpoint.apiDocId,
    endpointResolution: resolvedEndpoint ? exactEndpointResolution(resolvedEndpoint) : null,
  }
}

function activeContextForTestCase(
  testCase: Pick<ContextTrailTestCase, 'id' | 'apiId' | 'apiDocId'>,
  endpoint: ContextTrailEndpoint | null,
  run: ContextTrailRun | null,
  endpointResolution: EndpointIdentityResolution | null,
  diagnosis: Pick<ContextTrailDiagnosis, 'agentRunId'> | null,
  report: Pick<ContextTrailReport, 'reportId'> | null,
): ActiveContext {
  return {
    endpointId: endpoint?.id ?? null,
    endpointApiDocId: endpoint?.apiDocId ?? null,
    endpointResolution,
    caseId: testCase.id,
    runId: run?.runId ?? null,
    agentRunId: diagnosis?.agentRunId ?? null,
    reportId: report?.reportId ?? null,
  }
}

function activeContextForRun(
  run: Pick<ContextTrailRun, 'runId' | 'caseId' | 'apiId'>,
  testCase: ContextTrailTestCase | null,
  endpoint: ContextTrailEndpoint | null,
  endpointResolution: EndpointIdentityResolution,
  diagnosis: Pick<ContextTrailDiagnosis, 'agentRunId'> | null,
  report: Pick<ContextTrailReport, 'reportId'> | null,
): ActiveContext {
  return {
    endpointId: endpoint?.id ?? null,
    endpointApiDocId: endpoint?.apiDocId ?? null,
    endpointResolution,
    caseId: testCase?.id ?? run.caseId,
    runId: run.runId,
    agentRunId: diagnosis?.agentRunId ?? null,
    reportId: report?.reportId ?? null,
  }
}

function activeContextForLineage(
  run: ContextTrailRun | null,
  testCase: ContextTrailTestCase | null,
  endpoint: ContextTrailEndpoint | null,
  runId: number,
  agentRunId: string | null,
  reportId: string | null,
  endpointResolution: EndpointIdentityResolution | null,
): ActiveContext {
  return {
    endpointId: endpoint?.id ?? null,
    endpointApiDocId: endpoint?.apiDocId ?? null,
    endpointResolution,
    caseId: testCase?.id ?? run?.caseId ?? null,
    runId,
    agentRunId,
    reportId,
  }
}

/**
 * Resolve one target into a branch-consistent active selection.
 * It never uses the current endpoint, array order, or recency to infer a parent.
 */
export function resolveActiveContext(
  target: ContextTrailTarget,
  cache: ContextTrailCache,
  previousActiveContext: ActiveContext | null = null,
): ActiveContext | null {
  if (target.type === 'endpoint') {
    const resolvedEndpoint = uniqueEndpointRecords(cache.endpoints).find((endpoint) => (
      endpoint.id === target.id && endpoint.apiDocId === target.apiDocId
    )) ?? null
    return activeContextForEndpoint(target, resolvedEndpoint)
  }

  if (target.type === 'testcase') {
    const testCase = findTestCase(cache, target.id, target.apiId, target.apiDocId) ?? target
    const endpointResolution = resolveEndpointIdentityForRun(target.apiId, cache.endpoints)
    const endpoint = endpointResolution.endpoint
    const sameTestCase = previousActiveContext?.caseId === target.id
      && previousActiveContext.endpointId === target.apiId
      && (!previousActiveContext.endpointApiDocId || previousActiveContext.endpointApiDocId === target.apiDocId)
    const previousRunApiId = previousActiveContext?.endpointResolution?.sourceValue ?? target.apiId
    const run = sameTestCase && previousActiveContext?.runId !== null && previousActiveContext?.runId !== undefined
      ? cache.runs.find((item) => (
        item.runId === previousActiveContext.runId
        && item.caseId === target.id
        && item.apiId === previousRunApiId
      )) ?? null
      : null
    const diagnosis = run && sameTestCase && previousActiveContext?.agentRunId
      ? findDiagnosis(cache, previousActiveContext.agentRunId, run.runId)
      : null
    const report = diagnosis && sameTestCase && previousActiveContext?.reportId
      ? findReport(cache, previousActiveContext.reportId, diagnosis.agentRunId, diagnosis.runId)
      : null
    return activeContextForTestCase(
      testCase,
      endpoint,
      run,
      run ? previousActiveContext?.endpointResolution ?? endpointResolution : endpointResolution,
      diagnosis,
      report,
    )
  }

  if (target.type === 'run') {
    const run = findRun(cache, target) ?? target
    const endpointResolution = resolveEndpointIdentityForRun(run.apiId, cache.endpoints)
    const testCase = findUniqueTestCaseForRun(cache, run, endpointResolution)
    const endpoint = endpointResolution.endpoint
    const sameRun = previousActiveContext?.runId === run.runId
    const diagnosis = sameRun && previousActiveContext?.agentRunId
      ? findDiagnosis(cache, previousActiveContext.agentRunId, run.runId)
      : null
    const report = diagnosis && sameRun && previousActiveContext?.reportId
      ? findReport(cache, previousActiveContext.reportId, diagnosis.agentRunId, run.runId)
      : null
    return activeContextForRun(run, testCase, endpoint, endpointResolution, diagnosis, report)
  }

  if (target.type === 'diagnosis') {
    const diagnosis = findDiagnosis(cache, target.agentRunId, target.runId)
    const run = cache.runs.find((item) => item.runId === target.runId) ?? null
    const endpointResolution = run ? resolveEndpointIdentityForRun(run.apiId, cache.endpoints) : null
    const testCase = findUniqueTestCaseForRun(cache, run, endpointResolution ?? { endpoint: null, resolution: 'NOT_FOUND', sourceValue: '' })
    const endpoint = endpointResolution?.endpoint ?? null
    const report = diagnosis?.reportId
      ? findReport(cache, diagnosis.reportId, diagnosis.agentRunId, diagnosis.runId)
      : null
    return activeContextForLineage(
      run,
      testCase,
      endpoint,
      target.runId,
      diagnosis?.agentRunId ?? target.agentRunId,
      report?.reportId ?? null,
      endpointResolution,
    )
  }

  const report = findReport(cache, target.reportId, target.agentRunId, target.runId)
  const diagnosis = findDiagnosis(cache, target.agentRunId, target.runId)
  const run = cache.runs.find((item) => item.runId === target.runId) ?? null
  const endpointResolution = run ? resolveEndpointIdentityForRun(run.apiId, cache.endpoints) : null
  const testCase = findUniqueTestCaseForRun(cache, run, endpointResolution ?? { endpoint: null, resolution: 'NOT_FOUND', sourceValue: '' })
  const endpoint = endpointResolution?.endpoint ?? null
  return activeContextForLineage(
    run,
    testCase,
    endpoint,
    target.runId,
    diagnosis?.agentRunId ?? target.agentRunId,
    report?.reportId ?? target.reportId,
    endpointResolution,
  )
}
