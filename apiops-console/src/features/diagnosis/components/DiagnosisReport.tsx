import { CheckCircle2, CircleAlert, Crosshair, ExternalLink, FileWarning, ShieldCheck } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { ReportExportButtons } from '../../../shared/reports/ReportExportButtons'
import { diagnosisReportExport } from '../../../shared/reports/reportExport'
import { formatTimestamp } from '../../runs/presentation'
import type { DiagnosisExecutionResponse } from '../types'

type DiagnosisReportProps = {
  execution: DiagnosisExecutionResponse
  onOpenSourceRun?: () => void
  onOpenDiagnosisStudio?: () => void
  onViewTrace?: () => void
}

function statusClass(status: DiagnosisExecutionResponse['status']) {
  return status.toLowerCase().replace(/_/g, '-')
}

function valueOrDash(value: string | number | null | undefined) {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

export function DiagnosisReport({ execution, onOpenDiagnosisStudio, onOpenSourceRun, onViewTrace }: DiagnosisReportProps) {
  const { language, ui } = useConsoleLanguage()
  const locale = language === 'zh-CN' ? 'zh-CN' : 'en-US'
  const report = execution.report
  const testReport = execution.testReport
  const failureType = report?.failureType || testReport.summary.failureType || '—'
  const traceId = execution.traceId.trim()
  const runtimeLabel = execution.runtime === 'PYTHON_AGENTLAB' ? ui('Python AgentLab') : execution.runtime

  return (
    <article className="diagnosis-report panel">
      <header className="diagnosis-report-header">
        <div className="diagnosis-report-title">
          <span className="diagnosis-report-kicker">{ui('UNIFIED RESULT VIEW')}</span>
          <div className="diagnosis-report-heading-row">
            <div>
              <h1>{ui('Diagnosis')}</h1>
              <p>{execution.provider} · {execution.model} · {runtimeLabel}</p>
            </div>
            <div className="diagnosis-report-badges">
              <span className={`diagnosis-status diagnosis-status-${statusClass(execution.status)}`}>
                {execution.status === 'COMPLETED' ? <CheckCircle2 size={14} strokeWidth={1.9} /> : <CircleAlert size={14} strokeWidth={1.9} />}
                {execution.status}
              </span>
              <span className={`diagnosis-evidence-badge${report?.sufficientEvidence ? ' is-sufficient' : ''}`}>
                {report ? (report.sufficientEvidence ? ui('Sufficient Evidence') : ui('Limited Evidence')) : ui('Evidence unavailable')}
              </span>
            </div>
          </div>
        </div>

        <div className="diagnosis-report-actions" aria-label={ui('Diagnosis result actions')}>
          <ReportExportButtons document={diagnosisReportExport(execution)} />
          <button className="panel-action" disabled={!onOpenSourceRun} onClick={onOpenSourceRun} type="button">
            <ExternalLink size={14} strokeWidth={1.8} />
            {ui('Open Source Run')}
          </button>
          <button className="panel-action" disabled={!onOpenDiagnosisStudio} onClick={onOpenDiagnosisStudio} type="button">
            <ExternalLink size={14} strokeWidth={1.8} />
            {ui('Open in Diagnosis Studio')}
          </button>
          <button className="panel-action" disabled={!onViewTrace || !traceId} onClick={onViewTrace} type="button">
            <ExternalLink size={14} strokeWidth={1.8} />
            {ui('View Trace')}
          </button>
        </div>
      </header>

      <div className="diagnosis-report-metadata" aria-label={ui('Execution Identity')}>
        <div><span>{ui('Report ID')}</span><code>{valueOrDash(report?.reportId)}</code></div>
        <div><span>{ui('Agent Run ID')}</span><code>{valueOrDash(execution.agentRunId)}</code></div>
        <div><span>{ui('Project ID')}</span><code>{valueOrDash(execution.projectId)}</code></div>
        <div><span>{ui('Run ID')}</span><code>{valueOrDash(execution.runId)}</code></div>
        <div><span>{ui('Failure Type')}</span><strong>{failureType}</strong></div>
        <div><span>{ui('Runtime')}</span><code>{execution.runtime}</code></div>
        <div><span>{ui('Started At')}</span><strong>{formatTimestamp(testReport.startedAt, locale)}</strong></div>
        <div><span>{ui('Finished At')}</span><strong>{formatTimestamp(testReport.finishedAt, locale)}</strong></div>
        <div><span>{ui('Trace ID')}</span><code>{valueOrDash(traceId)}</code></div>
      </div>

      {!report ? (
        <section className="diagnosis-report-unavailable" role="status">
          <FileWarning size={18} strokeWidth={1.8} />
          <div>
            <strong>{ui('DiagnosisReport is not available for this execution.')}</strong>
            <p>{ui('The execution is readable, but Python AgentLab did not return a structured DiagnosisReport.')}</p>
          </div>
        </section>
      ) : null}

      <div className="diagnosis-report-body">
        <section className="diagnosis-report-section diagnosis-summary-section" aria-labelledby="diagnosis-summary-title">
          <div className="diagnosis-section-heading diagnosis-summary-heading">
            <div className="diagnosis-summary-heading-copy">
              <span className="trace-summary-icon diagnosis-summary-icon" aria-hidden="true"><Crosshair size={17} strokeWidth={1.8} /></span>
              <div>
                <span className="diagnosis-eyebrow">{ui('Agent diagnosis')}</span>
                <h2 id="diagnosis-summary-title">{ui('Diagnosis Summary')}</h2>
              </div>
            </div>
            <span className="diagnosis-report-source">{ui('Java TestReport')} · #{testReport.runId}</span>
          </div>
          <p>{report?.summary || ui('Summary unavailable')}</p>
        </section>

        <section className="diagnosis-report-section diagnosis-hypotheses-section" aria-labelledby="root-cause-title">
          <div className="diagnosis-section-heading">
            <div>
              <span className="diagnosis-eyebrow">{ui('Evidence-backed reasoning')}</span>
              <h2 id="root-cause-title">{ui('Root Cause Hypotheses')}</h2>
            </div>
            <span className="diagnosis-section-count">{report?.rootCauseHypotheses.length ?? 0}</span>
          </div>
          {report?.rootCauseHypotheses.length ? (
            <div className="diagnosis-hypothesis-list">
              {report.rootCauseHypotheses.map((hypothesis, index) => (
                <article className="diagnosis-hypothesis-card" key={`${hypothesis.statement}-${index}`}>
                  <div className="diagnosis-hypothesis-card-topline">
                    <span className={`diagnosis-confidence diagnosis-confidence-${hypothesis.confidence.toLowerCase()}`}>{hypothesis.confidence}</span>
                    <span>{ui('Hypothesis')} {index + 1}</span>
                  </div>
                  <p>{hypothesis.statement}</p>
                  <div className="diagnosis-evidence-ref-list">
                    {hypothesis.evidenceRefs.map((reference) => (
                      <code className="diagnosis-evidence-ref" key={reference.itemId} title={ui('Evidence reference from DiagnosisReport')}>
                        {reference.itemId}
                      </code>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="diagnosis-report-empty-copy">{ui('The real DiagnosisReport did not return a root-cause hypothesis.')}</p>
          )}
        </section>

        <div className="diagnosis-report-bottom-grid">
          <section className="diagnosis-report-section" aria-labelledby="recommended-checks-title">
            <div className="diagnosis-section-heading">
              <div>
                <span className="diagnosis-eyebrow">{ui('Recommended next step')}</span>
                <h2 id="recommended-checks-title">{ui('Recommended Checks')}</h2>
              </div>
              <ShieldCheck size={18} strokeWidth={1.8} />
            </div>
            {report?.recommendedChecks.length ? (
              <ul className="diagnosis-check-list">
                {report.recommendedChecks.map((check, index) => <li key={`${check}-${index}`}><ShieldCheck size={14} strokeWidth={1.9} /><span>{check}</span></li>)}
              </ul>
            ) : <p className="diagnosis-report-empty-copy">{ui('No recommended checks were returned.')}</p>}
          </section>

          <section className="diagnosis-report-section" aria-labelledby="limitations-title">
            <div className="diagnosis-section-heading">
              <div>
                <span className="diagnosis-eyebrow">{ui('Result boundaries')}</span>
                <h2 id="limitations-title">{ui('Limitations')}</h2>
              </div>
              <span className="diagnosis-section-count">{report?.limitations.length ?? 0}</span>
            </div>
            {report?.limitations.length ? (
              <ul className="diagnosis-limitation-list">
                {report.limitations.map((limitation, index) => <li key={`${limitation}-${index}`}><FileWarning size={14} strokeWidth={1.8} /><span>{limitation}</span></li>)}
              </ul>
            ) : <p className="diagnosis-report-empty-copy">{ui('No limitations were returned.')}</p>}
          </section>
        </div>
      </div>
    </article>
  )
}
