import { Activity, Info, ShieldAlert, Timer, Wrench } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { RuntimeEvaluationSummary, RuntimeMetricAggregate } from '../types'

type EvaluationOverviewPanelsProps = {
  summary: RuntimeEvaluationSummary
}

function formatMetric(metric: RuntimeMetricAggregate | undefined, percentage = false) {
  if (!metric || metric.status !== 'VALUE' || metric.mean === null) {
    if (metric?.status === 'NOT_APPLICABLE') return 'N/A'
    return metric?.status ?? 'UNKNOWN'
  }
  if (percentage) return `${(metric.mean * 100).toFixed(1)}%`
  return `${metric.mean.toFixed(1)}${metric.unit ? ` ${metric.unit}` : ''}`
}

function MetricValue({ metric, percentage = false }: { metric: RuntimeMetricAggregate | undefined; percentage?: boolean }) {
  const state = metric?.status ?? 'NOT_APPLICABLE'
  return (
    <strong className={`evaluation-value evaluation-value-${state.toLowerCase()}`}>
      {formatMetric(metric, percentage)}
    </strong>
  )
}

function CountRow({ label, value }: { label: string; value: number }) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-configuration-row">
      <span>{ui(label)}</span>
      <strong>{value}</strong>
    </div>
  )
}

export function EvaluationOverviewPanels({ summary }: EvaluationOverviewPanelsProps) {
  const { ui } = useConsoleLanguage()

  return (
    <div className="evaluation-overview-panels">
      <section className="evaluation-overview-card panel" aria-labelledby="core-metrics-title">
        <div className="evaluation-section-heading">
          <h2 id="core-metrics-title">{ui('Runtime Overview')}</h2>
          <Activity size={15} strokeWidth={1.8} />
        </div>
        <div className="evaluation-metric-grid">
          <div className="evaluation-metric-card">
            <span>{ui('Runs')}</span>
            <strong>{summary.runCount}</strong>
          </div>
          <div className="evaluation-metric-card">
            <span>{ui('Execution success')}</span>
            <MetricValue metric={summary.metrics.executionSuccess} percentage />
          </div>
          <div className="evaluation-metric-card">
            <span>{ui('Completed')}</span>
            <strong>{summary.execution.success}</strong>
          </div>
          <div className="evaluation-metric-card">
            <span>{ui('Failed')}</span>
            <strong>{summary.execution.failure}</strong>
          </div>
          <div className="evaluation-metric-card">
            <span>{ui('Running')}</span>
            <strong>{summary.execution.running}</strong>
          </div>
          <div className="evaluation-metric-card">
            <span>{ui('Approval required')}</span>
            <strong>{summary.execution.approvalRequired}</strong>
          </div>
        </div>
      </section>

      <section className="evaluation-overview-card panel" aria-labelledby="validation-summary-title">
        <div className="evaluation-section-heading">
          <h2 id="validation-summary-title">{ui('Validation')}</h2>
          <Timer size={15} strokeWidth={1.8} />
        </div>
        <div className="evaluation-category-list">
          {[
            ['VALID_JSON', 'validJson'],
            ['SCHEMA_VALID', 'schemaValid'],
            ['CONTRACT_ACCEPTED', 'contractAccepted'],
          ].map(([label, key]) => {
            const metric = summary.metrics[key]
            const width = metric?.rate === null || metric?.rate === undefined ? 0 : metric.rate * 100
            return (
              <div className="evaluation-category-row" key={key}>
                <span>{label}</span>
                <div className="evaluation-progress-track" aria-label={`${label} ${formatMetric(metric, true)}`}>
                  <span style={{ width: `${Math.max(0, Math.min(100, width))}%` }} />
                </div>
                <MetricValue metric={metric} percentage />
              </div>
            )
          })}
        </div>
      </section>

      <section className="evaluation-overview-card panel" aria-labelledby="tool-summary-title">
        <div className="evaluation-section-heading">
          <h2 id="tool-summary-title">{ui('Tool Execution')}</h2>
          <Wrench size={15} strokeWidth={1.8} />
        </div>
        <div className="evaluation-configuration-grid">
          <CountRow label="Attempts" value={summary.tool.attempted} />
          <CountRow label="SUCCESS" value={summary.tool.success} />
          <CountRow label="FAILED" value={summary.tool.failed} />
          <CountRow label="DENIED" value={summary.tool.denied} />
          <CountRow label="TIMEOUT" value={summary.tool.timeout} />
          <CountRow label="UNKNOWN" value={summary.tool.unknown} />
          <CountRow label="N/A (no tool attempt)" value={summary.tool.notApplicable} />
          <div className="evaluation-configuration-row">
            <span><ShieldAlert size={13} strokeWidth={1.8} /> {ui('Safety outcomes')}</span>
            <strong>{Object.values(summary.safety.explicitOutcomes).reduce((total, value) => total + value, 0)} / {summary.safety.unknown} {ui('explicit / UNKNOWN')}</strong>
          </div>
        </div>
      </section>
    </div>
  )
}
