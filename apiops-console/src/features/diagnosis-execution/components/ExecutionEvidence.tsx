import { Clipboard, Database, FileCheck2, Info, KeyRound, Link2, Search, Server, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { DiagnosisExecutionResponse } from '../../diagnosis/types'
import {
  buildExecutionAssertionDisplayGroups,
  buildExecutionStepDisplayProjection,
  type ExecutionAssertionDisplayGroup,
  type ExecutionStepDisplayItem,
} from '../../../shared/presentation/executionStepProjection'
import type { RunSummary, TestReport, TestReportAssertion, TestReportStep } from '../../runs/types'
import type { DiagnosisRuntime } from './DiagnosisRuntimeSelector'

type EvidenceTab = 'TestReport' | 'Assertion Mismatch / Failure' | 'Execution Identity' | 'Environment / Runtime'

type ExecutionEvidenceProps = {
  execution: DiagnosisExecutionResponse | null
  projectId: number | string | null
  run: RunSummary | null
  runtime: DiagnosisRuntime
  testReport: TestReport | null
}

function displayValue(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function copyValue(value: string) {
  if (value === '—' || value === 'not created') return
  void navigator.clipboard?.writeText(value)
}

type DisplayStepReference = {
  caseId: string
  item: ExecutionStepDisplayItem<TestReportStep>
}

function displayStepReferences(report: TestReport): DisplayStepReference[] {
  return buildExecutionStepDisplayProjection(report.cases).cases.flatMap(({ caseId, items }) => items.map((item) => ({ caseId, item })))
}

type DisplayAssertionFailure = {
  assertion: TestReportAssertion
  caseId: string
  group: ExecutionAssertionDisplayGroup<TestReportStep>
  item: ExecutionStepDisplayItem<TestReportStep>
}

function failedAssertions(report: TestReport | null): DisplayAssertionFailure[] {
  if (!report) return []
  return displayStepReferences(report).flatMap(({ caseId, item }) => buildExecutionAssertionDisplayGroups(item)
    .filter((group) => !group.representativeAssertion.passed)
    .map((group) => ({
      assertion: group.representativeAssertion,
      caseId,
      group,
      item,
    })))
}

function stepFailures(report: TestReport | null): DisplayStepReference[] {
  if (!report) return []
  return displayStepReferences(report).filter(({ item }) => {
    const step = item.representativeStep
    return step.failureType !== 'NONE'
      && !buildExecutionAssertionDisplayGroups(item).some((group) => !group.representativeAssertion.passed)
  })
}

function stepDisplayLabel(item: ExecutionStepDisplayItem<TestReportStep>, ui: (value: string) => string) {
  return item.kind === 'repeated'
    ? `${ui('Repeated executions')} ×${item.count}`
    : item.representativeStep.stepId
}

function RawExecutionDetails({ item }: { item: ExecutionStepDisplayItem<TestReportStep> }) {
  const { ui } = useConsoleLanguage()
  if (item.kind !== 'repeated') return null

  return (
    <details className="diagnosis-raw-executions">
      <summary>{ui('Raw executions')} ({item.count})</summary>
      <div className="diagnosis-raw-execution-list">
        {item.rawSteps.map((step, index) => (
          <div className="diagnosis-raw-execution-row" key={`${step.stepId}-${index}`}>
            <code>{step.stepId}</code>
            <span>{step.durationMs === null ? '—' : `${step.durationMs} ms`}</span>
          </div>
        ))}
      </div>
    </details>
  )
}

function StepFacts({ item }: { item: ExecutionStepDisplayItem<TestReportStep> }) {
  const { ui } = useConsoleLanguage()
  const step = item.representativeStep
  return (
    <div className="diagnosis-evidence-step-facts">
      <span>{ui('Step')} <strong>{stepDisplayLabel(item, ui)}</strong></span>
      {item.kind === 'repeated' ? <span>{ui('Execution count')} <strong>{item.count}</strong></span> : null}
      <span>{ui('Status')} <strong>{step.status}</strong></span>
      <span>{ui('Failure Type')} <strong>{step.failureType}</strong></span>
      {step.responseStatusCode !== null ? <span>{ui('HTTP Status')} <strong>{step.responseStatusCode}</strong></span> : null}
      {item.kind === 'repeated' ? <span>{ui('Total duration')} <strong>{item.totalDurationMs === null ? '—' : `${item.totalDurationMs} ms`}</strong></span> : null}
    </div>
  )
}

export function ExecutionEvidence({ execution, projectId, run, runtime, testReport }: ExecutionEvidenceProps) {
  const { ui } = useConsoleLanguage()
  const [activeTab, setActiveTab] = useState<EvidenceTab>('TestReport')
  const activeExecution = runtime === 'PYTHON_AGENTLAB' ? execution : null
  const report = activeExecution?.testReport ?? testReport
  const mismatches = useMemo(() => failedAssertions(report), [report])
  const failures = useMemo(() => stepFailures(report), [report])

  useEffect(() => {
    setActiveTab('TestReport')
  }, [run?.runId])

  const identity = activeExecution ? [
    { label: 'projectId', value: String(activeExecution.projectId), Icon: Link2 },
    { label: 'runId', value: String(activeExecution.runId), Icon: KeyRound },
    { label: 'taskId', value: String(activeExecution.taskId), Icon: KeyRound },
    { label: 'reportId', value: activeExecution.reportId, Icon: FileCheck2 },
    { label: 'agentRunId', value: activeExecution.agentRunId, Icon: KeyRound },
    { label: 'traceId', value: activeExecution.traceId, Icon: Link2 },
    { label: 'workflowId', value: activeExecution.workflowId, Icon: Link2 },
    { label: 'toolIntentId', value: activeExecution.toolIntentId ?? '—', Icon: Search },
    { label: 'toolCallId', value: activeExecution.toolCallId ?? 'not created', Icon: Clipboard },
  ] : run ? [
    { label: 'projectId', value: projectId === null ? '—' : String(projectId), Icon: Link2 },
    { label: 'runId', value: String(run.runId), Icon: KeyRound },
    { label: 'apiId', value: run.apiId, Icon: Link2 },
    { label: 'agentRunId', value: '—', Icon: KeyRound },
    { label: 'reportId', value: report?.reportId ?? '—', Icon: FileCheck2 },
  ] : []

  const tabs: Array<{ key: EvidenceTab; label: string; count?: number }> = [
    { key: 'TestReport', label: 'TestReport', count: report?.cases.length },
    { key: 'Assertion Mismatch / Failure', label: 'Assertion Mismatch / Failure', count: mismatches.length + failures.length || undefined },
    { key: 'Execution Identity', label: 'Execution Identity', count: identity.length || undefined },
    { key: 'Environment / Runtime', label: 'Environment / Runtime', count: 1 },
  ]

  return (
    <aside className="diagnosis-execution-panel diagnosis-evidence-panel diagnosis-studio-supporting-evidence panel" aria-labelledby="execution-evidence-title">
      <header className="diagnosis-execution-panel-header">
        <span className="diagnosis-execution-eyebrow">3. {ui('Supporting Evidence')}</span>
        <h2 id="execution-evidence-title">{ui('Supporting Evidence')}</h2>
      </header>

      {activeExecution ? (
        <div className="diagnosis-execution-context-grid">
          <div><Search size={15} strokeWidth={1.8} /><span>{ui('Evidence Items')}</span><strong>{activeExecution.context.evidenceItems}</strong></div>
          <div><Database size={15} strokeWidth={1.8} /><span>{ui('Context Characters')}</span><strong>{activeExecution.context.contextCharacters}</strong></div>
          <div><KeyRound size={15} strokeWidth={1.8} /><span>{ui('Model Calls')}</span><strong>{activeExecution.context.modelCalls}</strong></div>
          <div><Clipboard size={15} strokeWidth={1.8} /><span>{ui('Tool Calls')}</span><strong>{activeExecution.context.toolCalls}</strong></div>
        </div>
      ) : null}

      <nav className="diagnosis-evidence-tabs diagnosis-studio-evidence-tabs" aria-label={ui('Execution evidence views')}>
        {tabs.map((tab) => (
          <button aria-selected={activeTab === tab.key} className={activeTab === tab.key ? 'is-active' : undefined} key={tab.key} onClick={() => setActiveTab(tab.key)} role="tab" type="button">
            {ui(tab.label)}{tab.count ? ` (${tab.count})` : ''}
          </button>
        ))}
      </nav>

      {activeTab === 'TestReport' ? (
        <section className="diagnosis-evidence-subsection">
          <div className="diagnosis-evidence-section-title"><h3>{ui('Java TestReport')}</h3><span>{report ? `${report.cases.length} ${ui('cases')}` : ui('Not loaded')}</span></div>
          {report ? (
            <div className="diagnosis-execution-evidence-list">
              {buildExecutionStepDisplayProjection(report.cases).cases.map(({ items, sourceCase: testCase }) => (
                <article className={`diagnosis-execution-evidence-card ${testCase.status === 'SUCCESS' ? 'is-success' : 'is-danger'}`} key={testCase.caseId}>
                  <div className="diagnosis-execution-evidence-card-title"><Database size={17} strokeWidth={1.8} /><strong>{testCase.caseId}</strong><span>{ui(testCase.status)}</span></div>
                  <p>{ui('Failure Type')}: {testCase.failureType} · {testCase.steps.length} {ui('steps')}</p>
                  {items.map((item) => {
                    const failedAssertionGroups = buildExecutionAssertionDisplayGroups(item).filter((group) => !group.representativeAssertion.passed)

                    return (
                    <div className="diagnosis-report-evidence-step" key={`${testCase.caseId}-${item.representativeStep.stepId}-${item.kind}`}>
                      <StepFacts item={item} />
                      {failedAssertionGroups.map((group) => <small key={`${item.representativeStep.stepId}-${group.representativeAssertion.type}-${group.rawAssertions[0].assertionIndex}`}>{group.representativeAssertion.type}{group.count > 1 ? ` ×${group.count}` : ''}: expected {displayValue(group.representativeAssertion.expected)}, actual {displayValue(group.representativeAssertion.actual)}</small>)}
                      <RawExecutionDetails item={item} />
                    </div>
                    )
                  })}
                </article>
              ))}
            </div>
          ) : <p className="diagnosis-execution-muted">{ui('The selected run TestReport is loading or unavailable.')}</p>}
        </section>
      ) : null}

      {activeTab === 'Assertion Mismatch / Failure' ? (
        <section className="diagnosis-evidence-subsection">
          <div className="diagnosis-evidence-section-title"><h3>{ui('Assertion Mismatch / Failure')}</h3><TriangleAlert size={14} strokeWidth={1.8} /></div>
          {mismatches.length || failures.length ? (
            <div className="diagnosis-evidence-failure-list">
              {mismatches.map(({ assertion, caseId, group, item }, index) => (
                <article className="diagnosis-evidence-failure" key={`${caseId}-${item.representativeStep.stepId}-assertion-${group.representativeAssertion.type}-${index}`}>
                  <div><TriangleAlert size={15} strokeWidth={1.8} /><strong>{caseId} · {stepDisplayLabel(item, ui)}</strong><span>{assertion.type}{group.count > 1 ? ` ×${group.count}` : ''}</span></div>
                  <p>{assertion.message ?? ui('Assertion did not pass.')}</p>
                  <code>expected: {displayValue(assertion.expected)} · actual: {displayValue(assertion.actual)}</code>
                  <RawExecutionDetails item={item} />
                </article>
              ))}
              {failures.map(({ caseId, item }) => (
                <article className="diagnosis-evidence-failure" key={`${caseId}-${item.representativeStep.stepId}-${item.kind}-failure`}>
                  <div><TriangleAlert size={15} strokeWidth={1.8} /><strong>{caseId} · {stepDisplayLabel(item, ui)}</strong><span>{item.representativeStep.failureType}{item.count > 1 ? ` ×${item.count}` : ''}</span></div>
                  <p>{ui('Failure recorded by Java TestReport.')}</p>
                  <RawExecutionDetails item={item} />
                </article>
              ))}
            </div>
          ) : <p className="diagnosis-execution-muted">{ui('No assertion mismatches or failure facts are recorded.')}</p>}
        </section>
      ) : null}

      {activeTab === 'Execution Identity' ? (
        <section className="diagnosis-evidence-subsection">
          <div className="diagnosis-evidence-section-title"><h3>{ui('Execution Identity')}</h3><Info size={14} strokeWidth={1.8} /></div>
          <div className="diagnosis-execution-identity-list">
            {identity.map(({ Icon, label, value }) => (
              <div key={label}>
                <span><Icon size={14} strokeWidth={1.8} />{ui(label)}</span>
                <code title={value}>{value}</code>
                <button aria-label={`${ui('Copy')} ${label}`} disabled={value === '—' || value === 'not created'} onClick={() => copyValue(value)} type="button"><Clipboard size={14} strokeWidth={1.8} /></button>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {activeTab === 'Environment / Runtime' ? (
        <section className="diagnosis-evidence-subsection">
          <div className="diagnosis-evidence-section-title"><h3>{ui('Environment / Runtime')}</h3><Server size={14} strokeWidth={1.8} /></div>
          <div className="diagnosis-runtime-environment-list">
            <div><span>{ui('Execution authority')}</span><strong>Java Platform</strong></div>
            <div><span>{ui('Diagnosis runtime')}</span><strong>{activeExecution?.runtime ?? (runtime === 'PYTHON_AGENTLAB' ? 'Python AgentLab' : 'Java Platform')}</strong></div>
            {activeExecution ? (
              <>
                <div><span>{ui('Provider')}</span><strong>{activeExecution.provider}</strong></div>
                <div><span>{ui('Workflow')}</span><strong>{activeExecution.workflow}</strong></div>
                <div><span>{ui('Implementation')}</span><strong>{activeExecution.implementation}</strong></div>
                <div><span>{ui('Model')}</span><strong>{activeExecution.model}</strong></div>
              </>
            ) : runtime === 'JAVA_PLATFORM' ? (
              <div className="diagnosis-runtime-environment-unavailable"><span>{ui('Status')}</span><strong>{ui('Browser execution not wired')}</strong></div>
            ) : (
              <div className="diagnosis-runtime-environment-unavailable"><span>{ui('Status')}</span><strong>{ui('Metadata appears after Start Diagnosis')}</strong></div>
            )}
          </div>
        </section>
      ) : null}
    </aside>
  )
}
