import assert from 'node:assert/strict'
import { findRecoverableDiagnosis } from '../src/features/diagnosis-execution/recoveryModel.ts'
import type { DiagnosisRunSummary } from '../src/features/diagnosis/types.ts'

function saved(id: string, status: DiagnosisRunSummary['status'], overrides: Partial<DiagnosisRunSummary> = {}): DiagnosisRunSummary {
  return { agentRunId: id, status, projectId: 41, runId: 701, taskId: 1, traceId: id, workflowId: id,
    provider: 'test', model: 'test', apiId: null, reportId: 'r', diagnosisReportId: null, summary: null,
    createdAt: '2026-09-08T10:00:00Z', updatedAt: '2026-09-08T10:00:00Z', ...overrides }
}

const failed = saved('failed', 'FAILED')
const completed = saved('completed', 'COMPLETED', { createdAt: '2026-09-08T11:00:00Z' })
const approval = saved('approval', 'APPROVAL_REQUIRED')
const running = saved('running', 'RUNNING', { createdAt: '2026-09-08T12:00:00Z' })
assert.equal(findRecoverableDiagnosis([], '41', 701), null)
assert.equal(findRecoverableDiagnosis([completed], '42', 701), null)
assert.equal(findRecoverableDiagnosis([completed], '41', 702), null)
assert.equal(findRecoverableDiagnosis([failed, completed], '41', 701)?.agentRunId, 'completed')
// A newer terminal attempt must not hide an approval that still needs attention.
assert.equal(findRecoverableDiagnosis([completed, approval], '41', 701)?.agentRunId, 'approval')
assert.equal(findRecoverableDiagnosis([approval, running], '41', 701)?.agentRunId, 'running')
// GET refresh updates updatedAt; that must not make an older attempt the newest.
assert.equal(findRecoverableDiagnosis([{ ...failed, updatedAt: '2026-09-09T10:00:00Z' }, completed], '41', 701)?.agentRunId, 'completed')
assert.equal(findRecoverableDiagnosis([failed], '41', 701)?.status, 'FAILED')
assert.equal(findRecoverableDiagnosis([saved('rejected', 'REJECTED')], '41', 701)?.status, 'REJECTED')
console.log('Diagnosis recovery checks passed: project/run isolation, active recovery, stable selection, retryable terminal states.')
