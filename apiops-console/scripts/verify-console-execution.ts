import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveActiveContext, type ContextTrailCache } from '../src/app/contextTrailModel.ts'
import {
  runnerRequestForValidatedTestCase,
  singleRunnerSubmission,
} from '../src/features/api-studio/types.ts'

const candidate = { caseId: 'case-1', projectId: 101, apiId: 'api-1', steps: [{}] }
assert.deepEqual(runnerRequestForValidatedTestCase('ACCEPTED', candidate), { testCases: [candidate] })
assert.equal(runnerRequestForValidatedTestCase('REJECTED', candidate), null)
assert.equal(runnerRequestForValidatedTestCase('FAILED', candidate), null)
assert.equal(runnerRequestForValidatedTestCase(null, candidate), null)

const submission = singleRunnerSubmission({
  batchId: 'batch-java',
  taskIds: [201],
  runIds: [301],
})
assert.deepEqual(submission, { batchId: 'batch-java', taskId: 201, runId: 301 })
assert.throws(() => singleRunnerSubmission({ batchId: 'bad', taskIds: [], runIds: [] }))

const cache: ContextTrailCache = {
  endpoints: [{
    id: 'api-1',
    apiDocId: 'doc-1',
    operationId: 'createOrder',
    method: 'POST',
    path: '/orders',
    summary: 'Create order',
  }],
  testCases: [{
    id: 'case-1',
    apiId: 'api-1',
    apiDocId: 'doc-1',
    name: 'Create order succeeds',
    runIds: [submission.runId],
  }],
  runs: [{
    id: String(submission.runId),
    runId: submission.runId,
    caseId: 'case-1',
    apiId: 'api-1',
    name: 'Create order succeeds',
    status: 'PENDING',
    createdAt: null,
    diagnosisIds: [],
  }],
  diagnoses: [],
  reports: [],
}
const active = resolveActiveContext({
  type: 'run',
  id: String(submission.runId),
  runId: submission.runId,
  caseId: 'case-1',
  apiId: 'api-1',
}, cache)
assert.deepEqual({
  endpointId: active?.endpointId,
  caseId: active?.caseId,
  runId: active?.runId,
  agentRunId: active?.agentRunId,
}, { endpointId: 'api-1', caseId: 'case-1', runId: 301, agentRunId: null })

const studioSource = readFileSync(new URL('../src/features/api-studio/ApiStudioPage.tsx', import.meta.url), 'utf8')
assert.match(studioSource, /\/test-batches/)
const dslPanelSource = readFileSync(new URL('../src/features/api-studio/components/GeneratedDslPanel.tsx', import.meta.url), 'utf8')
assert.match(dslPanelSource, /onViewRun\(runnerSubmission\.runId\)/)
const runsSource = readFileSync(new URL('../src/features/runs/RunsPage.tsx', import.meta.url), 'utf8')
assert.match(runsSource, /fetchExactRun\(nextProjectId, targetRunId/)
const diagnosisSource = readFileSync(new URL('../src/features/diagnosis/DiagnosisPage.tsx', import.meta.url), 'utf8')
assert.match(diagnosisSource, /fetchExactRun\(String\(projectId\), nextExecution\.runId/)
assert.doesNotMatch(diagnosisSource, /apiFetch<RunSummaryResponse\[\]>/)
const shellSource = readFileSync(new URL('../src/components/layout/AppShell.tsx', import.meta.url), 'utf8')
assert.match(shellSource, /navigate\('runs', runId\)/)

console.log('Console execution and durable Run lineage: passed')
