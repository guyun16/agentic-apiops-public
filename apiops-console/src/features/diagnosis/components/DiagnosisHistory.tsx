import { Ban, CheckCircle2, ChevronLeft, ChevronRight, CircleAlert, CircleX, FileText, LoaderCircle, Search } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ApiError } from '../../../lib/api-client'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatTimestamp } from '../../runs/presentation'
import type { RuntimeRunStatus, RuntimeRunSummary } from '../../evaluation/types'
import type { DiagnosisHistoryFilter } from '../types'

type DiagnosisHistoryProps = {
  runs: RuntimeRunSummary[]
  visibleRuns: RuntimeRunSummary[]
  selectedAgentRunId: string | null
  query: string
  filter: DiagnosisHistoryFilter
  currentPage: number
  pageCount: number
  pageSize: number
  totalMatches: number
  historyLoading: boolean
  historyError: ApiError | null
  summaryByAgentRunId: Readonly<Record<string, string | null>>
  summaryLoadingIds: ReadonlySet<string>
  accessDeniedDescription: string
  onQueryChange: (query: string) => void
  onFilterChange: (filter: DiagnosisHistoryFilter) => void
  onPageChange: (page: number) => void
  onSelect: (agentRunId: string) => void
  onRetry: () => void
}

const filters: Array<{ value: DiagnosisHistoryFilter; label: string }> = [
  { value: 'ALL', label: 'All' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'APPROVAL_REQUIRED', label: 'Approval Required' },
  { value: 'FAILED', label: 'Failed' },
]

const statusIcons: Record<RuntimeRunStatus, LucideIcon> = {
  COMPLETED: CheckCircle2,
  RUNNING: LoaderCircle,
  APPROVAL_REQUIRED: CircleAlert,
  FAILED: CircleX,
  REJECTED: Ban,
}

function statusLabel(status: RuntimeRunStatus, ui: (text: string) => string) {
  switch (status) {
    case 'COMPLETED':
      return ui('Completed')
    case 'APPROVAL_REQUIRED':
      return ui('Approval Required')
    case 'FAILED':
      return ui('Failed')
    case 'RUNNING':
      return ui('Running')
    case 'REJECTED':
      return ui('Rejected')
  }
}

function statusTone(status: RuntimeRunStatus) {
  return status.toLowerCase().replace(/_/g, '-')
}

function hasSummary(summaryByAgentRunId: Readonly<Record<string, string | null>>, agentRunId: string) {
  return Object.prototype.hasOwnProperty.call(summaryByAgentRunId, agentRunId)
}

function summaryText(
  run: RuntimeRunSummary,
  summaryByAgentRunId: Readonly<Record<string, string | null>>,
  summaryLoadingIds: ReadonlySet<string>,
  ui: (text: string) => string,
) {
  const summary = summaryByAgentRunId[run.agentRunId]
  if (hasSummary(summaryByAgentRunId, run.agentRunId) && summary) return summary
  if (run.status === 'RUNNING') return ui('Diagnosis in progress')
  if (run.status === 'APPROVAL_REQUIRED') return ui('Approval required')
  if (run.status === 'FAILED') return ui('Diagnosis failed')
  if (run.status === 'REJECTED') return ui('Diagnosis rejected')
  if (summaryLoadingIds.has(run.agentRunId)) return ui('Loading report summary...')
  return ui('Report not available')
}

function pageButtons(pageCount: number, currentPage: number): Array<number | 'ellipsis'> {
  if (pageCount <= 7) return Array.from({ length: pageCount }, (_, index) => index + 1)
  if (currentPage <= 3) return [1, 2, 3, 'ellipsis', pageCount]
  if (currentPage >= pageCount - 2) return [1, 'ellipsis', pageCount - 2, pageCount - 1, pageCount]
  return [1, 'ellipsis', currentPage, 'ellipsis', pageCount]
}

export function DiagnosisHistory({
  accessDeniedDescription,
  currentPage,
  filter,
  historyError,
  historyLoading,
  onFilterChange,
  onPageChange,
  onQueryChange,
  onRetry,
  onSelect,
  pageCount,
  pageSize,
  query,
  runs,
  selectedAgentRunId,
  summaryByAgentRunId,
  summaryLoadingIds,
  totalMatches,
  visibleRuns,
}: DiagnosisHistoryProps) {
  const { language, ui } = useConsoleLanguage()
  const locale = language === 'zh-CN' ? 'zh-CN' : 'en-US'
  const firstItem = visibleRuns.length ? (currentPage - 1) * pageSize + 1 : 0
  const lastItem = visibleRuns.length ? firstItem + visibleRuns.length - 1 : 0

  return (
    <aside className="diagnosis-history panel" aria-labelledby="diagnosis-history-title">
      <header className="diagnosis-history-header">
        <div>
          <span className="diagnosis-history-kicker">{ui('Result history')}</span>
          <h2 id="diagnosis-history-title">{ui('Diagnosis History')}</h2>
        </div>
        <span className="diagnosis-history-count">{runs.length}</span>
      </header>

      <label className="diagnosis-history-search">
        <Search size={15} strokeWidth={1.8} />
        <span className="sr-only">{ui('Search diagnosis')}</span>
        <input
          aria-label={ui('Search diagnosis')}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={ui('Search diagnosis...')}
          value={query}
        />
      </label>

      <div className="diagnosis-history-filters" role="group" aria-label={ui('Diagnosis filters')}>
        {filters.map((item) => (
          <button
            aria-pressed={filter === item.value}
            className={`diagnosis-history-filter${filter === item.value ? ' is-active' : ''}`}
            key={item.value}
            onClick={() => onFilterChange(item.value)}
            type="button"
          >
            {ui(item.label)}
          </button>
        ))}
      </div>

      <div className="diagnosis-history-list" aria-label={ui('Diagnosis history list')}>
        {historyLoading ? (
          <div className="diagnosis-history-state" role="status">{ui('Loading Diagnosis History')}</div>
        ) : historyError ? (
          <div className="diagnosis-history-state diagnosis-history-state-error">
            <strong>{ui('Diagnosis History unavailable')}</strong>
            <p>{historyError.status === 403 ? accessDeniedDescription : historyError.message}</p>
            <button className="panel-action" onClick={onRetry} type="button">{ui('Retry')}</button>
          </div>
        ) : runs.length === 0 ? (
          <div className="diagnosis-history-state">{ui('No diagnosis executions for current project')}</div>
        ) : visibleRuns.length === 0 ? (
          <div className="diagnosis-history-state">{ui('No diagnosis executions match the current filters')}</div>
        ) : (
          visibleRuns.map((run) => {
            const StatusIcon = statusIcons[run.status]
            return (
              <button
                aria-pressed={run.agentRunId === selectedAgentRunId}
                className={`diagnosis-history-item${run.agentRunId === selectedAgentRunId ? ' is-selected' : ''}`}
                key={run.agentRunId}
                onClick={() => onSelect(run.agentRunId)}
                type="button"
              >
                <span className="diagnosis-history-item-icon"><FileText size={15} strokeWidth={1.8} /></span>
                <span className="diagnosis-history-item-copy">
                  <span className="diagnosis-history-item-topline">
                    <code title={run.agentRunId}>{run.agentRunId}</code>
                    <span className={`diagnosis-history-status diagnosis-history-status-${statusTone(run.status)}`}>
                      <StatusIcon size={13} strokeWidth={2} />
                      {statusLabel(run.status, ui)}
                    </span>
                  </span>
                  <span className="diagnosis-history-item-meta">
                    <span>{ui('Source run')}: {run.runId === null ? '—' : `#${run.runId}`}</span>
                    <span>{ui('Diagnosis')} · {run.provider}</span>
                  </span>
                  <span className="diagnosis-history-item-summary" title={summaryText(run, summaryByAgentRunId, summaryLoadingIds, ui)}>
                    {summaryText(run, summaryByAgentRunId, summaryLoadingIds, ui)}
                  </span>
                </span>
                <time dateTime={run.finishedAt ?? run.startedAt}>{formatTimestamp(run.finishedAt ?? run.startedAt, locale)}</time>
              </button>
            )
          })
        )}
      </div>

      {!historyLoading && !historyError && runs.length > 0 ? (
        <footer className="diagnosis-history-footer">
          <span>{ui('Showing')} {firstItem}–{lastItem} {ui('of')} {totalMatches}</span>
          <nav className="diagnosis-history-pagination" aria-label={ui('Diagnosis history pagination')}>
            <button aria-label={ui('Previous page')} disabled={currentPage <= 1} onClick={() => onPageChange(currentPage - 1)} type="button">
              <ChevronLeft size={14} strokeWidth={1.8} />
            </button>
            {pageButtons(pageCount, currentPage).map((page, index) => page === 'ellipsis' ? (
              <span className="diagnosis-history-page-ellipsis" key={`ellipsis-${index}`}>…</span>
            ) : (
              <button aria-current={page === currentPage ? 'page' : undefined} className={page === currentPage ? 'is-active' : undefined} key={page} onClick={() => onPageChange(page)} type="button">{page}</button>
            ))}
            <button aria-label={ui('Next page')} disabled={currentPage >= pageCount} onClick={() => onPageChange(currentPage + 1)} type="button">
              <ChevronRight size={14} strokeWidth={1.8} />
            </button>
          </nav>
        </footer>
      ) : null}
    </aside>
  )
}
