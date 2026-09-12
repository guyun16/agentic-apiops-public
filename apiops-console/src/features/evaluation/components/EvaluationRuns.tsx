import { Activity, CheckCircle2, CircleX, Clock3, LoaderCircle, Search, ShieldAlert } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { countRuntimeRuns, evaluationRunFilters } from '../evaluationViewModel'
import type { EvaluationRunFilter, RuntimeRunStatus, RuntimeRunSummary } from '../types'

type EvaluationRunsProps = {
  allRuns: RuntimeRunSummary[]
  filter: EvaluationRunFilter
  onFilterChange: (filter: EvaluationRunFilter) => void
  onQueryChange: (query: string) => void
  onSelect: (runId: string) => void
  query: string
  runs: RuntimeRunSummary[]
  selectedRunId: string | null
}

function StatusIcon({ status }: { status: RuntimeRunStatus }) {
  if (status === 'COMPLETED') return <CheckCircle2 size={11} strokeWidth={2.4} />
  if (status === 'FAILED' || status === 'REJECTED') return <CircleX size={11} strokeWidth={2.4} />
  if (status === 'APPROVAL_REQUIRED') return <ShieldAlert size={11} strokeWidth={2.4} />
  return <LoaderCircle className="evaluation-spin" size={11} strokeWidth={2.4} />
}

function formatExecutionType(type: RuntimeRunSummary['executionType']) {
  return type === 'TESTCASE_GENERATION' ? 'TestCase Generation' : 'Diagnosis'
}

function formatTimestamp(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export function EvaluationRuns({
  allRuns,
  filter,
  onFilterChange,
  onQueryChange,
  onSelect,
  query,
  runs,
  selectedRunId,
}: EvaluationRunsProps) {
  const { ui } = useConsoleLanguage()
  const counts = countRuntimeRuns(allRuns)

  return (
    <aside className="evaluation-runs panel" aria-label={ui('Evaluation Runs')}>
      <div className="evaluation-panel-header">
        <div>
          <h2>{ui('Evaluation Runs')}</h2>
          <span>{counts.ALL} {ui('runtime runs')}</span>
        </div>
        <Activity size={17} strokeWidth={1.8} aria-hidden="true" />
      </div>

      <label className="evaluation-search">
        <Search size={15} strokeWidth={1.8} />
        <input
          aria-label={ui('Search runs')}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={ui('Search runs...')}
          value={query}
        />
      </label>

      <div className="evaluation-filter-row" aria-label={ui('Evaluation status filters')}>
        {evaluationRunFilters.map((item) => (
          <button
            aria-pressed={filter === item.id}
            className={`evaluation-filter-chip${filter === item.id ? ' is-active' : ''}`}
            key={item.id}
            onClick={() => onFilterChange(item.id)}
            title={ui(item.label)}
            type="button"
          >
            <span>{ui(item.label)}</span>
            <strong>{counts[item.id]}</strong>
          </button>
        ))}
      </div>

      <div className="evaluation-run-list">
        {runs.length > 0 ? runs.map((run) => (
          <button
            aria-label={`${ui('Select')} ${run.agentRunId}`}
            aria-pressed={run.agentRunId === selectedRunId}
            className={`evaluation-run-item${run.agentRunId === selectedRunId ? ' is-selected' : ''}`}
            key={run.agentRunId}
            onClick={() => onSelect(run.agentRunId)}
            type="button"
          >
            <div className="evaluation-run-topline">
              <span className={`evaluation-status evaluation-status-${run.status.toLowerCase()}`}>
                <StatusIcon status={run.status} />
                {ui(run.status).replace(/_/g, ' ')}
              </span>
              {run.runId !== null ? <span className="evaluation-run-number">Run #{run.runId}</span> : null}
            </div>
            <strong className="evaluation-run-name">{ui(formatExecutionType(run.executionType))}</strong>
            <code className="evaluation-run-id" title={run.agentRunId}>{run.agentRunId}</code>
            <div className="evaluation-run-provider" title={`${run.provider} / ${run.model}`}>
              <span>{run.provider}</span><span>·</span><span>{run.model}</span>
            </div>
            {run.traceId ? <code className="evaluation-run-trace" title={run.traceId}>{ui('Trace')} {run.traceId}</code> : null}
            <div className="evaluation-run-meta">
              <span><Clock3 size={11} strokeWidth={1.8} /> <time dateTime={run.startedAt}>{formatTimestamp(run.startedAt)}</time></span>
            </div>
          </button>
        )) : (
          <p className="evaluation-empty-state">{ui('No runtime runs match the current filters.')}</p>
        )}
      </div>
    </aside>
  )
}
