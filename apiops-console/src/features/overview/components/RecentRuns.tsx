import { List } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatDuration, formatTimestamp } from '../../runs/presentation'
import { RunStatusBadge } from '../../runs/components/RunStatusBadge'
import type { RunSummary } from '../../runs/types'

type RecentRunsProps = {
  runs: RunSummary[]
  state: 'loading' | 'ready' | 'error'
  onNavigate: () => void
}

export function RecentRuns({ onNavigate, runs, state }: RecentRunsProps) {
  const { language, ui } = useConsoleLanguage()
  const visibleRuns = runs.slice(0, 5)
  const timestampLocale = language === 'zh-CN' ? 'zh-CN' : 'en-US'

  return (
    <section aria-labelledby="recent-runs-title" className="recent-runs panel">
      <div className="panel-header">
        <div className="panel-heading">
          <List size={18} strokeWidth={1.8} />
          <h2 id="recent-runs-title">{ui('Recent Runs')}</h2>
        </div>
        <button className="overview-panel-link" onClick={onNavigate} type="button">
          {ui('View all Runs')} <span aria-hidden="true">→</span>
        </button>
      </div>

      {state === 'error' ? (
        <div className="overview-inline-state overview-inline-state-error">
          <strong>{ui('Recent Java runs unavailable')}</strong>
          <span>{ui('No fallback data is shown.')}</span>
        </div>
      ) : state === 'loading' ? (
        <div className="overview-inline-state" role="status">{ui('Loading recent Java runs...')}</div>
      ) : visibleRuns.length === 0 ? (
        <div className="overview-inline-state">
          <strong>{ui('No recent runs')}</strong>
          <span>{ui('The Java Platform returned no persisted runs for this project.')}</span>
        </div>
      ) : (
        <div className="runs-table-wrap">
          <table aria-label={ui('Recent Runs')} className="runs-table overview-runs-table">
            <thead>
              <tr>
                <th>{ui('Run ID')}</th>
                <th>{ui('Test case')}</th>
                <th>{ui('API')}</th>
                <th>{ui('Status')}</th>
                <th>{ui('Started At')}</th>
                <th>{ui('Duration')}</th>
              </tr>
            </thead>
            <tbody>
              {visibleRuns.map((run) => {
                return (
                  <tr key={run.runId}>
                    <td><code className="overview-run-id">#{run.runId}</code></td>
                    <td className="overview-test-case" title={run.testCaseName}>{run.testCaseName}</td>
                    <td className="overview-api-id" title={run.apiId}>{run.apiId}</td>
                    <td><RunStatusBadge status={run.status} /></td>
                    <td>{formatTimestamp(run.startedAt, timestampLocale)}</td>
                    <td>{formatDuration(run.durationMs)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

    </section>
  )
}
