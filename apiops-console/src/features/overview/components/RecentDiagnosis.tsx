import { Ban, CircleAlert, CircleCheck, CircleX, LoaderCircle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatTimestamp } from '../../runs/presentation'
import type { RuntimeRunStatus } from '../../evaluation/types'
import type { RecentDiagnosis as RecentDiagnosisItem } from '../types'
import type { ApiError } from '../../../lib/api-client'

type RecentDiagnosisProps = {
  error: ApiError | null
  onNavigate: () => void
  runs: RecentDiagnosisItem[]
  state: 'loading' | 'ready' | 'error'
}

const statusIcons: Record<RuntimeRunStatus, LucideIcon> = {
  COMPLETED: CircleCheck,
  RUNNING: LoaderCircle,
  FAILED: CircleX,
  APPROVAL_REQUIRED: CircleAlert,
  REJECTED: Ban,
}

function statusTone(status: RuntimeRunStatus) {
  switch (status) {
    case 'COMPLETED':
      return 'completed'
    case 'RUNNING':
      return 'running'
    case 'APPROVAL_REQUIRED':
      return 'approval'
    case 'FAILED':
      return 'failed'
    case 'REJECTED':
      return 'rejected'
  }
}

function statusLabel(status: RuntimeRunStatus, ui: (text: string) => string) {
  switch (status) {
    case 'COMPLETED':
      return ui('Completed')
    case 'RUNNING':
      return ui('Running')
    case 'APPROVAL_REQUIRED':
      return ui('Approval required')
    case 'FAILED':
      return ui('Failed')
    case 'REJECTED':
      return ui('Rejected')
  }
}

function summaryText(run: RecentDiagnosisItem, ui: (text: string) => string) {
  if (run.status === 'RUNNING') return ui('Diagnosis in progress')
  if (run.status === 'APPROVAL_REQUIRED') return ui('Waiting for human approval')
  if (run.status === 'FAILED') return ui('Diagnosis failed')
  if (run.status === 'REJECTED') return ui('Diagnosis rejected')
  return run.summary ?? ui('Summary unavailable')
}

export function RecentDiagnosis({ error, onNavigate, runs, state }: RecentDiagnosisProps) {
  const { language, ui } = useConsoleLanguage()
  const timestampLocale = language === 'zh-CN' ? 'zh-CN' : 'en-US'

  return (
    <section aria-labelledby="recent-diagnosis-title" className="recent-diagnosis panel">
      <div className="panel-header">
        <div className="panel-heading">
          <CircleAlert size={18} strokeWidth={1.8} />
          <h2 id="recent-diagnosis-title">{ui('Recent Diagnosis')}</h2>
        </div>
        <button className="overview-panel-link" onClick={onNavigate} type="button">
          {ui('View all Diagnosis')} <span aria-hidden="true">→</span>
        </button>
      </div>

      {state === 'error' ? (
        <div className="overview-inline-state overview-inline-state-error">
          <strong>{ui('Recent diagnosis unavailable')}</strong>
          <span>{error?.status === 403 ? ui('Access denied for the current project.') : ui('No fallback data is shown.')}</span>
        </div>
      ) : state === 'loading' ? (
        <div className="overview-inline-state" role="status">{ui('Loading recent diagnosis...')}</div>
      ) : runs.length === 0 ? (
        <div className="overview-inline-state">
          <strong>{ui('No recent diagnosis')}</strong>
          <span>{ui('Python AgentLab returned no diagnosis executions for this project.')}</span>
        </div>
      ) : (
        <div className="recent-diagnosis-list">
          {runs.map((run) => {
            const StatusIcon = statusIcons[run.status]
            return (
              <article className="recent-diagnosis-row" key={run.agentRunId}>
                <span className={`recent-diagnosis-status recent-diagnosis-status-${statusTone(run.status)}`} title={statusLabel(run.status, ui)}>
                  <StatusIcon size={15} strokeWidth={1.9} />
                </span>
                <div className="recent-diagnosis-copy">
                  <div className="recent-diagnosis-heading">
                    <code title={run.agentRunId}>{run.agentRunId}</code>
                    <span className={`diagnosis-runtime-status diagnosis-runtime-status-${statusTone(run.status)}`}>
                      {statusLabel(run.status, ui)}
                    </span>
                  </div>
                  <span className="recent-diagnosis-source">
                    {ui('Source run')}: {run.runId === null ? '—' : `#${run.runId}`}
                  </span>
                  <span className="recent-diagnosis-summary" title={summaryText(run, ui)}>{summaryText(run, ui)}</span>
                </div>
                <time dateTime={run.startedAt}>{formatTimestamp(run.startedAt, timestampLocale)}</time>
              </article>
            )
          })}
        </div>
      )}

    </section>
  )
}
