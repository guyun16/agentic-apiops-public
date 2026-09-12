import { Database, BookOpen } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { categoryDistribution, categoryRows, formatMetric, percent } from '../benchmarkViewModel'
import type { BenchmarkRunDetail, BenchmarkTask } from '../types'

export function BenchmarkScorecards({ detail }: { detail: BenchmarkRunDetail }) {
  const { ui } = useConsoleLanguage()
  const cards = [
    { label: 'Selected Tasks', value: detail.selectedTaskCount, tone: 'total' },
    { label: 'PASS', value: detail.taskSuccess.passCount, tone: 'pass' },
    { label: 'FAIL', value: detail.taskSuccess.failCount, tone: 'fail' },
    { label: 'UNKNOWN', value: detail.taskSuccess.unknownCount, tone: 'unknown' },
    { label: 'Task Success Rate', value: detail.taskSuccess.rate === null ? null : percent(detail.taskSuccess.rate), tone: 'rate' },
  ]
  return <section className="benchmark-formal-summary" aria-label={ui('Formal Result Summary')}>
    <div className="benchmark-formal-cards">{cards.map(card => <div className={'panel benchmark-formal-card is-' + card.tone} key={card.label}><span>{ui(card.label)}</span><strong className={card.value == null ? 'is-unavailable' : undefined}>{card.value ?? 'MISSING'}</strong></div>)}</div>
    <div className="benchmark-formal-footer"><span>N/A <strong>{detail.taskSuccess.notApplicableCount ?? 'MISSING'}</strong></span><small>{ui('PASS / (PASS + FAIL); UNKNOWN and N/A excluded')}</small></div>
  </section>
}
export function BenchmarkOverview({ detail }: { detail: BenchmarkRunDetail }) {
  const { ui } = useConsoleLanguage()
  return <section className="panel benchmark-secondary-panel" aria-label={ui('Secondary Metrics')}><div className="benchmark-section-heading"><h2>{ui('Secondary Metrics')}</h2><span className="benchmark-caption">{ui('Persisted evaluation metrics')}</span></div>
    <div className="benchmark-secondary-grid">{detail.aggregateMetrics.map(metric => <article className="benchmark-secondary-metric" key={metric.metric}>
      <span title={metric.metric}>{metric.metric.replace(/_/g, ' ')}</span><strong className={metric.state === 'VALUE' ? '' : 'is-unavailable'}>{formatMetric(metric)}</strong>
      <small>{metric.state === 'NOT_APPLICABLE' ? 'N/A' : metric.state} · {metric.valueCount ?? 'MISSING'} {ui('VALUE samples')}</small>
      <details><summary>{ui('Metric scope')}</summary><p>{ui('Applicable samples')}: {metric.applicableCount ?? 'MISSING'} · {ui('Total samples')}: {metric.totalCount ?? 'MISSING'}</p><p>UNKNOWN: {metric.unknownCount ?? 'MISSING'} · ERROR: {metric.errorCount ?? 'MISSING'} · N/A: {metric.notApplicableCount ?? 'MISSING'}</p>{metric.reason && <p>{metric.reason}</p>}</details>
    </article>)}</div>
    {!detail.aggregateMetrics.length && <p className="benchmark-caption">{ui('No saved ratio metrics are available.')}</p>}
  </section>
}

export function BenchmarkCategories({ detail, tasks, tasksState, onSelect }: { detail: BenchmarkRunDetail; tasks: BenchmarkTask[]; tasksState: 'loading' | 'ready' | 'error'; onSelect: (type: string) => void }) {
  const { ui } = useConsoleLanguage()
  const rows = categoryRows(tasks, detail.executedTaskCount)
  return <section className="panel benchmark-category-panel" aria-label={ui('Category Performance')}>
    <div className="benchmark-section-heading"><h2>{ui('Category Performance')}</h2><span className="benchmark-caption">{ui('Selected Tasks')}: {detail.selectedTaskCount} · {ui('Executed Tasks')}: {detail.executedTaskCount}</span></div>
    <p className="benchmark-caption">{ui('Counts from the complete persisted task response. Select a type to inspect its task metrics.')}</p>
    {tasksState !== 'ready' ? <p role="status">{ui(tasksState === 'loading' ? 'Loading task results' : 'Task results unavailable')}</p> : <div className="benchmark-category-rows">{rows.map(row => {
      const segments = categoryDistribution(row)
      return <div className="benchmark-category-row" key={row.type}>
        <div className="benchmark-category-label"><button className="benchmark-text-button" type="button" onClick={() => onSelect(row.type)}>{ui(row.label)}</button><span>{row.complete ? row.count : 'MISSING'} {ui('Tasks')}</span>{!row.recognized && <small>{ui('Unrecognized task type')}</small>}</div>
        <div className="benchmark-category-results">
          <div className="benchmark-distribution" role="img" aria-label={ui(row.label) + ': ' + (row.complete ? segments.map(segment => `${segment.count} ${segment.label}`).join(', ') : 'MISSING')}>
            {segments.map(segment => <span key={segment.status} className={'benchmark-segment is-' + segment.status.toLowerCase()} style={{ width: segment.width + '%' }} />)}
          </div>
          <div className="benchmark-distribution-labels">{row.complete ? segments.map(segment => <span className={'benchmark-count-' + segment.status.toLowerCase()} key={segment.status}><strong>{segment.count}</strong> {segment.label}</span>) : <span>MISSING</span>}</div>
        </div>
      </div>
    })}</div>}
  </section>
}
export function BenchmarkInfo({ detail, tasks, tasksState }: { detail: BenchmarkRunDetail; tasks: BenchmarkTask[]; tasksState: 'loading' | 'ready' | 'error' }) {
  const { ui } = useConsoleLanguage()
  const facts = [['Dataset', detail.datasetId], ['Dataset Version', detail.datasetVersion], ['Dataset Split', detail.datasetSplit ?? 'UNKNOWN'], ['Dataset total size', 'MISSING'], ['Selected Tasks', String(detail.selectedTaskCount)], ['Executed Tasks', String(detail.executedTaskCount)], ['Evaluated Tasks', String(detail.evaluatedTaskCount)], ['Task Schema', detail.taskSchemaVersion], ['Data Source', detail.dataSource]]
  return <aside className="benchmark-info-column"><section className="panel benchmark-info-card"><h2><Database size={18} />{ui('Dataset Info')}</h2><dl>{facts.map(([label, value]) => <div key={label}><dt>{ui(label)}</dt><dd>{value}</dd></div>)}</dl><p className="benchmark-caption">{ui('Dataset total size is not provided; selected tasks are this run only.')}</p><h3>{ui('Execution mode')}</h3>{tasksState !== 'ready' && <p role="status">{ui(tasksState === 'loading' ? 'Loading task results' : 'Task results unavailable')}</p>}{[...new Set(tasks.map(task => task.executionMode))].map(mode => <p className="benchmark-source" key={mode}>{mode}</p>)}</section>
    <section className="panel benchmark-info-card"><h2><BookOpen size={18} />{ui('Metric Definitions')}</h2><dl className="benchmark-definitions">
      <div><dt>{ui('Task Success Rate')}</dt><dd>{ui('PASS / (PASS + FAIL); UNKNOWN and N/A excluded')}</dd></div>
      <div><dt>{ui('Diagnosis Accuracy')}</dt><dd>{ui('Saved diagnosis_accuracy: exact match with expected diagnosis or an accepted alternative; VALUE samples only.')}</dd></div>
      <div><dt>{ui('Valid JSON Rate')}</dt><dd>{ui('Saved valid_json: JSON parsing validity; VALUE samples only. Does not establish executability.')}</dd></div>
      <div><dt>{ui('Safety Violation Count')}</dt><dd>{ui('Count not exposed by the result API')}</dd></div>
      <div><dt>{ui('Units and availability')}</dt><dd>{ui('Rates use %. Count, latency and cost are not plotted. N/A, UNKNOWN, MISSING, ERROR and numeric zero remain distinct.')}</dd></div>
    </dl></section></aside>
}
