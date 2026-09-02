import { ChevronDown, Clock3, Search } from 'lucide-react'
import { useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatDuration, formatTime } from '../presentation'
import { isDiagnosableStatus, type RunFilter, type RunStatus, type RunSummary } from '../types'
import { RunStatusBadge } from './RunStatusBadge'

type RunsExplorerProps = {
  allRuns: RunSummary[]
  runs: RunSummary[]
  totalRuns: number
  selectedRunId: number | null
  query: string
  filter: RunFilter
  onQueryChange: (query: string) => void
  onFilterChange: (filter: RunFilter) => void
  onSelect: (runId: number) => void
  onDiagnose?: (runId: string) => void
}

const filterOptions: Array<{ value: RunFilter; label: string }> = [
  { value: 'ALL', label: 'All statuses' },
  { value: 'SUCCESS', label: 'Success' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'RUNNING', label: 'Running' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'CANCELLED', label: 'Cancelled' },
]

function filterMatches(status: RunStatus, filter: RunFilter) {
  if (filter === 'ALL') return true
  if (filter === 'SUCCESS') return status === 'SUCCESS'
  if (filter === 'RUNNING') return status === 'RUNNING'
  if (filter === 'PENDING') return status === 'PENDING'
  if (filter === 'CANCELLED') return status === 'CANCELLED'
  return isDiagnosableStatus(status)
}

function filterCount(runs: RunSummary[], filter: RunFilter) {
  return runs.filter((run) => filterMatches(run.status, filter)).length
}

const statusGroups: Array<{ key: string; label: string; statuses: RunStatus[] }> = [
  { key: 'failed', label: 'Failed', statuses: ['ASSERTION_FAILED', 'EXECUTION_FAILED', 'TIMEOUT'] },
  { key: 'running', label: 'Running', statuses: ['RUNNING'] },
  { key: 'successful', label: 'Successful', statuses: ['SUCCESS'] },
  { key: 'pending', label: 'Pending', statuses: ['PENDING'] },
  { key: 'cancelled', label: 'Cancelled', statuses: ['CANCELLED'] },
]

function isToday(value: string | null) {
  if (!value) return false
  const date = new Date(value)
  const today = new Date()
  return !Number.isNaN(date.getTime())
    && date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate()
}

function groupRuns(runs: RunSummary[]) {
  const periods = [
    { key: 'today', label: 'Today', runs: runs.filter((run) => isToday(run.startedAt ?? run.createdAt)) },
    { key: 'earlier', label: 'Earlier', runs: runs.filter((run) => !isToday(run.startedAt ?? run.createdAt)) },
  ]

  return periods
    .map((period) => ({
      ...period,
      statusGroups: statusGroups
        .map((group) => ({
          ...group,
          runs: period.runs.filter((run) => group.statuses.includes(run.status)),
        }))
        .filter((group) => group.runs.length > 0),
    }))
    .filter((period) => period.runs.length > 0)
}

export function RunsExplorer({
  allRuns,
  filter,
  onDiagnose,
  onFilterChange,
  onQueryChange,
  onSelect,
  query,
  runs,
  selectedRunId,
  totalRuns,
}: RunsExplorerProps) {
  const { language, t, ui } = useConsoleLanguage()
  const locale = language === 'zh-CN' ? 'zh-CN' : 'en-US'
  const groupedRuns = groupRuns(runs)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})

  const toggleGroup = (groupKey: string) => {
    setExpandedGroups((current) => ({ ...current, [groupKey]: !(current[groupKey] ?? true) }))
  }

  return (
    <aside className="runs-explorer panel">
      <header className="runs-panel-header">
        <div className="runs-heading">
          <h2>{ui('Runs List')}</h2>
          <span className="runs-count">{totalRuns}</span>
        </div>
      </header>

      <div className="runs-toolbar">
        <label className="runs-search">
          <Search size={16} strokeWidth={1.8} />
          <span className="sr-only">{ui('Search runs')}</span>
          <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={ui('Search runs...')} />
        </label>
        <label className="runs-status-filter">
          <span>{ui('Status')}</span>
          <select aria-label={ui('Run status')} onChange={(event) => onFilterChange(event.target.value as RunFilter)} value={filter}>
            {filterOptions.map((option) => (
              <option key={option.value} value={option.value}>{ui(option.label)} ({filterCount(allRuns, option.value)})</option>
            ))}
          </select>
        </label>
      </div>

      <div className="runs-list" aria-label={ui('Runs list')}>
        {groupedRuns.length > 0 ? (
          groupedRuns.map((period) => {
            const periodKey = `period-${period.key}`
            const periodExpanded = expandedGroups[periodKey] ?? true

            return (
              <section className="run-date-group" key={period.key}>
                <button
                  aria-expanded={periodExpanded}
                  className="run-group-heading run-date-group-heading"
                  onClick={() => toggleGroup(periodKey)}
                  type="button"
                >
                  <ChevronDown className={`run-group-chevron${periodExpanded ? ' is-expanded' : ''}`} size={13} strokeWidth={1.8} />
                  <strong>{ui(period.label)}</strong>
                  <span>({period.runs.length})</span>
                </button>
                {periodExpanded ? (
                  <div className="run-date-group-content">
                    {period.statusGroups.map((statusGroup) => {
                      const statusKey = `${periodKey}-${statusGroup.key}`
                      const statusExpanded = expandedGroups[statusKey] ?? true
                      return (
                        <section className="run-status-group" key={statusGroup.key}>
                          <button
                            aria-expanded={statusExpanded}
                            className="run-group-heading run-status-group-heading"
                            onClick={() => toggleGroup(statusKey)}
                            type="button"
                          >
                            <ChevronDown className={`run-group-chevron${statusExpanded ? ' is-expanded' : ''}`} size={12} strokeWidth={1.8} />
                            <span className={`run-group-dot run-group-${statusGroup.key}`} />
                            <strong>{ui(statusGroup.label)}</strong>
                            <span>({statusGroup.runs.length})</span>
                          </button>
                          {statusExpanded ? (
                            <div className="run-status-group-items">
                              {statusGroup.runs.map((run) => (
                                <div
                                  aria-pressed={run.runId === selectedRunId}
                                  className={`run-list-item${run.runId === selectedRunId ? ' is-selected' : ''}`}
                                  key={run.runId}
                                  onClick={() => onSelect(run.runId)}
                                  onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                      event.preventDefault()
                                      onSelect(run.runId)
                                    }
                                  }}
                                  role="button"
                                  tabIndex={0}
                                >
                                  <span className="run-list-topline">
                                    <span className="run-list-title">
                                      <strong>#{run.runId}</strong>
                                      <span>{run.testCaseName}</span>
                                    </span>
                                    <span className="run-list-time">{formatTime(run.startedAt ?? run.createdAt, locale)}</span>
                                  </span>
                                  <span className="run-list-status-line">
                                    <RunStatusBadge status={run.status} />
                                    <span className="run-duration">
                                      <Clock3 size={13} strokeWidth={1.8} />
                                      {formatDuration(run.durationMs)}
                                    </span>
                                  </span>
                                  <span className="run-list-meta">
                                    <span>{run.caseId} · {run.apiId}</span>
                                    {onDiagnose && isDiagnosableStatus(run.status) ? (
                                      <button
                                        aria-label={`${ui('Diagnose')} ${run.runId}`}
                                        className="run-diagnose-button"
                                        onClick={(event) => {
                                          event.stopPropagation()
                                          onDiagnose(String(run.runId))
                                        }}
                                        type="button"
                                      >
                                        {ui('Diagnose')}
                                      </button>
                                    ) : null}
                                  </span>
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </section>
                      )
                    })}
                  </div>
                ) : null}
              </section>
            )
          })
        ) : (
          <div className="runs-empty-state">{totalRuns ? ui('No runs match the current filters.') : t('runs.noRuns')}</div>
        )}
      </div>

      <footer className="runs-explorer-footer">
        <span>{runs.length} {ui('of')} {totalRuns} {ui('runs')}</span>
      </footer>
    </aside>
  )
}
