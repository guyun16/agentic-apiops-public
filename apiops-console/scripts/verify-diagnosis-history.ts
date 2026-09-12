import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  diagnosisHistoryPath,
  filterDiagnosisHistory,
  resolveDiagnosisSelection,
  sortDiagnosisHistory,
} from '../src/features/diagnosis/diagnosisHistoryModel.ts'
import type { DiagnosisRunStatus, DiagnosisRunSummary } from '../src/features/diagnosis/types.ts'

function run(
  agentRunId: string,
  status: DiagnosisRunStatus,
  updatedAt: string,
  summary: string | null = null,
): DiagnosisRunSummary {
  return {
    status,
    provider: 'DeepSeek',
    model: 'deepseek-chat',
    projectId: 41,
    runId: 701,
    taskId: 301,
    agentRunId,
    traceId: `trace:${agentRunId}`,
    workflowId: `workflow:${agentRunId}`,
    apiId: 'orders.get',
    reportId: 'test-report:701',
    diagnosisReportId: summary ? `report:${agentRunId}` : null,
    summary,
    createdAt: '2026-08-23T12:00:00Z',
    updatedAt,
  }
}

const older = run('agent_run:older', 'FAILED', '2026-08-23T12:01:00Z')
const selected = run(
  'agent_run:studio',
  'COMPLETED',
  '2026-08-23T12:03:00Z',
  'The orders endpoint returned HTTP 500.',
)
const approval = run('agent_run:approval', 'APPROVAL_REQUIRED', '2026-08-23T12:02:00Z')
const history = sortDiagnosisHistory([older, selected, approval])

// The page reads the dedicated durable Diagnosis endpoint, not runtime evaluation state.
assert.equal(diagnosisHistoryPath(41), '/api/v1/diagnosis/runs?projectId=41')
assert.equal(diagnosisHistoryPath(41).includes('/evaluation/runtime/'), false)
const pageSource = fs.readFileSync(
  new URL('../src/features/diagnosis/DiagnosisPage.tsx', import.meta.url),
  'utf8',
)
assert.match(pageSource, /diagnosisHistoryPath\(projectId\)/)
assert.doesNotMatch(pageSource, /\/api\/v1\/evaluation\/runtime\/runs/)
assert.match(pageSource, /\/api\/v1\/diagnosis\/runs\/\$\{encodeURIComponent\(selectedAgentRunId\)\}/)

// Repository update order drives the initial Sidebar selection.
assert.deepEqual(history.map((item) => item.agentRunId), [
  'agent_run:studio',
  'agent_run:approval',
  'agent_run:older',
])
assert.equal(resolveDiagnosisSelection(null, history), 'agent_run:studio')

// A Studio-provided agentRunId wins when it belongs to the current Project history.
assert.equal(resolveDiagnosisSelection('agent_run:approval', history), 'agent_run:approval')
assert.equal(resolveDiagnosisSelection('agent_run:another-project', history), 'agent_run:studio')
assert.equal(resolveDiagnosisSelection('agent_run:studio', []), null)

// Filtering and search stay local to the SQLite-backed response.
assert.deepEqual(
  filterDiagnosisHistory(history, 'FAILED', '').map((item) => item.agentRunId),
  ['agent_run:older'],
)
assert.deepEqual(
  filterDiagnosisHistory(history, 'ALL', 'HTTP 500').map((item) => item.agentRunId),
  ['agent_run:studio'],
)

console.log('Diagnosis history verification passed.')
