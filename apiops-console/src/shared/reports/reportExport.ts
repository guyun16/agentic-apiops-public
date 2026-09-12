import type { DiagnosisExecutionResponse } from '../../features/diagnosis/types'
import type { TestReport } from '../../features/runs/types'

export type ReportExport = {
  schemaVersion: '1.0'
  kind: 'test-report' | 'diagnosis-report'
  exportedAt: string
  source: { projectId: number; runId: number; reportId: string; agentRunId?: string; traceId?: string }
  testReport: TestReport
  diagnosis: Pick<DiagnosisExecutionResponse, 'status' | 'runtime' | 'provider' | 'model' | 'workflowId' | 'report' | 'failure'> | null
}

export function testReportExport(report: TestReport, exportedAt = new Date().toISOString()): ReportExport {
  return { schemaVersion: '1.0', kind: 'test-report', exportedAt,
    source: { projectId: report.projectId, runId: report.runId, reportId: report.reportId },
    testReport: report, diagnosis: null }
}

export function diagnosisReportExport(execution: DiagnosisExecutionResponse, exportedAt = new Date().toISOString()): ReportExport {
  const { status, runtime, provider, model, workflowId, report, failure } = execution
  return { schemaVersion: '1.0', kind: 'diagnosis-report', exportedAt,
    source: { projectId: execution.projectId, runId: execution.runId, reportId: execution.reportId,
      agentRunId: execution.agentRunId, traceId: execution.traceId },
    testReport: execution.testReport, diagnosis: { status, runtime, provider, model, workflowId, report, failure } }
}

export function reportExportFilename(document: ReportExport, format: 'json' | 'md') {
  const identity = `${document.kind}-project-${document.source.projectId}-run-${document.source.runId}-${document.source.agentRunId || document.source.reportId}`
  return `${identity.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 160)}.${format}`
}

// Fence lengths are derived from the data so report text cannot terminate a block.
function jsonBlock(value: unknown) {
  const text = JSON.stringify(value, null, 2)
  let fenceLength = 3
  for (const match of text.matchAll(/`+/g)) fenceLength = Math.max(fenceLength, match[0].length + 1)
  const fence = '`'.repeat(fenceLength)
  return `${fence}json\n${text}\n${fence}`
}

function plain(value: unknown) {
  return String(value).replace(/[\\`*_{}[\]<>#+.!|~-]/g, '\\$&').replace(/\r?\n/g, '\n\n')
}

export function reportExportMarkdown(document: ReportExport, language: string) {
  const zh = language === 'zh-CN'
  const label = (cn: string, en: string) => zh ? cn : en
  const missing = label('未提供', 'Not provided')
  const report = document.testReport
  const lines = [
    `# ${document.kind === 'test-report' ? label('测试报告', 'Test report') : label('诊断报告', 'Diagnosis report')}`,
    `${label('导出时间', 'Exported at')}: ${plain(document.exportedAt)}`,
    `${label('项目', 'Project')}: ${document.source.projectId} · ${label('运行', 'Run')}: ${document.source.runId}`,
    `${label('来源报告', 'Source report')}: ${plain(document.source.reportId)}`,
    label('此文件是导出时已加载数据的快照；未提供的数据不会推断或补造。', 'This file captures the loaded data at export time; missing data is not inferred.'),
  ]
  if (document.diagnosis) {
    const diagnosis = document.diagnosis
    const result = diagnosis.report
    lines.push(`## ${label('诊断结果', 'Diagnosis result')}`,
      `${label('状态', 'Status')}: ${plain(diagnosis.status)}`,
      `${label('诊断运行', 'Agent Run')}: ${plain(document.source.agentRunId ?? missing)} · ${label('追踪', 'Trace')}: ${plain(document.source.traceId || missing)}`,
      `${label('模型', 'Model')}: ${plain(diagnosis.provider)} / ${plain(diagnosis.model)}`,
      `${label('结构化报告', 'Structured report')}: ${result ? plain(result.reportId) : missing}`,
      `${label('失败信息', 'Failure')}:`, jsonBlock(diagnosis.failure),
      `### ${label('结论', 'Summary')}`, result ? plain(result.summary) : missing,
      `${label('证据充分', 'Sufficient evidence')}: ${result ? String(result.sufficientEvidence) : missing}`,
      `### ${label('根因假设与证据引用', 'Root cause hypotheses and evidence references')}`)
    if (result?.rootCauseHypotheses.length) {
      result.rootCauseHypotheses.forEach((hypothesis, index) => lines.push(
        `#### ${index + 1}. ${plain(hypothesis.confidence)}`, plain(hypothesis.statement),
        `${label('证据引用', 'Evidence references')}: ${hypothesis.evidenceRefs.length ? hypothesis.evidenceRefs.map((ref) => plain(ref.itemId)).join(', ') : missing}`))
    } else lines.push(missing)
    lines.push(`### ${label('建议检查', 'Recommended checks')}`, ...(result?.recommendedChecks.length ? result.recommendedChecks.map((item) => `- ${plain(item)}`) : [missing]),
      `### ${label('限制', 'Limitations')}`, ...(result?.limitations.length ? result.limitations.map((item) => `- ${plain(item)}`) : [missing]))
  }
  lines.push(`## ${label('测试执行', 'Test execution')}`, `${label('状态', 'Status')}: ${plain(report.status)}`,
    `${label('开始', 'Started')}: ${plain(report.startedAt)} · ${label('结束', 'Finished')}: ${plain(report.finishedAt ?? missing)}`,
    `${label('摘要', 'Summary')}:`, jsonBlock(report.summary))
  for (const testCase of report.cases) {
    lines.push(`### ${label('用例', 'Case')} ${plain(testCase.caseId)}`, `${plain(testCase.status)} / ${plain(testCase.failureType)}`)
    for (const step of testCase.steps) lines.push(`#### ${label('步骤', 'Step')} ${plain(step.stepId)}`, jsonBlock(step))
  }
  if (!report.cases.length) lines.push(label('没有记录用例结果。', 'No case results recorded.'))
  // Retain all source fields, including evidence identity and nullable values, for later review.
  lines.push(`## ${label('完整导出数据', 'Complete export data')}`, jsonBlock(document))
  return `${lines.join('\n\n')}\n`
}

export function downloadReport(document: ReportExport, format: 'json' | 'md', language: string) {
  const content = format === 'json' ? `${JSON.stringify(document, null, 2)}\n` : reportExportMarkdown(document, language)
  const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' }))
  const link = window.document.createElement('a')
  link.href = url
  link.download = reportExportFilename(document, format)
  window.document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
