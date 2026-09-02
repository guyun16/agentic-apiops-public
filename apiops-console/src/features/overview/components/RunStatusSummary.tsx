import { CircleCheck, CircleX, Clock3, LoaderCircle, TriangleAlert } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { ApiError } from '../../../lib/api-client'
import type { RunStatus, RunSummary } from '../../runs/types'

type RunStatusSummaryProps = {
  runs: RunSummary[]
  state: 'loading' | 'ready' | 'error'
  error: ApiError | null
}

type RunCount = {
  label: string
  value: number
  icon: LucideIcon
  tone: 'accent' | 'success' | 'danger' | 'muted'
}

function countStatus(runs: RunSummary[], statuses: RunStatus[]) {
  return runs.filter((run) => statuses.includes(run.status)).length
}

export function RunStatusSummary({ error, runs, state }: RunStatusSummaryProps) {
  const { ui } = useConsoleLanguage()
  const counts: RunCount[] = [
    { icon: LoaderCircle, label: 'Running', tone: 'accent', value: countStatus(runs, ['RUNNING']) },
    { icon: CircleCheck, label: 'Success', tone: 'success', value: countStatus(runs, ['SUCCESS']) },
    { icon: TriangleAlert, label: 'Failure', tone: 'danger', value: countStatus(runs, ['ASSERTION_FAILED', 'EXECUTION_FAILED', 'TIMEOUT']) },
    { icon: Clock3, label: 'Pending', tone: 'muted', value: countStatus(runs, ['PENDING']) },
    { icon: CircleX, label: 'Cancelled', tone: 'muted', value: countStatus(runs, ['CANCELLED']) },
  ]

  return (
    <section aria-labelledby="run-status-summary-title" className="overview-run-summary panel">
      <div className="panel-header">
        <div className="panel-heading">
          <h2 id="run-status-summary-title">{ui('Run summary')}</h2>
        </div>
        <span className="overview-source-label">{ui('Java /test-runs')}</span>
      </div>
      {state === 'error' ? (
        <div className="overview-inline-state overview-inline-state-error">
          <strong>{ui('Java Runs unavailable')}</strong>
          <span>{error?.status === 403 ? ui('Access denied for the current project.') : ui('No fallback data is shown.')}</span>
        </div>
      ) : (
        <div className="run-count-grid">
          {counts.map(({ icon: Icon, label, tone, value }) => (
            <div className={`run-count-card run-count-${tone}`} key={label}>
              <span className="run-count-icon"><Icon size={17} strokeWidth={1.8} /></span>
              <span className="run-count-copy">
                <span>{ui(label)}</span>
                <strong>{state === 'loading' ? '—' : value}</strong>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
