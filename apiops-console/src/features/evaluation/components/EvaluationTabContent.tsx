import { Activity, Clock3, DollarSign, Info, ShieldAlert, Wrench } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { RuntimeEvaluationSummary, RuntimeMetric, RuntimeMetricAggregate, RuntimeRunDetail } from '../types'

type EvaluationTabContentProps = {
  detail: RuntimeRunDetail | null
  summary: RuntimeEvaluationSummary
}

const validationMetrics = [
  { key: 'validJson', label: 'VALID_JSON' },
  { key: 'schemaValid', label: 'SCHEMA_VALID' },
  { key: 'contractAccepted', label: 'CONTRACT_ACCEPTED' },
] as const

const latencyMetrics = [
  { key: 'wallClockLatencyMs', label: 'Wall-clock latency' },
  { key: 'modelLatencyMs', label: 'Model latency' },
] as const

const usageMetrics = [
  { key: 'promptTokens', label: 'Prompt tokens' },
  { key: 'completionTokens', label: 'Completion tokens' },
  { key: 'totalTokens', label: 'Total tokens' },
  { key: 'cost', label: 'Cost' },
] as const

function statusLabel(status: RuntimeMetric['status']) {
  return status === 'NOT_APPLICABLE' ? 'N/A' : status
}

function statusClass(status: RuntimeMetric['status']) {
  return status === 'NOT_APPLICABLE' ? 'n-a' : status.toLowerCase()
}

function displayMetric(metric: RuntimeMetric | RuntimeMetricAggregate | undefined, percentage = false) {
  if (!metric || metric.status !== 'VALUE') return statusLabel(metric?.status ?? 'NOT_APPLICABLE')
  const value = 'mean' in metric ? metric.mean : metric.value
  if (value === null) return 'UNKNOWN'
  if (percentage) return `${(value * 100).toFixed(1)}%`
  const rendered = Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1)
  return metric.unit ? `${rendered} ${metric.unit}` : rendered
}

function MetricBadge({ metric, percentage = false }: { metric: RuntimeMetric | RuntimeMetricAggregate | undefined; percentage?: boolean }) {
  const status = metric?.status ?? 'NOT_APPLICABLE'
  return <span className={`evaluation-cell-value evaluation-cell-${statusClass(status)}`}>{displayMetric(metric, percentage)}</span>
}

function DetailMetricCard({ detail, keyName, label, percentage = false }: { detail: RuntimeRunDetail; keyName: string; label: string; percentage?: boolean }) {
  const { ui } = useConsoleLanguage()
  const metric = detail.metrics[keyName]
  return (
    <section className="evaluation-metric-detail-card panel">
      <div className="evaluation-metric-detail-heading">
        <div>
          <h3>{ui(label)}</h3>
          <p>{metric.reason ?? `${ui('Observed on')} ${detail.traceId}`}</p>
        </div>
        <MetricBadge metric={metric} percentage={percentage} />
      </div>
      <div className="evaluation-breakdown-list">
        <div><span>{ui('Status')}</span><strong>{statusLabel(metric.status)}</strong></div>
        <div><span>{ui('Trace records')}</span><strong>{detail.traceRecordCount}</strong></div>
      </div>
    </section>
  )
}

function AggregateMetricCard({ metric, label, percentage = false }: { metric: RuntimeMetricAggregate | undefined; label: string; percentage?: boolean }) {
  const { ui } = useConsoleLanguage()
  return (
    <section className="evaluation-metric-detail-card panel">
      <div className="evaluation-metric-detail-heading">
        <div>
          <h3>{ui(label)}</h3>
          <p>{metric?.reason ?? ui('Aggregated from runtime execution facts.')}</p>
        </div>
        <MetricBadge metric={metric} percentage={percentage} />
      </div>
      <div className="evaluation-breakdown-list">
        <div><span>{ui('Status')}</span><strong>{statusLabel(metric?.status ?? 'NOT_APPLICABLE')}</strong></div>
        <div><span>{ui('Runs / values')}</span><strong>{metric?.totalCount ?? 0} / {metric?.valueCount ?? 0}</strong></div>
        <div><span>{ui('UNKNOWN / N/A')}</span><strong>{metric?.unknownCount ?? 0} / {metric?.notApplicableCount ?? 0}</strong></div>
      </div>
    </section>
  )
}

function NoRunSelected() {
  const { ui } = useConsoleLanguage()
  return <section className="evaluation-readout-card panel"><p className="evaluation-empty-state">{ui('Select a runtime run to inspect its detailed facts.')}</p></section>
}

export function EvaluationOverviewTab({ detail, summary }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <section className="evaluation-readout-card panel">
        <div className="evaluation-section-heading">
          <div>
            <h2>{ui('Runtime readout')}</h2>
            <p>{ui('Only observed execution, validation, tool, safety, latency, token, and cost facts are included.')}</p>
          </div>
          <Activity size={17} strokeWidth={1.8} />
        </div>
        <div className="evaluation-readout-metrics">
          <div><span>{ui('Executions')}</span><strong>{summary.execution.total}</strong></div>
          <div><span>{ui('Success')}</span><strong>{summary.execution.success}</strong></div>
          <div><span>{ui('Failure')}</span><strong>{summary.execution.failure}</strong></div>
          <div><span>{ui('Safety UNKNOWN')}</span><strong>{summary.safety.unknown}</strong></div>
        </div>
      </section>
      {detail ? (
        <section className="evaluation-recent-cases panel">
          <div className="evaluation-section-heading">
            <h2>{ui('Selected runtime facts')}</h2>
            <Info size={15} strokeWidth={1.8} />
          </div>
          <div className="evaluation-breakdown-list">
            <div><span>{ui('Tool attempts')}</span><strong>{detail.toolCounts.attempted}</strong></div>
            <div><span>{ui('Safety result')}</span><strong>{detail.safetyOutcome ?? 'UNKNOWN'}</strong></div>
            <div><span>{ui('Wall-clock latency')}</span><MetricBadge metric={detail.metrics.wallClockLatencyMs} /></div>
            <div><span>{ui('Token usage')}</span><MetricBadge metric={detail.metrics.totalTokens} /></div>
          </div>
        </section>
      ) : <NoRunSelected />}
    </div>
  )
}

export function EvaluationValidationTab({ detail, summary }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro">
        <div><h2>{ui('Validation')}</h2><p>{ui('Validation facts come from the existing TestCase generation validator; they are N/A for Diagnosis runs.')}</p></div>
        <Info size={18} strokeWidth={1.8} />
      </div>
      <div className="evaluation-metric-detail-grid">
        {validationMetrics.map(({ key, label }) => <AggregateMetricCard key={key} label={label} metric={summary.metrics[key]} percentage />)}
      </div>
      {detail ? <div className="evaluation-metric-detail-grid">{validationMetrics.map(({ key, label }) => <DetailMetricCard detail={detail} key={key} keyName={key} label={label} percentage />)}</div> : <NoRunSelected />}
    </div>
  )
}

export function EvaluationToolTab({ detail, summary }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  const tool = detail?.toolCounts ?? summary.tool
  const outcomes = Object.entries(summary.safety.explicitOutcomes)
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro">
        <div><h2>{ui('Tool Execution')}</h2><p>{ui('Counts are derived from existing ToolIntent and ToolResult trace facts.')}</p></div>
        <Wrench size={18} strokeWidth={1.8} />
      </div>
      <section className="evaluation-readout-card panel">
        <div className="evaluation-readout-metrics">
          <div><span>{ui('Attempted')}</span><strong>{tool.attempted}</strong></div>
          <div><span>SUCCESS</span><strong>{tool.success}</strong></div>
          <div><span>FAILED</span><strong>{tool.failed}</strong></div>
          <div><span>DENIED</span><strong>{tool.denied}</strong></div>
          <div><span>TIMEOUT</span><strong>{tool.timeout}</strong></div>
          <div><span>UNKNOWN / N/A</span><strong>{tool.unknown} / {tool.notApplicable}</strong></div>
        </div>
      </section>
      <section className="evaluation-metric-detail-card panel">
        <div className="evaluation-section-heading"><h2>{ui('Safety / guardrail outcomes')}</h2><ShieldAlert size={17} strokeWidth={1.8} /></div>
        <div className="evaluation-breakdown-list">
          {outcomes.length ? outcomes.map(([outcome, count]) => <div key={outcome}><span>{outcome}</span><strong>{count}</strong></div>) : null}
          <div><span>{ui('UNKNOWN (no explicit outcome)')}</span><strong>{detail?.safetyStatus === 'UNKNOWN' ? 1 : summary.safety.unknown}</strong></div>
        </div>
      </section>
    </div>
  )
}

export function EvaluationLatencyTab({ detail, summary }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro"><div><h2>{ui('Latency')}</h2><p>{ui('Wall-clock latency is measured at the agent boundary; model latency is summed from terminal model-call facts.')}</p></div><Clock3 size={18} strokeWidth={1.8} /></div>
      <div className="evaluation-metric-detail-grid">
        {latencyMetrics.map(({ key, label }) => <AggregateMetricCard key={key} label={label} metric={summary.metrics[key]} />)}
      </div>
      {detail ? <div className="evaluation-metric-detail-grid">{latencyMetrics.map(({ key, label }) => <DetailMetricCard detail={detail} key={key} keyName={key} label={label} />)}</div> : <NoRunSelected />}
    </div>
  )
}

export function EvaluationTokenCostTab({ detail, summary }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro"><div><h2>{ui('Token & Cost')}</h2><p>{ui('Missing provider usage remains UNKNOWN; cost is UNKNOWN until runtime pricing facts exist.')}</p></div><DollarSign size={18} strokeWidth={1.8} /></div>
      <div className="evaluation-metric-detail-grid">
        {usageMetrics.map(({ key, label }) => <AggregateMetricCard key={key} label={label} metric={summary.metrics[key]} />)}
      </div>
      {detail ? <div className="evaluation-metric-detail-grid">{usageMetrics.map(({ key, label }) => <DetailMetricCard detail={detail} key={key} keyName={key} label={label} />)}</div> : <NoRunSelected />}
    </div>
  )
}
