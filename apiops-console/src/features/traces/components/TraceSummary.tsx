import { CheckCircle2, CircleX, Clock3, Copy, GitBranch } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { TraceRecord } from '../types'

type TraceSummaryProps = {
  trace: TraceRecord
}

type SummaryItem = {
  label: string
  value: string
  copy?: boolean
}

function isKnown(value: string) {
  return value.trim() !== '' && value !== 'UNKNOWN'
}

function statusIcon(status: TraceRecord['status']) {
  if (status === 'SUCCESS') return <CheckCircle2 size={16} strokeWidth={2} />
  if (status === 'RUNNING') return <Clock3 size={16} strokeWidth={2} />
  return <CircleX size={16} strokeWidth={2} />
}

function copyText(value: string) {
  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    void navigator.clipboard.writeText(value)
  }
}

function CopyValueButton({ label, value }: { label: string; value: string }) {
  const { ui } = useConsoleLanguage()

  return (
    <button
      aria-label={`${ui('Copy')} ${label}`}
      className="trace-copy-button"
      onClick={() => copyText(value)}
      title={`${ui('Copy')} ${label}`}
      type="button"
    >
      <Copy size={13} strokeWidth={1.8} />
    </button>
  )
}

export function TraceSummary({ trace }: TraceSummaryProps) {
  const { ui } = useConsoleLanguage()
  const identityItems: SummaryItem[] = [
    { label: ui('Trace ID'), value: trace.traceId, copy: true },
    ...(isKnown(trace.runId) ? [{ label: ui('Source Run ID'), value: trace.runId, copy: true }] : []),
    { label: ui('Agent Run ID'), value: trace.agentRunId, copy: true },
  ]
  const detailItems: SummaryItem[] = [
    { label: ui('Workflow Type'), value: trace.name },
    ...(isKnown(trace.agentRuntime) ? [{ label: ui('Agent Runtime'), value: trace.agentRuntime }] : []),
    { label: ui('Started At'), value: trace.startedAt ?? 'UNKNOWN' },
    { label: ui('Duration'), value: trace.durationLabel },
  ]

  return (
    <section className="trace-summary panel" aria-labelledby="trace-summary-title">
      <header className="trace-summary-header">
        <div className="trace-summary-title">
          <span className="trace-summary-icon" aria-hidden="true"><GitBranch size={17} strokeWidth={1.8} /></span>
          <div className="trace-summary-title-copy">
            <span className="trace-summary-kicker">{ui('Current Trace')}</span>
            <h2 id="trace-summary-title">{trace.name}</h2>
          </div>
          <span className={`trace-status trace-status-${trace.status.toLowerCase()}`}>
            {statusIcon(trace.status)}
            {trace.status}
          </span>
        </div>
      </header>

      <div className="trace-summary-identities">
        {identityItems.map((item) => (
          <SummaryValue key={item.label} item={item} />
        ))}
      </div>

      <div className="trace-summary-details">
        {detailItems.map((item) => (
          <SummaryValue key={item.label} item={item} />
        ))}
      </div>
    </section>
  )
}

function SummaryValue({ item }: { item: SummaryItem }) {
  return (
    <div className="trace-summary-value">
      <span>{item.label}</span>
      <div className="trace-summary-value-line">
        <strong title={item.value}>{item.value}</strong>
        {item.copy ? <CopyValueButton label={item.label} value={item.value} /> : null}
      </div>
    </div>
  )
}
