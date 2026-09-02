import { CheckCircle2, CircleAlert, CircleX, Clock3, LoaderCircle, Search, ShieldAlert } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { EvaluationRunFilter, RuntimeRunStatus, RuntimeRunSummary } from '../types'

type EvaluationRunsProps = {
  filter: EvaluationRunFilter
  onFilterChange: (filter: EvaluationRunFilter) => void
  onQueryChange: (query: string) => void
  onSelect: (runId: string) => void
  query: string
  runs: RuntimeRunSummary[]
  selectedRunId: string | null
}

const filters: Array<{ id: EvaluationRunFilter; label: string }> = [
  { id: 'ALL', label: 'All' },
  { id: 'COMPLETED', label: 'Completed' },
  { id: 'RUNNING', label: 'Running' },
  { id: 'APPROVAL_REQUIRED', label: 'Approval required' },
  { id: 'FAILED', label: 'Failed' },
  { id: 'REJECTED', label: 'Rejected' },
]

function StatusIcon({ status }: { status: RuntimeRunStatus }) {
  if (status === 'COMPLETED') return <CheckCircle2 size={15} strokeWidth={2} />
  if (status === 'FAILED' || status === 'REJECTED') return <CircleX size={15} strokeWidth={2} />
  if (status === 'APPROVAL_REQUIRED') return <ShieldAlert size={15} strokeWidth={2} />
  if (status === 'RUNNING') return <LoaderCircle size={15} strokeWidth={2} />
  return <CircleAlert size={15} strokeWidth={2} />
}

function formatExecutionType(type: RuntimeRunSummary['executionType']) {
  return type === 'TESTCASE_GENERATION' ? 'TestCase Generation' : 'Diagnosis'
}

function formatTimestamp(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'short' }).format(date)
}

export function EvaluationRuns({
  filter,
  onFilterChange,
  onQueryChange,
  onSelect,
  query,
  runs,
  selectedRunId,
}: EvaluationRunsProps) {
  const { ui } = useConsoleLanguage()

  return (
    <aside className="evaluation-runs panel" aria-label={ui('Evaluation Runs')}>
      <div className="evaluation-panel-header">
        <h2>{ui('Recent Runs')}</h2>
        <Clock3 size={17} strokeWidth={1.8} aria-hidden="true" />
      </div>

      <label className="evaluation-search">
        <Search size={16} strokeWidth={1.8} />
        <input
          aria-label={ui('Search evaluations')}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={ui('Search evaluations...')}
          value={query}
        />
      </label>

      <div className="evaluation-filter-row" aria-label={ui('Evaluation status filters')}>
        {filters.map((item) => (
          <button
            aria-pressed={filter === item.id}
            className={`evaluation-filter-chip${filter === item.id ? ' is-active' : ''}`}
            key={item.id}
            onClick={() => onFilterChange(item.id)}
            type="button"
          >
            {ui(item.label)}
          </button>
        ))}
      </div>

      <div className="evaluation-run-list">
        {runs.length > 0 ? runs.map((run) => (
          <button
            aria-label={`${ui('Select')} ${run.agentRunId}`}
            className={`evaluation-run-item${run.agentRunId === selectedRunId ? ' is-selected' : ''}`}
            key={run.agentRunId}
            onClick={() => onSelect(run.agentRunId)}
            type="button"
          >
            <div className="evaluation-run-topline">
              <span className={`evaluation-status evaluation-status-${run.status.toLowerCase()}`}>
                <StatusIcon status={run.status} />
                {ui(run.status)}
              </span>
            </div>
            <strong className="evaluation-run-name">{formatExecutionType(run.executionType)}</strong>
            <code className="evaluation-run-id">{run.agentRunId}</code>
            <div className="evaluation-run-meta">
              <span title={`${run.provider} / ${run.model}`}>{run.provider} · {run.model}</span>
              <time dateTime={run.startedAt}>{formatTimestamp(run.startedAt)}</time>
            </div>
          </button>
        )) : (
          <p className="evaluation-empty-state">{ui('No runtime runs match the current filters.')}</p>
        )}
      </div>

      <div className="evaluation-runs-footer">
        <span>{runs.length} {ui('runtime runs')}</span>
      </div>
    </aside>
  )
}
