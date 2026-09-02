import { CheckCircle2, CircleX, Clock3, GitBranch, Link2, ListTree, Search } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { TraceFilter, TraceRecord } from '../types'

type TraceExplorerProps = {
  filter: TraceFilter
  onFilterChange: (filter: TraceFilter) => void
  onQueryChange: (query: string) => void
  onSelect: (traceId: string) => void
  query: string
  traces: TraceRecord[]
  selectedTraceId: string
}

const filters: Array<{ id: TraceFilter; label: string }> = [
  { id: 'ALL', label: 'All' },
  { id: 'SUCCESS', label: 'Success' },
  { id: 'FAILED', label: 'Failed' },
  { id: 'TOOL', label: 'Tool' },
  { id: 'MODEL', label: 'Model' },
  { id: 'PYTHON', label: 'Python' },
  { id: 'JAVA', label: 'Java' },
]

function statusIcon(status: TraceRecord['status']) {
  if (status === 'SUCCESS') return <CheckCircle2 size={14} strokeWidth={2} />
  if (status === 'RUNNING') return <Clock3 size={14} strokeWidth={2} />
  return <CircleX size={14} strokeWidth={2} />
}

export function TraceExplorer({
  filter,
  onFilterChange,
  onQueryChange,
  onSelect,
  query,
  traces,
  selectedTraceId,
}: TraceExplorerProps) {
  const { ui } = useConsoleLanguage()

  return (
    <aside className="traces-explorer panel" aria-label={ui('Trace Explorer')}>
      <div className="traces-panel-header">
        <div className="traces-heading">
          <GitBranch size={18} strokeWidth={1.8} />
          <h2>{ui('Trace Explorer')}</h2>
        </div>
        <span className="traces-count">{traces.length}</span>
      </div>

      <label className="traces-search">
        <Search size={16} strokeWidth={1.8} />
        <input
          aria-label={ui('Search traces')}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={ui('Search traces, workflows, IDs...')}
          value={query}
        />
      </label>

      <div className="traces-filter-row" aria-label={ui('Trace filters')}>
        {filters.map((item) => (
          <button
            aria-pressed={filter === item.id}
            className={`traces-filter-chip filter-${item.id.toLowerCase()}${filter === item.id ? ' is-active' : ''}`}
            key={item.id}
            onClick={() => onFilterChange(item.id)}
            type="button"
          >
            {item.id === 'SUCCESS' ? <span className="trace-filter-dot is-success" /> : null}
            {item.id === 'FAILED' ? <span className="trace-filter-dot is-failed" /> : null}
            {item.id === 'TOOL' ? <span className="trace-filter-dot is-tool" /> : null}
            {item.id === 'MODEL' ? <span className="trace-filter-dot is-model" /> : null}
            {item.id === 'PYTHON' ? <span className="trace-filter-dot is-python" /> : null}
            {item.id === 'JAVA' ? <span className="trace-filter-dot is-java" /> : null}
            {ui(item.label)}
          </button>
        ))}
      </div>

      <div className="traces-list">
        {traces.length > 0 ? traces.map((trace) => (
          <button
            aria-label={`${ui('Select')} ${trace.name} ${trace.traceId}`}
            className={`trace-list-item${selectedTraceId === trace.id ? ' is-selected' : ''}`}
            key={trace.id}
            onClick={() => onSelect(trace.id)}
            type="button"
          >
            <div className="trace-list-topline">
              <span className={`trace-status trace-status-${trace.status.toLowerCase()}`}>
                {statusIcon(trace.status)}
                {trace.status}
              </span>
              <time>{trace.relativeTime}</time>
            </div>
            <strong className="trace-list-name">{trace.name}</strong>
            <div className="trace-list-identities">
              <span>agentRunId <code>{trace.agentRunId}</code></span>
              <span>traceId <code>{trace.traceId}</code></span>
            </div>
            <div className="trace-list-meta">
              <span><ListTree size={13} strokeWidth={1.8} /> {trace.stepCount} {ui('steps')}</span>
              <span><Clock3 size={13} strokeWidth={1.8} /> {trace.durationLabel}</span>
              <span><Link2 size={13} strokeWidth={1.8} /> {trace.tags[0] ?? 'TRACE'}</span>
            </div>
          </button>
        )) : (
          <p className="traces-empty-state">{ui('No traces match the current filters.')}</p>
        )}
      </div>

    </aside>
  )
}
