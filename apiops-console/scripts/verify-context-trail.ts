import assert from 'node:assert/strict'
import { resolveActiveContext, resolveEndpointIdentityForRun, type ActiveContext, type ContextTrailCache, type ContextTrailTarget } from '../src/app/contextTrailModel.ts'

const endpointE1 = {
  id: 'E1',
  apiDocId: 'doc-1',
  operationId: 'endpointE1',
  method: 'POST',
  path: '/api/orders',
  summary: 'E1',
}
const endpointE2 = {
  id: 'E2',
  apiDocId: 'doc-2',
  operationId: 'endpointE2',
  method: 'GET',
  path: '/api/inventory',
  summary: 'E2',
}
const testCaseA = { id: 'TC-A', apiId: 'E1', apiDocId: 'doc-1', name: 'A', runIds: [101] }
const testCaseB = { id: 'TC-B', apiId: 'E1', apiDocId: 'doc-1', name: 'B', runIds: [102] }
const testCaseC = { id: 'TC-C', apiId: 'E2', apiDocId: 'doc-2', name: 'C', runIds: [103] }
const runA = { id: '101', runId: 101, caseId: 'TC-A', apiId: 'E1', name: 'Run-A', status: 'FAILED', createdAt: '1', diagnosisIds: ['diag-A'] }
const runB = { id: '102', runId: 102, caseId: 'TC-B', apiId: 'E1', name: 'Run-B', status: 'FAILED', createdAt: '2', diagnosisIds: [] }
const runC = { id: '103', runId: 103, caseId: 'TC-C', apiId: 'E2', name: 'Run-C', status: 'SUCCESS', createdAt: '3', diagnosisIds: [] }
const diagnosisA = { id: 'diag-A', agentRunId: 'agent-A', runId: 101, status: 'COMPLETED', reportId: 'report-A' }
const reportA = { id: 'report-A', reportId: 'report-A', agentRunId: 'agent-A', runId: 101 }

const cache: ContextTrailCache = {
  endpoints: [endpointE2, endpointE1],
  testCases: [testCaseC, testCaseB, testCaseA],
  runs: [runC, runB, runA],
  diagnoses: [diagnosisA],
  reports: [reportA],
}

function activeIdentity(active: ActiveContext | null) {
  if (!active) return null
  return {
    endpointId: active.endpointId,
    endpointApiDocId: active.endpointApiDocId,
    caseId: active.caseId,
    runId: active.runId,
    agentRunId: active.agentRunId,
    reportId: active.reportId,
  }
}

function targetTestCase(testCase: typeof testCaseA): ContextTrailTarget {
  return {
    type: 'testcase',
    id: testCase.id,
    apiId: testCase.apiId,
    apiDocId: testCase.apiDocId,
  }
}

function targetRun(run: typeof runA): ContextTrailTarget {
  return {
    type: 'run',
    id: run.id,
    runId: run.runId,
    caseId: run.caseId,
    apiId: run.apiId,
  }
}

const fallbackEndpoint = {
  id: 'API-001',
  apiDocId: 'doc-fallback',
  operationId: 'listProducts',
  method: 'GET',
  path: '/products',
  summary: 'List products',
}
const duplicateOperationEndpoint = {
  ...fallbackEndpoint,
  id: 'API-002',
  apiDocId: 'doc-other',
  path: '/catalog/products',
}

const exactResolution = resolveEndpointIdentityForRun('API-001', [fallbackEndpoint, duplicateOperationEndpoint])
assert.equal(exactResolution.resolution, 'EXACT_API_ID')
assert.equal(exactResolution.endpoint?.id, 'API-001')

const uniqueOperationResolution = resolveEndpointIdentityForRun('listProducts', [fallbackEndpoint])
assert.equal(uniqueOperationResolution.resolution, 'UNIQUE_OPERATION_ID')
assert.equal(uniqueOperationResolution.endpoint?.id, 'API-001')

const ambiguousOperationResolution = resolveEndpointIdentityForRun('listProducts', [fallbackEndpoint, duplicateOperationEndpoint])
assert.equal(ambiguousOperationResolution.resolution, 'AMBIGUOUS_OPERATION_ID')
assert.equal(ambiguousOperationResolution.endpoint, null)

const notFoundResolution = resolveEndpointIdentityForRun('legacyUnknownApi', [fallbackEndpoint])
assert.equal(notFoundResolution.resolution, 'NOT_FOUND')
assert.equal(notFoundResolution.endpoint, null)

const fallbackTestCase = { id: 'TC-FALLBACK', apiId: 'API-001', apiDocId: 'doc-fallback', name: 'List products', runIds: [104] }
const fallbackRun = { id: '104', runId: 104, caseId: 'TC-FALLBACK', apiId: 'listProducts', name: 'Run-fallback', status: 'SUCCESS', createdAt: '4', diagnosisIds: [] }
const fallbackCache: ContextTrailCache = {
  endpoints: [fallbackEndpoint],
  testCases: [fallbackTestCase],
  runs: [fallbackRun],
  diagnoses: [],
  reports: [],
}
const fallbackActive = resolveActiveContext(targetRun(fallbackRun), fallbackCache)
assert.deepEqual(activeIdentity(fallbackActive), {
  endpointId: 'API-001',
  endpointApiDocId: 'doc-fallback',
  caseId: 'TC-FALLBACK',
  runId: 104,
  agentRunId: null,
  reportId: null,
})
assert.equal(fallbackActive?.endpointResolution?.resolution, 'UNIQUE_OPERATION_ID')

const ambiguousTestCase = { id: 'TC-AMBIGUOUS', apiId: 'listProducts', apiDocId: '', name: 'List products historical case', runIds: [105] }
const ambiguousRun = { id: '105', runId: 105, caseId: 'TC-AMBIGUOUS', apiId: 'listProducts', name: 'Run-ambiguous', status: 'FAILED', createdAt: '5', diagnosisIds: ['diag-ambiguous'] }
const ambiguousDiagnosis = { id: 'diag-ambiguous', agentRunId: 'agent-ambiguous', runId: 105, status: 'COMPLETED', reportId: 'report-ambiguous' }
const ambiguousReport = { id: 'report-ambiguous', reportId: 'report-ambiguous', agentRunId: 'agent-ambiguous', runId: 105 }
const ambiguousLineageCache: ContextTrailCache = {
  endpoints: [fallbackEndpoint, duplicateOperationEndpoint],
  testCases: [ambiguousTestCase],
  runs: [ambiguousRun],
  diagnoses: [ambiguousDiagnosis],
  reports: [ambiguousReport],
}
const ambiguousActive = resolveActiveContext(targetRun(ambiguousRun), ambiguousLineageCache)
assert.deepEqual(activeIdentity(ambiguousActive), {
  endpointId: null,
  endpointApiDocId: null,
  caseId: 'TC-AMBIGUOUS',
  runId: 105,
  agentRunId: null,
  reportId: null,
})
assert.equal(ambiguousActive?.endpointResolution?.resolution, 'AMBIGUOUS_OPERATION_ID')
const ambiguousReportActive = resolveActiveContext({ type: 'report', id: 'report-ambiguous', reportId: 'report-ambiguous', agentRunId: 'agent-ambiguous', runId: 105 }, ambiguousLineageCache)
assert.deepEqual(activeIdentity(ambiguousReportActive), {
  endpointId: null,
  endpointApiDocId: null,
  caseId: 'TC-AMBIGUOUS',
  runId: 105,
  agentRunId: 'agent-ambiguous',
  reportId: 'report-ambiguous',
})

const notFoundTestCase = { id: 'TC-NOT-FOUND', apiId: 'legacyUnknownApi', apiDocId: '', name: 'Legacy case', runIds: [106] }
const notFoundRun = { id: '106', runId: 106, caseId: 'TC-NOT-FOUND', apiId: 'legacyUnknownApi', name: 'Run-not-found', status: 'FAILED', createdAt: '6', diagnosisIds: [] }
const notFoundCache: ContextTrailCache = {
  endpoints: [],
  testCases: [notFoundTestCase],
  runs: [notFoundRun],
  diagnoses: [],
  reports: [],
}
const notFoundActive = resolveActiveContext(targetRun(notFoundRun), notFoundCache)
assert.deepEqual(activeIdentity(notFoundActive), {
  endpointId: null,
  endpointApiDocId: null,
  caseId: 'TC-NOT-FOUND',
  runId: 106,
  agentRunId: null,
  reportId: null,
})
assert.equal(notFoundActive?.endpointResolution?.resolution, 'NOT_FOUND')

const responseOwnerContext = resolveActiveContext(targetRun(runA), cache)
assert.equal(responseOwnerContext?.runId, runA.runId)
assert.equal(responseOwnerContext?.caseId, runA.caseId)

let active = resolveActiveContext(targetTestCase(testCaseA), cache)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E1',
  endpointApiDocId: 'doc-1',
  caseId: 'TC-A',
  runId: null,
  agentRunId: null,
  reportId: null,
})

active = resolveActiveContext(targetRun(runA), cache, active)
active = resolveActiveContext({ type: 'diagnosis', id: 'diag-A', agentRunId: 'agent-A', runId: 101 }, cache, active)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E1',
  endpointApiDocId: 'doc-1',
  caseId: 'TC-A',
  runId: 101,
  agentRunId: 'agent-A',
  reportId: 'report-A',
})

active = resolveActiveContext(targetTestCase(testCaseB), cache, active)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E1',
  endpointApiDocId: 'doc-1',
  caseId: 'TC-B',
  runId: null,
  agentRunId: null,
  reportId: null,
})

active = resolveActiveContext(targetRun(runB), cache, active)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E1',
  endpointApiDocId: 'doc-1',
  caseId: 'TC-B',
  runId: 102,
  agentRunId: null,
  reportId: null,
})

active = resolveActiveContext(targetRun(runC), cache, active)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E2',
  endpointApiDocId: 'doc-2',
  caseId: 'TC-C',
  runId: 103,
  agentRunId: null,
  reportId: null,
})

active = resolveActiveContext({ type: 'report', id: 'report-A', reportId: 'report-A', agentRunId: 'agent-A', runId: 101 }, cache, active)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E1',
  endpointApiDocId: 'doc-1',
  caseId: 'TC-A',
  runId: 101,
  agentRunId: 'agent-A',
  reportId: 'report-A',
})

const duplicateDocTestCase = { id: 'TC-A', apiId: 'E1', apiDocId: 'doc-2', name: 'A from another document', runIds: [] }
const ambiguousCache: ContextTrailCache = {
  ...cache,
  testCases: [testCaseA, duplicateDocTestCase],
}
assert.deepEqual(activeIdentity(resolveActiveContext(targetRun(runA), ambiguousCache)), {
  endpointId: 'E1',
  endpointApiDocId: 'doc-1',
  caseId: 'TC-A',
  runId: 101,
  agentRunId: null,
  reportId: null,
})

active = resolveActiveContext({ type: 'endpoint', id: 'E2', apiDocId: 'doc-2' }, cache, active)
assert.deepEqual(activeIdentity(active), {
  endpointId: 'E2',
  endpointApiDocId: 'doc-2',
  caseId: null,
  runId: null,
  agentRunId: null,
  reportId: null,
})

const uncachedDiagnosis = resolveActiveContext({ type: 'diagnosis', id: 'diag-missing', agentRunId: 'agent-missing', runId: 999 }, cache)
assert.deepEqual(activeIdentity(uncachedDiagnosis), {
  endpointId: null,
  endpointApiDocId: null,
  caseId: null,
  runId: 999,
  agentRunId: 'agent-missing',
  reportId: null,
})

const uncachedReport = resolveActiveContext({ type: 'report', id: 'report-missing', reportId: 'report-missing', agentRunId: 'agent-missing', runId: 999 }, cache)
assert.deepEqual(activeIdentity(uncachedReport), {
  endpointId: null,
  endpointApiDocId: null,
  caseId: null,
  runId: 999,
  agentRunId: 'agent-missing',
  reportId: 'report-missing',
})

console.log('Context Trail active-chain branch isolation: passed')
