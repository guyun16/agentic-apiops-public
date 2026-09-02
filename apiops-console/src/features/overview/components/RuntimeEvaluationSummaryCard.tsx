import { Activity, AlertTriangle, BarChart3 } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { ApiError } from '../../../lib/api-client'
import type { RuntimeEvaluationSummary, RuntimeMetricAggregate } from '../../evaluation/types'

type RuntimeEvaluationSummaryCardProps = {
  summary: RuntimeEvaluationSummary | null
  state: 'loading' | 'ready' | 'error'
  error: ApiError | null
  onNavigate: () => void
}

function formatMetric(metric: RuntimeMetricAggregate | undefined) {
  if (!metric) return 'UNKNOWN'
  if (metric.status !== 'VALUE') return metric.status
  if (metric.rate !== null && metric.rate !== undefined) return `${(metric.rate * 100).toFixed(1)}%`
  if (metric.mean !== null && metric.mean !== undefined) {
    return `${metric.mean.toFixed(1)}${metric.unit ? ` ${metric.unit}` : ''}`
  }
  return 'VALUE'
}

export function RuntimeEvaluationSummaryCard({ error, onNavigate, state, summary }: RuntimeEvaluationSummaryCardProps) {
  const { ui } = useConsoleLanguage()

  return (
    <section aria-labelledby="runtime-evaluation-summary-title" className="overview-evaluation panel">
      <div className="panel-header">
        <div className="panel-heading">
          <BarChart3 size={18} strokeWidth={1.8} />
          <h2 id="runtime-evaluation-summary-title">{ui('Runtime Evaluation summary')}</h2>
        </div>
        <span className="overview-source-label">{ui('Python AgentLab API')}</span>
      </div>

      {state === 'error' ? (
        <div className="overview-inline-state overview-inline-state-error">
          <AlertTriangle size={17} strokeWidth={1.8} />
          <strong>{ui('Runtime Evaluation unavailable')}</strong>
          <span>{error?.status === 403 ? ui('Access denied for the current project.') : ui('No fallback data is shown.')}</span>
        </div>
      ) : state === 'loading' || !summary ? (
        <div className="overview-inline-state" role="status">{ui('Loading Runtime Evaluation summary...')}</div>
      ) : (
        <>
          <div className="runtime-evaluation-grid">
            <div className="runtime-evaluation-readout runtime-evaluation-readout-primary">
              <span>{ui('Runtime runs')}</span>
              <strong>{summary.runCount}</strong>
            </div>
            <div className="runtime-evaluation-readout">
              <span>{ui('Execution success')}</span>
              <strong>{formatMetric(summary.metrics.executionSuccess)}</strong>
            </div>
            <div className="runtime-evaluation-readout">
              <span>{ui('Completed')}</span>
              <strong>{summary.execution.success}</strong>
            </div>
            <div className="runtime-evaluation-readout">
              <span>{ui('Failed')}</span>
              <strong>{summary.execution.failure}</strong>
            </div>
            <div className="runtime-evaluation-readout">
              <span>{ui('Running')}</span>
              <strong>{summary.execution.running}</strong>
            </div>
            <div className="runtime-evaluation-readout">
              <span>{ui('Approval required')}</span>
              <strong>{summary.execution.approvalRequired}</strong>
            </div>
          </div>
          <div className="overview-summary-note">
            <Activity size={14} strokeWidth={1.8} />
            <span>{ui('Read-only values supplied by Runtime Evaluation API.')}</span>
          </div>
        </>
      )}

      <div className="panel-footer">
        <button className="footer-link" onClick={onNavigate} type="button">
          {ui('Open Evaluation')} <span aria-hidden="true">→</span>
        </button>
      </div>
    </section>
  )
}
