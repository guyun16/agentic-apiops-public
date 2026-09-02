import { Activity, AlertTriangle, CalendarDays, Cpu, FileText, Hash, Server, Shield } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { RuntimeRunDetail } from '../types'

type EvaluationSummaryProps = {
  run: RuntimeRunDetail
}

function formatTimestamp(value: string | null) {
  if (!value) return 'UNKNOWN'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'short' }).format(date)
}

function valueOr(value: string | number | null, fallback = 'N/A') {
  return value === null || value === '' ? fallback : String(value)
}

export function EvaluationSummary({ run }: EvaluationSummaryProps) {
  const { ui } = useConsoleLanguage()
  const facts = [
    { label: 'Execution type', value: run.executionType === 'TESTCASE_GENERATION' ? 'TestCase Generation' : 'Diagnosis', icon: Activity },
    { label: 'Agent run ID', value: run.agentRunId, icon: Hash },
    { label: 'Trace ID', value: run.traceId, icon: FileText },
    { label: 'Project', value: valueOr(run.projectId), icon: Server },
    { label: 'Java run', value: valueOr(run.runId), icon: FileText },
    { label: 'API', value: valueOr(run.apiId), icon: Cpu },
    { label: 'Provider / model', value: `${run.provider} / ${run.model}`, icon: Shield },
    { label: 'Started', value: formatTimestamp(run.startedAt), icon: CalendarDays },
  ]

  return (
    <section className="evaluation-summary panel" aria-labelledby="evaluation-summary-title">
      <div className="evaluation-summary-header">
        <div className="evaluation-summary-title">
          <div className="evaluation-title-line">
            <h2 id="evaluation-summary-title">{ui('Runtime Evaluation')}</h2>
            <span className={`evaluation-status evaluation-status-${run.status.toLowerCase()}`}>{ui(run.status)}</span>
          </div>
          <code className="evaluation-summary-code">{run.agentRunId}</code>
        </div>
        <span className="evaluation-summary-code">{ui('Finished')}: {formatTimestamp(run.finishedAt)}</span>
      </div>
      <div className="evaluation-summary-facts">
        {facts.map(({ icon: Icon, label, value }) => (
          <div className="evaluation-summary-fact" key={label}>
            <Icon size={18} strokeWidth={1.7} />
            <div>
              <span>{ui(label)}</span>
              <strong title={value}>{value}</strong>
            </div>
          </div>
        ))}
      </div>
      {run.failureCode || run.failureMessage ? (
        <div className="evaluation-failure-note">
          <AlertTriangle size={15} strokeWidth={1.8} />
          <span>{valueOr(run.failureCode, 'FAILED')}: {valueOr(run.failureMessage, 'Runtime execution failed.')}</span>
        </div>
      ) : null}
    </section>
  )
}
