import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {
  countRuntimeRuns,
  evaluationCoverage,
  filterRuntimeRuns,
  formatRuntimeMetric,
  resolveRuntimeEndpoint,
  resolveSelectedRunId,
  runtimeContextTarget,
  runtimeNavigation,
  selectedRuntimeRun,
  validationSummary,
} from '../src/features/evaluation/evaluationViewModel.ts'
import type { ContextTrailEndpoint } from '../src/app/ContextTrailContext.tsx'
import type { RunSummary } from '../src/features/runs/types.ts'
import type { RuntimeMetric, RuntimeRunDetail, RuntimeRunStatus, RuntimeRunSummary } from '../src/features/evaluation/types.ts'

const statuses: RuntimeRunStatus[] = ['COMPLETED', 'RUNNING', 'APPROVAL_REQUIRED', 'FAILED', 'REJECTED']

function run(status: RuntimeRunStatus, index: number): RuntimeRunSummary {
  return {
    agentRunId: `agent_run:${index}`,
    traceId: `trace:${index}`,
    executionType: index % 2 ? 'DIAGNOSIS' : 'TESTCASE_GENERATION',
    status,
    provider: index === 3 ? 'Qwen' : 'DeepSeek',
    model: `model-${index}`,
    projectId: 41,
    apiId: `api-${index}`,
    runId: index % 2 ? 700 + index : null,
    reportId: index === 1 ? 'report:1' : null,
    startedAt: `2026-08-29T01:0${index}:00Z`,
    finishedAt: status === 'RUNNING' || status === 'APPROVAL_REQUIRED' ? null : `2026-08-29T01:0${index}:02Z`,
  }
}

const runs = statuses.map(run)

// Behaviour: filtering and visible-run selection.
const counts = countRuntimeRuns(runs)
assert.equal(counts.ALL, 5)
statuses.forEach((status) => assert.equal(counts[status], 1))
assert.deepEqual(filterRuntimeRuns(runs, 'COMPLETED', '').map((item) => item.status), ['COMPLETED'])
assert.deepEqual(filterRuntimeRuns(runs, 'APPROVAL_REQUIRED', '').map((item) => item.status), ['APPROVAL_REQUIRED'])
assert.deepEqual(filterRuntimeRuns(runs, 'ALL', 'qwen').map((item) => item.agentRunId), ['agent_run:3'])
assert.deepEqual(filterRuntimeRuns(runs, 'ALL', 'trace:4').map((item) => item.agentRunId), ['agent_run:4'])

assert.equal(resolveSelectedRunId('agent_run:3', runs), 'agent_run:3')
assert.equal(resolveSelectedRunId('agent_run:3', [runs[0]]), 'agent_run:0')
assert.equal(resolveSelectedRunId('agent_run:3', []), null)

const valueMetric: RuntimeMetric = { status: 'VALUE', value: 2400, unit: 'ms', reason: null }
const unknownMetric: RuntimeMetric = { status: 'UNKNOWN', value: null, unit: null, reason: 'not recorded' }
const notApplicableMetric: RuntimeMetric = { status: 'NOT_APPLICABLE', value: null, unit: null, reason: 'not applicable' }
const errorMetric: RuntimeMetric = { status: 'ERROR', value: null, unit: null, reason: 'invalid source fact' }

// Behaviour: absence and error states never collapse into numeric zero.
assert.equal(formatRuntimeMetric(valueMetric, { compactDuration: true }), '2.40 s')
assert.equal(formatRuntimeMetric(unknownMetric), 'UNKNOWN')
assert.equal(formatRuntimeMetric(notApplicableMetric), 'N/A')
assert.equal(formatRuntimeMetric(errorMetric), 'ERROR')
assert.notEqual(formatRuntimeMetric(unknownMetric), '0')
assert.notEqual(formatRuntimeMetric(notApplicableMetric), '0')
assert.notEqual(formatRuntimeMetric(errorMetric), '0')

function detail(overrides: Partial<RuntimeRunDetail> = {}): RuntimeRunDetail {
  return {
    ...run('COMPLETED', 1),
    executionType: 'DIAGNOSIS',
    metrics: {
      validJson: notApplicableMetric,
      schemaValid: notApplicableMetric,
      contractAccepted: notApplicableMetric,
      wallClockLatencyMs: valueMetric,
      modelLatencyMs: unknownMetric,
      promptTokens: unknownMetric,
      completionTokens: unknownMetric,
      totalTokens: unknownMetric,
      cost: unknownMetric,
    },
    toolCounts: { attempted: 0, success: 0, failed: 0, denied: 0, timeout: 0, unknown: 0, notApplicable: 1 },
    safetyStatus: 'UNKNOWN',
    safetyOutcome: null,
    safetyReason: 'not recorded',
    traceRecordCount: 2,
    failureCode: null,
    failureMessage: null,
    evaluationResult: null,
    judgeResults: [],
    ...overrides,
  }
}

// Behaviour: the workspace only exposes detail for the selected Agent Run.
const detailA = detail()
const detailB = detail({ agentRunId: 'agent_run:B', traceId: 'trace:B' })
assert.equal(selectedRuntimeRun(detailB, 'agent_run:B')?.agentRunId, 'agent_run:B')
assert.equal(selectedRuntimeRun(detailA, 'agent_run:B'), null)
assert.equal(selectedRuntimeRun(null, 'agent_run:B'), null)

// Behaviour: Diagnosis validation preserves N/A, UNKNOWN, and ERROR.
assert.equal(validationSummary(detail()).label, 'N/A')
assert.equal(validationSummary(detail({ metrics: { ...detail().metrics, validJson: unknownMetric } })).label, 'UNKNOWN')
assert.equal(validationSummary(detail({ metrics: { ...detail().metrics, validJson: errorMetric } })).label, 'ERROR')

// Behaviour: persisted formal results are visible; absence remains NOT EVALUATED, never zero/failure.
const persistedDetail = detail({
  evaluationResult: {
    evaluation_id: 'evaluation:formal',
    case_id: 'case:formal',
    trace_id: 'trace:1',
    agent_run_id: 'agent_run:1',
    ground_truth_id: 'gt:formal',
    ground_truth_version: 'v1',
    evaluator_version: 'rule-based-v1',
    metrics: [{ metric: 'valid_json', status: 'VALUE', value: 1, unit: null, reason: null, details: [] }],
  },
  judgeResults: [{
    judge_result_id: 'judge_result:formal',
    judge_case_id: 'judge_case:formal',
    trace_id: 'trace:1',
    agent_run_id: 'agent_run:1',
    dimension: 'DIAGNOSIS_QUALITY',
    score: 0.8,
    reason: 'Supported by the reference.',
    configuration: {
      rubric: { rubric_id: 'diagnosis-quality', version: 'v1', dimension: 'DIAGNOSIS_QUALITY', criteria: ['Use the reference.'] },
      prompt: { name: 'judge', version: 'v1' },
      model_identity: { provider: 'judge-provider', model: 'judge-model', deployment: null, version: 'judge-v1' },
    },
  }],
})
assert.equal(evaluationCoverage(persistedDetail).deterministic.label, 'AVAILABLE')
assert.match(evaluationCoverage(persistedDetail).deterministic.reason, /evaluation:formal/)
assert.equal(evaluationCoverage(persistedDetail).judge.label, 'AVAILABLE')
assert.equal(persistedDetail.evaluationResult?.metrics[0].value, 1)
assert.equal(persistedDetail.judgeResults[0].score, 0.8)
assert.deepEqual(evaluationCoverage(detail()), {
  deterministic: { label: 'NOT EVALUATED', reason: 'Ground Truth unavailable', tone: 'neutral' },
  judge: { label: 'NOT EVALUATED', reason: 'No persisted JudgeResult', tone: 'neutral' },
})

// Behaviour: navigation is emitted only from real identities.
const diagnosisNavigation = runtimeNavigation(detail())
assert.equal(diagnosisNavigation.runId, 701)
assert.equal(diagnosisNavigation.traceId, 'trace:1')
assert.equal(diagnosisNavigation.diagnosisAgentRunId, 'agent_run:1')
assert.equal(runtimeNavigation(run('COMPLETED', 2)).diagnosisAgentRunId, null)
assert.deepEqual(
  runtimeNavigation({ ...run('COMPLETED', 2), runId: null, traceId: '' }),
  { diagnosisAgentRunId: null, runId: null, traceId: null },
)

const owningRun: RunSummary = {
  runId: 701,
  caseId: 'case-1',
  apiId: 'api-1',
  testCaseName: 'Order failure',
  status: 'ASSERTION_FAILED',
  failureType: 'ASSERTION_MISMATCH',
  createdAt: '2026-08-29T01:00:00Z',
  startedAt: '2026-08-29T01:00:00Z',
  finishedAt: '2026-08-29T01:00:02Z',
  durationMs: 2000,
}

// Behaviour: Context Trail targets require a resolved Java Run and Diagnosis identity.
assert.equal(runtimeContextTarget(detail(), owningRun)?.type, 'report')
assert.equal(runtimeContextTarget(detail({ reportId: null }), owningRun)?.type, 'diagnosis')
assert.equal(runtimeContextTarget(detail({ executionType: 'TESTCASE_GENERATION' }), owningRun), null)
assert.equal(runtimeContextTarget(detail(), { ...owningRun, runId: 999 }), null)
assert.equal(runtimeContextTarget(detail(), null), null)

const endpoints: ContextTrailEndpoint[] = [
  { id: 'api-1', apiDocId: 'doc-1', operationId: 'getOrder', method: 'GET', path: '/orders/{id}', summary: null },
  { id: 'api-2', apiDocId: 'doc-1', operationId: 'listOrders', method: 'GET', path: '/orders', summary: null },
]
assert.equal(resolveRuntimeEndpoint('api-1', endpoints)?.id, 'api-1')
assert.equal(resolveRuntimeEndpoint('listOrders', endpoints)?.id, 'api-2')
assert.equal(resolveRuntimeEndpoint('missing', endpoints), null)
assert.equal(resolveRuntimeEndpoint('duplicate', [
  { ...endpoints[0], id: 'api-3', operationId: 'duplicate' },
  { ...endpoints[1], id: 'api-4', operationId: 'duplicate' },
]), null)

// Architecture guards: keep Runtime Evaluation isolated from Benchmark and reuse shell wiring.
const evaluationRoot = path.resolve('src/features/evaluation')
const evaluationSources = fs.readdirSync(evaluationRoot, { recursive: true })
  .filter((name): name is string => typeof name === 'string' && /\.(ts|tsx)$/.test(name))
  .map((name) => fs.readFileSync(path.join(evaluationRoot, name), 'utf8'))
  .join('\n')
assert.match(evaluationSources, /\/api\/v1\/evaluation\/runtime\/summary/)
assert.match(evaluationSources, /\/api\/v1\/evaluation\/runtime\/runs/)
assert.doesNotMatch(evaluationSources, /\/api\/v1\/benchmark/)
assert.match(evaluationSources, /<ContextTrail/)
assert.match(evaluationSources, /result\.metrics\.map/)
assert.match(evaluationSources, /detail\.judgeResults\.map/)
assert.match(evaluationSources, /result\.ground_truth_version/)
assert.match(evaluationSources, /judge\.configuration\.rubric\.version/)
assert.match(evaluationSources, /judge\.configuration\.prompt\.version/)
assert.match(evaluationSources, /judge\.configuration\.model_identity/)
assert.doesNotMatch(evaluationSources, /No Agent Run query contract is available/)

const appShell = fs.readFileSync(path.resolve('src/components/layout/AppShell.tsx'), 'utf8')
assert.match(appShell, /onViewRun=\{viewRunReport\}/)
assert.match(appShell, /onViewTrace=\{viewTrace\}/)
assert.match(appShell, /onViewDiagnosis=\{viewDiagnosisResult\}/)
assert.match(appShell, /onContextNavigate=\{handleContextNavigation\}/)

console.log('Evaluation persisted results, absence semantics, navigation, context gating, and API boundaries: passed')
