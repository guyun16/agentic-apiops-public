import assert from 'node:assert/strict'
import { diagnosisReportExport, reportExportFilename, reportExportMarkdown, testReportExport } from '../src/shared/reports/reportExport.ts'
import type { TestReport } from '../src/features/runs/types.ts'
import type { DiagnosisExecutionResponse } from '../src/features/diagnosis/types.ts'

const report: TestReport = {
  projectId: 41, taskId: 20, runId: 12, reportId: '../bad:name\n', status: 'ASSERTION_FAILED',
  startedAt: '2026-09-08T00:00:00Z', finishedAt: null,
  summary: { totalCases: 1, totalSteps: 1, totalAssertions: 1, passedAssertions: 0, failedAssertions: 1, failureType: 'ASSERTION_MISMATCH' },
  cases: [{ caseId: 'case', status: 'ASSERTION_FAILED', failureType: 'ASSERTION_MISMATCH', steps: [{
    stepId: 'step', status: 'ASSERTION_FAILED', failureType: 'ASSERTION_MISMATCH', responseStatusCode: 500, durationMs: null,
    assertionResults: [{ type: 'STATUS_CODE', passed: false, expected: 200, actual: 500, message: '```\n<script>test</script>' }],
    httpExchange: {
      request: { method: 'GET', url: 'http://localhost/products?token=[REDACTED]', headers: {}, body: null, bodyState: 'empty', truncated: false },
      response: { statusCode: 500, headers: {}, body: '{"count":2}', bodyState: 'captured', truncated: true },
    },
  }] }],
}
const original = JSON.stringify(report)
const document = testReportExport(report, '2026-09-08T01:00:00Z')
assert.deepEqual(JSON.parse(JSON.stringify(document)).testReport, report)
assert.match(reportExportFilename(document, 'json'), /^[a-zA-Z0-9_-]+\.json$/)
assert.equal(JSON.stringify(report), original, 'Export must not mutate the source report')
const markdown = reportExportMarkdown(document, 'zh-CN')
assert.match(markdown, /# 测试报告/)
assert.match(markdown, /ASSERTION_FAILED/)
assert.match(markdown, /````json/, 'Data containing a fence must not break out of its code block')
assert.match(markdown, /未提供/)
assert.match(markdown, /"passed": false/)
assert.match(markdown, /"httpExchange"/)
assert.match(markdown, /"truncated": true/, 'Exports must preserve incomplete snapshot markers')
assert.match(markdown, /### 用例 case/)
assert.match(markdown, /#### 步骤 step/)
assert.match(markdown, /运行: 12/)
const largeReport = structuredClone(report)
largeReport.cases[0].steps[0].assertionResults[0].message = '` '.repeat(150_000)
assert.doesNotThrow(() => reportExportMarkdown(testReportExport(largeReport), 'zh-CN'))

const execution = {
  status: 'FAILED', runtime: 'PYTHON_AGENTLAB', implementation: 'REAL', workflow: 'diagnosis',
  provider: 'provider', model: 'model', projectId: 41, runId: 12, taskId: 20, reportId: 'test-id',
  agentRunId: 'agent-1', traceId: 'trace-1', workflowId: 'workflow-1', testReport: report,
  report: null, failure: { code: 'WORKER_INTERRUPTED', message: 'interrupted' },
  toolIntentId: null, toolCallId: null, steps: [], context: { evidenceItems: 0, contextCharacters: 0, modelCalls: 0, toolCalls: 0 },
  approvalRequest: { arguments: { token: 'not-for-export' } },
} as unknown as DiagnosisExecutionResponse
const failed = diagnosisReportExport(execution, 'now')
assert.equal(failed.diagnosis?.report, null)
assert.equal(failed.diagnosis?.failure?.code, 'WORKER_INTERRUPTED')
assert.equal(JSON.stringify(failed).includes('not-for-export'), false)
assert.match(reportExportMarkdown(failed, 'en-US'), /Structured report: Not provided/)

execution.report = {
  schemaVersion: '0.1.0', reportId: 'diagnosis-2', agentRunId: 'agent-1', projectId: 41, runId: 12,
  failureType: 'ASSERTION_MISMATCH', summary: '<img src=x> Summary', traceId: 'trace-1',
  sufficientEvidence: false, recommendedChecks: ['Check service'], limitations: ['No logs'],
  rootCauseHypotheses: [{ statement: 'Possible failure', confidence: 'LOW', evidenceRefs: [{ itemId: 'evidence-7' }] }],
}
const diagnosis = diagnosisReportExport(execution, 'now')
const diagnosisMd = reportExportMarkdown(diagnosis, 'en-US')
assert.match(diagnosisMd, /evidence\\-7/)
assert.match(diagnosisMd, /Sufficient evidence: false/)
assert.match(diagnosisMd, /No logs/)
assert.match(diagnosisMd, /\\<img src=x\\>/)
assert.equal(diagnosis.source.reportId, 'test-id')
assert.equal(diagnosis.diagnosis?.report?.reportId, 'diagnosis-2')
console.log('Report exports preserve source identity, failures, evidence, null values, and safe formatting: passed')
