import { Clipboard, Clock3, Database, FileCheck2, ScanSearch, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { ReportExportButtons } from '../../../shared/reports/ReportExportButtons'
import { testReportExport } from '../../../shared/reports/reportExport'
import {
  buildExecutionAssertionDisplayGroups,
  buildExecutionStepDisplayProjection,
  executionStepDisplayKey,
  type ExecutionStepDisplayCase,
  type ExecutionStepDisplayItem,
} from '../../../shared/presentation/executionStepProjection'
import { formatDuration, formatTime, runTimeline } from '../presentation'
import { isDiagnosableStatus, type RunLiveState, type RunProgress, type RunSummary, type RunTab, type TestReport, type TestReportCase, type TestReportStep } from '../types'
import { RunAssertions } from './RunAssertions'
import { RunRequest } from './RunRequest'
import { RunResponse } from './RunResponse'
import { RunStatusBadge } from './RunStatusBadge'
import { ExecutionSummary } from './ExecutionSummary'
import { RunTimeline } from './RunTimeline'

const tabs: RunTab[] = ['Summary', 'Test Report', 'Timeline']
type ReportTab = 'Overview' | 'Request' | 'Response' | 'Assertions'
const reportTabs: ReportTab[] = ['Overview', 'Request', 'Response', 'Assertions']

type ReportStatus = 'idle' | 'loading' | 'ready' | 'unavailable' | 'error'

type DisplayCase = ExecutionStepDisplayCase<TestReportStep, TestReportCase>
type RepeatedStepItem = Extract<ExecutionStepDisplayItem<TestReportStep>, { kind: 'repeated' }>

function TestReportHierarchy({ cases, onSelectItem, selectedItemKey, title = 'Test Report' }: {
  cases: DisplayCase[]
  onSelectItem: (caseId: string, item: ExecutionStepDisplayItem<TestReportStep>) => void
  selectedItemKey: string | null
  title?: string
}) {
  const { ui } = useConsoleLanguage()

  return (
    <section className="test-report-hierarchy" aria-labelledby="test-report-title">
      <div className="run-overview-heading">
        <div>
          <h3 id="test-report-title">{ui(title)}</h3>
          <p>{ui(title === 'Cases' ? 'Case → Step' : 'Run → Case → Step → Assertion')}</p>
        </div>
        <FileCheck2 size={20} strokeWidth={1.8} />
      </div>
      <div className="test-report-tree">
        {cases.length ? cases.map((displayCase) => {
          const reportCase = displayCase.sourceCase

          return (
          <section className="test-report-node test-report-case" key={displayCase.caseId}>
            <div className="test-report-case-row">
              <span className="test-report-summary-main">
                <strong>{ui('Case')} · {reportCase.caseId}</strong>
              </span>
              <span className="test-report-case-status">
                <RunStatusBadge status={reportCase.status} />
                {reportCase.failureType !== 'NONE' ? <small>{reportCase.failureType}</small> : null}
              </span>
            </div>
            <div className="test-report-case-body">
              {reportCase.steps.length ? displayCase.items.map((item) => {
                const itemKey = executionStepDisplayKey(displayCase.caseId, item)
                const selected = selectedItemKey === itemKey
                const representative = item.representativeStep
                const label = item.kind === 'single' ? `${ui('Step')} · ${representative.stepId}` : `${ui('Repeated executions')} ×${item.count}`

                return (
                  <button
                    aria-current={selected ? 'step' : undefined}
                    className={`test-report-node test-report-step${selected ? ' is-selected' : ''}`}
                    key={itemKey}
                    onClick={() => onSelectItem(displayCase.caseId, item)}
                    type="button"
                  >
                    <span className="test-report-summary-main test-report-step-copy">
                      <strong>{label}</strong>
                      {item.kind === 'repeated' ? (
                        <small>{item.rawSteps[0].stepId} … {item.rawSteps[item.rawSteps.length - 1].stepId}</small>
                      ) : null}
                    </span>
                    <span className="test-report-step-meta">
                      {item.kind === 'repeated' ? <small className="test-report-step-count">{item.count} {ui('executions')}</small> : null}
                      <RunStatusBadge status={representative.status} />
                    </span>
                  </button>
                )
              }) : <p className="test-report-step-note">{ui('No step results recorded.')}</p>}
            </div>
          </section>
          )
        }) : <p className="test-report-step-note">{ui('No case results recorded.')}</p>}
      </div>
    </section>
  )
}

function RepeatedStepInspector({ group }: { group: RepeatedStepItem }) {
  const { ui } = useConsoleLanguage()
  const representative = group.rawSteps[0]
  const assertionGroups = buildExecutionAssertionDisplayGroups(group)
  const assertionCount = assertionGroups.reduce((total, assertionGroup) => total + assertionGroup.count, 0)
  const passedAssertions = assertionGroups.reduce(
    (total, assertionGroup) => total + (assertionGroup.representativeAssertion.passed ? assertionGroup.count : 0),
    0,
  )
  const failureType = representative.failureType !== 'NONE' ? representative.failureType : null
  const responseStatusCode = representative.responseStatusCode

  return (
    <div className="run-repeated-step-inspector">
      <div className="run-repeated-step-summary">
        <div className="run-repeated-step-fact">
          <span>{ui('Execution count')}</span>
          <strong>{group.count}</strong>
        </div>
        <div className="run-repeated-step-fact">
          <span>{ui('Total duration')}</span>
          <strong>{formatDuration(group.totalDurationMs)}</strong>
        </div>
        <div className="run-repeated-step-fact">
          <span>{ui('Average duration')}</span>
          <strong>{formatDuration(group.averageDurationMs)}</strong>
        </div>
        <div className="run-repeated-step-fact run-repeated-step-status">
          <span>{ui('Status')}</span>
          <RunStatusBadge status={representative.status} />
        </div>
        {failureType ? (
          <div className="run-repeated-step-fact">
            <span>{ui('Failure type')}</span>
            <strong>{failureType}</strong>
          </div>
        ) : null}
        {responseStatusCode !== null && responseStatusCode !== undefined ? (
          <div className="run-repeated-step-fact">
            <span>{ui('HTTP Status')}</span>
            <strong>{responseStatusCode}</strong>
          </div>
        ) : null}
      </div>

      <div className="run-repeated-step-assertions">
        <span>{ui('Assertions summary')}</span>
        <strong>{passedAssertions} / {assertionCount} {ui('passed')}</strong>
      </div>

      <details className="run-raw-executions">
        <summary>{ui('Raw executions')} ({group.count})</summary>
        <div className="run-raw-execution-list">
          {group.rawSteps.map((step, index) => (
            <div key={`${step.stepId}-${index}`}>
            <div className="run-raw-execution-row">
              <code>{step.stepId}</code>
              <span>{formatDuration(step.durationMs)}</span>
            </div>
            {step.httpExchange ? <details>
              <summary>{ui('Request')} / {ui('Response')}</summary>
              <RunRequest step={step} />
              <RunResponse steps={[step]} />
            </details> : null}
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}

function ReportState({ onRetry, reportStatus }: { onRetry: () => void; reportStatus: ReportStatus }) {
  const { t } = useConsoleLanguage()
  if (reportStatus === 'loading') return <div className="run-inline-state" aria-live="polite">{t('runs.loadingReport')}</div>
  if (reportStatus === 'unavailable') return <div className="run-inline-state">{t('runs.reportUnavailableDescription')}</div>
  if (reportStatus === 'error') {
    return (
      <div className="run-inline-state run-inline-state-error">
        <span>{t('runs.failedToLoadReportDescription')}</span>
        <button className="panel-action" onClick={onRetry} type="button">{t('runs.retry')}</button>
      </div>
    )
  }
  return null
}

type RunDetailProps = {
  controls?: ReactNode
  run: RunSummary | null
  report: TestReport | null
  reportStatus: ReportStatus
  progress: RunProgress | null
  liveState: RunLiveState
  activeTab: RunTab
  onTabChange: (tab: RunTab) => void
  onRetryReport: () => void
  onDiagnose?: (runId: string) => void
}

export function RunDetail({ controls, activeTab, liveState, onDiagnose, onRetryReport, onTabChange, progress, report, reportStatus, run }: RunDetailProps) {
  const { language, t, ui } = useConsoleLanguage()
  const locale = language === 'zh-CN' ? 'zh-CN' : 'en-US'
  const projection = report ? buildExecutionStepDisplayProjection(report.cases) : null
  const presentationCases = projection?.cases ?? []
  const displayStepGroups = presentationCases.flatMap(({ caseId, items }) => items.map((item) => ({ caseId, item })))
  const [reportTab, setReportTab] = useState<ReportTab>('Overview')
  const [selectedItemKey, setSelectedItemKey] = useState<string | null>(null)

  useEffect(() => {
    setReportTab('Overview')
    const firstCase = presentationCases[0]
    const firstItem = firstCase?.items[0]
    setSelectedItemKey(firstCase && firstItem ? executionStepDisplayKey(firstCase.caseId, firstItem) : null)
  }, [report?.reportId, run?.runId])

  const selectedPresentation = presentationCases
    .flatMap(({ caseId, items }) => items.map((item) => ({ caseId, item })))
    .find(({ caseId, item }) => executionStepDisplayKey(caseId, item) === selectedItemKey) ?? null
  const selectedItem = selectedPresentation?.item ?? null
  const selectedStep = selectedItem?.kind === 'single' ? selectedItem.step : null
  const selectedRepeatedStep = selectedItem?.kind === 'repeated' ? selectedItem : null

  if (!run) {
    return (
      <section className="run-detail panel">
        <div className="run-empty-panel">{t('runs.noRunSelected')}</div>
      </section>
    )
  }

  const canDiagnose = onDiagnose && isDiagnosableStatus(run.status)
  const failureType = run.failureType && run.failureType !== 'NONE' ? run.failureType : null
  return (
    <section className="run-detail panel">
      <header className="run-detail-header">
        <div className="run-detail-title">
          <div className="run-endpoint-line">
            <h1>Run #{run.runId}</h1>
            <RunStatusBadge status={run.status} />
          </div>
          <div className="run-context-line">
            <strong>{run.testCaseName}</strong>
            <span>{ui('Case')} {run.caseId}</span>
            <span>{ui('API')} {run.apiId}</span>
          </div>
          <div className="run-detail-facts">
            <span><Clock3 size={14} strokeWidth={1.8} />{ui('Started')} {formatTime(run.startedAt ?? run.createdAt, locale)}</span>
            <span><Database size={14} strokeWidth={1.8} />{formatDuration(run.durationMs)}</span>
          </div>
          <div aria-label={`${ui('Executed by')} Java Platform`} className="run-authority-line">
            <ShieldCheck size={14} strokeWidth={1.8} />
            <span>{ui('Executed by')}</span>
            <strong>Java Platform</strong>
          </div>
          {failureType ? (
            <div className="run-failure-line">
              <span>{ui('Failure type')}</span>
              <code>{failureType}</code>
            </div>
          ) : null}
        </div>
        <div className="run-detail-actions">
          {reportStatus === 'ready' && report?.runId === run.runId ? <ReportExportButtons document={testReportExport(report)} /> : null}
          {canDiagnose ? (
            <button className="panel-action run-detail-diagnose-button" onClick={() => onDiagnose(String(run.runId))} type="button">
              <ScanSearch size={15} strokeWidth={1.8} />
              {ui('Diagnose')}
            </button>
          ) : null}
          <button className="runs-icon-button" title={ui('Copy run ID')} type="button" onClick={() => navigator.clipboard?.writeText(String(run.runId))}>
            <Clipboard size={16} strokeWidth={1.8} />
          </button>
        </div>
      </header>

      {controls}

      <nav className="run-tabs" aria-label={ui('Run detail tabs')}>
        {tabs.map((tab) => (
          <button
            aria-selected={activeTab === tab}
            className={`run-tab${activeTab === tab ? ' is-active' : ''}`}
            key={tab}
            onClick={() => onTabChange(tab)}
            role="tab"
            type="button"
          >
            {ui(tab)}
          </button>
        ))}
      </nav>

      <div className="run-detail-content">
        {activeTab === 'Summary' ? (
          <section className="run-summary-content">
            <ExecutionSummary liveState={liveState} progress={progress} report={report} run={run} />
            <div className="run-summary-workspace">
              <section className="run-case-panel" aria-label={ui('Cases')}>
                <ReportState onRetry={onRetryReport} reportStatus={reportStatus} />
                {reportStatus === 'ready' && report ? (
                  <TestReportHierarchy
                    cases={presentationCases}
                    onSelectItem={(caseId, item) => setSelectedItemKey(executionStepDisplayKey(caseId, item))}
                    selectedItemKey={selectedItemKey}
                    title="Cases"
                  />
                ) : null}
              </section>
              <section className="run-step-inspector" aria-labelledby="run-step-inspector-title">
                <div className="run-step-inspector-heading">
                  <div>
                    <h3 id="run-step-inspector-title">
                      {selectedRepeatedStep ? `${ui('Repeated executions')} ×${selectedRepeatedStep.count}` : selectedStep?.stepId ?? ui('Step details')}
                    </h3>
                    <p>
                      {selectedRepeatedStep
                        ? ui('Presentation group for consecutive equivalent executions.')
                        : selectedStep
                          ? ui('TestReport facts for the selected step.')
                          : ui('Select a step to inspect its TestReport facts.')}
                    </p>
                  </div>
                  {selectedStep ? <RunStatusBadge status={selectedStep.status} /> : selectedRepeatedStep ? <RunStatusBadge status={selectedRepeatedStep.rawSteps[0].status} /> : null}
                </div>
                {selectedRepeatedStep ? <RepeatedStepInspector group={selectedRepeatedStep} /> : null}
                {selectedStep ? (
                  <>
                    <nav className="run-report-tabs" aria-label={ui('TestReport detail tabs')}>
                      {reportTabs.map((tab) => (
                        <button
                          aria-selected={reportTab === tab}
                          className={`run-report-tab${reportTab === tab ? ' is-active' : ''}`}
                          key={tab}
                          onClick={() => setReportTab(tab)}
                          role="tab"
                          type="button"
                        >
                          {ui(tab)}
                        </button>
                      ))}
                    </nav>
                  </>
                ) : null}
                {selectedStep ? (
                  reportTab === 'Overview' ? (
                    <div className="run-step-overview">
                      <div><span>{ui('Step')}</span><strong>{selectedStep.stepId}</strong></div>
                      <div><span>{ui('Duration')}</span><strong>{formatDuration(selectedStep.durationMs)}</strong></div>
                      <div><span>{ui('HTTP Status')}</span><strong>{selectedStep.responseStatusCode ?? '—'}</strong></div>
                      <div><span>{ui('Assertions')}</span><strong>{selectedStep.assertionResults.length}</strong></div>
                      {selectedStep.failureType !== 'NONE' ? <div><span>{ui('Failure type')}</span><strong>{selectedStep.failureType}</strong></div> : null}
                    </div>
                  ) : reportTab === 'Request' ? (
                    <RunRequest step={selectedStep} />
                  ) : reportTab === 'Response' ? (
                    <RunResponse steps={[selectedStep]} />
                  ) : (
                    <RunAssertions stepGroups={selectedPresentation ? [selectedPresentation] : []} available={reportStatus === 'ready'} />
                  )
                ) : !selectedRepeatedStep ? (
                  <div className="run-step-empty">{reportStatus === 'ready' ? ui('No step results recorded.') : ui('Step details will appear when TestReport is available.')}</div>
                ) : null}
              </section>
            </div>
            {reportStatus === 'ready' && report ? <RunAssertions stepGroups={displayStepGroups} available /> : null}
          </section>
        ) : activeTab === 'Test Report' ? (
          <section className="run-test-report-content">
            <div className="run-overview-heading">
              <div>
                <h3>{ui('Test Report')}</h3>
                <p>{t('runs.javaReportFacts')}</p>
              </div>
              <FileCheck2 size={20} strokeWidth={1.8} />
            </div>
            <ReportState onRetry={onRetryReport} reportStatus={reportStatus} />
            {reportStatus === 'ready' && report ? (
              <>
                <TestReportHierarchy
                  cases={presentationCases}
                  onSelectItem={(caseId, item) => setSelectedItemKey(executionStepDisplayKey(caseId, item))}
                  selectedItemKey={selectedItemKey}
                />
                <RunAssertions stepGroups={displayStepGroups} available />
              </>
            ) : null}
          </section>
        ) : (
          <section className="run-timeline-tab">
            <div className="run-overview-heading">
              <div>
                <h3>{ui('Timeline')}</h3>
                <p>{t('runs.javaReportFacts')}</p>
              </div>
              <Clock3 size={20} strokeWidth={1.8} />
            </div>
            <RunTimeline timeline={runTimeline(run)} />
          </section>
        )}
      </div>
    </section>
  )
}
