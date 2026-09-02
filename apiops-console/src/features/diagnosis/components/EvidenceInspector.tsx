import { Clipboard, Database, FileCheck2, FileWarning, KeyRound, Link2, Search } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import {
  buildExecutionAssertionDisplayGroups,
  buildExecutionStepDisplayProjection,
  type ExecutionStepDisplayItem,
} from '../../../shared/presentation/executionStepProjection'
import { formatValue } from '../../runs/presentation'
import type { TestReportCase, TestReportStep } from '../../runs/types'
import type { DiagnosisExecutionResponse } from '../types'

type EvidenceTab = 'Key Evidence' | 'All Evidence' | 'Execution Identity'

type EvidenceInspectorProps = {
  execution: DiagnosisExecutionResponse | null
}

function copyValue(value: string) {
  void navigator.clipboard?.writeText(value)
}

function failedAssertionCount(testCase: TestReportCase) {
  return testCase.steps.reduce((total, step) => total + step.assertionResults.filter((assertion) => !assertion.passed).length, 0)
}

function isFailedCase(testCase: TestReportCase) {
  return testCase.status !== 'SUCCESS' || testCase.failureType !== 'NONE'
}

function statusClass(status: string) {
  return status.toLowerCase().replace(/_/g, '-')
}

function DisplayStepEvidence({ item }: { item: ExecutionStepDisplayItem<TestReportStep> }) {
  const { ui } = useConsoleLanguage()
  const step = item.representativeStep
  const assertionGroups = buildExecutionAssertionDisplayGroups(item)
  const failedAssertionGroups = assertionGroups.filter((group) => !group.representativeAssertion.passed)
  const stepLabel = item.kind === 'repeated'
    ? `${ui('Repeated executions')} ×${item.count}`
    : step.stepId

  return (
    <div className="diagnosis-report-evidence-step">
      <div className="diagnosis-evidence-step-heading"><code>{stepLabel}</code><span>{step.status} · {step.failureType}</span></div>
      {item.kind === 'repeated' ? (
        <small>{ui('Total duration')}: {item.totalDurationMs === null ? '—' : `${item.totalDurationMs} ms`} · {ui('Average duration')}: {item.averageDurationMs === null ? '—' : `${item.averageDurationMs} ms`}</small>
      ) : null}
      {step.responseStatusCode !== null ? <small>{ui('HTTP Status')}: {step.responseStatusCode} · {ui('Duration')}: {step.durationMs === null ? '—' : `${step.durationMs} ms`}</small> : null}
      {failedAssertionGroups.map((group) => (
        <small className="diagnosis-evidence-assertion" key={`${group.representativeAssertion.type}-${group.rawAssertions[0].assertionIndex}`}>
          {group.representativeAssertion.type}{group.count > 1 ? ` ×${group.count}` : ''}: {ui('Expected')} {formatValue(group.representativeAssertion.expected)} · {ui('Actual')} {formatValue(group.representativeAssertion.actual)}{group.representativeAssertion.message ? ` · ${group.representativeAssertion.message}` : ''}
        </small>
      ))}
      {item.kind === 'repeated' ? (
        <details className="diagnosis-raw-executions">
          <summary>{ui('Raw executions')} ({item.count})</summary>
          <div className="diagnosis-raw-execution-list">
            {item.rawSteps.map((rawStep, index) => (
              <div className="diagnosis-raw-execution-row" key={`${rawStep.stepId}-${index}`}>
                <code>{rawStep.stepId}</code>
                <span>{rawStep.durationMs === null ? '—' : `${rawStep.durationMs} ms`}</span>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  )
}

export function EvidenceInspector({ execution }: EvidenceInspectorProps) {
  const { ui } = useConsoleLanguage()
  const [activeTab, setActiveTab] = useState<EvidenceTab>('Key Evidence')
  const testReport = execution?.testReport ?? null
  const failedCases = testReport?.cases.filter(isFailedCase) ?? []
  const visibleCases = activeTab === 'Key Evidence' ? failedCases : testReport?.cases ?? []
  const identity = execution ? [
    { label: 'projectId', value: String(execution.projectId), Icon: Link2 },
    { label: 'runId', value: String(execution.runId), Icon: Link2 },
    { label: 'taskId', value: String(execution.taskId), Icon: KeyRound },
    { label: 'testReportId', value: execution.testReport.reportId, Icon: FileCheck2 },
    { label: 'diagnosisReportId', value: execution.report?.reportId ?? '—', Icon: FileCheck2 },
    { label: 'agentRunId', value: execution.agentRunId, Icon: KeyRound },
    { label: 'traceId', value: execution.traceId || '—', Icon: Link2 },
    { label: 'workflowId', value: execution.workflowId, Icon: Search },
    ...(execution.toolIntentId ? [{ label: 'toolIntentId', value: execution.toolIntentId, Icon: Search }] : []),
    ...(execution.toolCallId ? [{ label: 'toolCallId', value: execution.toolCallId, Icon: Clipboard }] : []),
  ] satisfies Array<{ label: string; value: string; Icon: LucideIcon }> : []

  return (
    <aside className="diagnosis-inspector panel" aria-label={ui('Evidence and context inspector')}>
      <header className="diagnosis-inspector-header">
        <div>
          <span className="diagnosis-eyebrow">{ui('Investigation details')}</span>
          <h2>{ui('Evidence & Context')}</h2>
        </div>
        <span className="diagnosis-inspector-count">{testReport?.summary.failedAssertions ?? 0} {ui('failed assertions')}</span>
      </header>

      <nav className="diagnosis-evidence-tabs" aria-label={ui('Execution evidence views')} role="tablist">
        {(['Key Evidence', 'All Evidence', 'Execution Identity'] as EvidenceTab[]).map((tab) => (
          <button
            aria-selected={activeTab === tab}
            className={activeTab === tab ? 'is-active' : undefined}
            key={tab}
            onClick={() => setActiveTab(tab)}
            role="tab"
            type="button"
          >
            {ui(tab)}
          </button>
        ))}
      </nav>

      <div className="diagnosis-inspector-scroll">
        {!execution ? (
          <div className="diagnosis-inspector-empty" role="status">
            <FileWarning size={18} strokeWidth={1.8} />
            <strong>{ui('Select a diagnosis execution from History.')}</strong>
            <p>{ui('Evidence and context appear here when a real DiagnosisReport is selected.')}</p>
          </div>
        ) : activeTab === 'Execution Identity' ? (
          <section className="diagnosis-inspector-section">
            <div className="diagnosis-inspector-section-heading"><h3>{ui('Execution Identity')}</h3><span>{ui('Traceable IDs')}</span></div>
            <div className="diagnosis-identity-list">
              {identity.map(({ Icon, label, value }) => (
                <div className="diagnosis-identity-row" key={label}>
                  <span><Icon size={14} strokeWidth={1.8} />{label}</span>
                  <code title={value}>{value}</code>
                  <button aria-label={`${ui('Copy')} ${label}`} onClick={() => copyValue(value)} type="button"><Clipboard size={13} strokeWidth={1.8} /></button>
                </div>
              ))}
            </div>
          </section>
        ) : (
          <>
            <section className="diagnosis-inspector-section diagnosis-inspector-source">
              <div className="diagnosis-inspector-section-heading"><h3>{ui('Java TestReport')}</h3><span>{testReport?.cases.length ?? 0} {ui('cases')}</span></div>
              <div className="diagnosis-source-list">
                <div className="diagnosis-source-row">
                  <span className="diagnosis-source-icon"><FileCheck2 size={16} strokeWidth={1.8} /></span>
                  <span><strong>{testReport?.reportId}</strong><small>{testReport?.status} · {testReport?.summary.failureType}</small></span>
                  <span className="diagnosis-source-status">{testReport?.summary.failedAssertions ?? 0}</span>
                </div>
              </div>
            </section>

            <section className="diagnosis-inspector-section">
              <div className="diagnosis-inspector-section-heading">
                <h3>{activeTab === 'Key Evidence' ? ui('Failed case evidence') : ui('TestReport cases')}</h3>
                <span>{visibleCases.length} / {testReport?.cases.length ?? 0}</span>
              </div>
              <div className="diagnosis-evidence-grid">
                {visibleCases.map((testCase) => {
                  const displayCase = buildExecutionStepDisplayProjection([testCase]).cases[0]

                  return (
                  <article className="diagnosis-evidence-card" key={testCase.caseId}>
                    <div className="diagnosis-evidence-card-heading">
                      <div><span className="diagnosis-subheading">{ui('Case')}</span><strong>{testCase.caseId}</strong></div>
                      <span className={`diagnosis-fail-label diagnosis-fail-label-${statusClass(testCase.status)}`}>{testCase.status}</span>
                    </div>
                    <div className="diagnosis-evidence-values">
                      <div><span>{ui('Failure Type')}</span><code>{testCase.failureType}</code></div>
                      <div><span>{ui('Steps')}</span><strong>{testCase.steps.length}</strong></div>
                      <div><span>{ui('Failed Assertions')}</span><strong className={failedAssertionCount(testCase) ? 'diagnosis-actual-fail' : undefined}>{failedAssertionCount(testCase)}</strong></div>
                    </div>
                    <div className="diagnosis-evidence-step-list">
                      {displayCase.items.map((item) => <DisplayStepEvidence item={item} key={`${item.representativeStep.stepId}-${item.kind}`} />)}
                    </div>
                  </article>
                  )
                })}
                {!visibleCases.length ? <p className="diagnosis-empty-state">{activeTab === 'Key Evidence' ? ui('No failed case facts are present in this TestReport.') : ui('No case facts are present in this TestReport.')}</p> : null}
              </div>
            </section>
          </>
        )}

        {execution ? (
          <>
            <section className="diagnosis-inspector-section">
              <div className="diagnosis-inspector-section-heading"><h3>{ui('Tool Activity')}</h3><span>{execution.context.toolCalls} {ui('calls')}</span></div>
              <div className="diagnosis-tool-list">
                {execution.toolIntentId ? (
                  <div className="diagnosis-tool-row"><span className="diagnosis-tool-name"><Search size={14} strokeWidth={1.8} />toolIntentId</span><code>{execution.toolIntentId}</code></div>
                ) : null}
                {execution.toolCallId ? (
                  <div className="diagnosis-tool-row"><span className="diagnosis-tool-name"><Search size={14} strokeWidth={1.8} />toolCallId</span><code>{execution.toolCallId}</code></div>
                ) : null}
                {!execution.toolIntentId && !execution.toolCallId ? <p className="diagnosis-empty-state">NOT_REQUESTED</p> : null}
              </div>
            </section>

            <section className="diagnosis-inspector-section">
              <div className="diagnosis-inspector-section-heading"><h3>{ui('Context')}</h3><span>{ui('Collected inputs')}</span></div>
              <div className="diagnosis-context-grid">
                <div><Database size={15} strokeWidth={1.8} /><span>{ui('Evidence Items')}</span><strong>{execution.context.evidenceItems}</strong></div>
                <div><Clipboard size={15} strokeWidth={1.8} /><span>{ui('Context Characters')}</span><strong>{execution.context.contextCharacters}</strong></div>
                <div><KeyRound size={15} strokeWidth={1.8} /><span>{ui('Model Calls')}</span><strong>{execution.context.modelCalls}</strong></div>
                <div><Search size={15} strokeWidth={1.8} /><span>{ui('Tool Calls')}</span><strong>{execution.context.toolCalls}</strong></div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </aside>
  )
}
