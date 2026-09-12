import { useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { configurationSummary } from '../benchmarkViewModel'
import type { BenchmarkRunFilter, BenchmarkRunSummary } from '../types'

type Props = { filter: BenchmarkRunFilter; onFilterChange: (filter: BenchmarkRunFilter) => void; onQueryChange: (query: string) => void; onSelect: (id: string) => void; query: string; runs: BenchmarkRunSummary[]; selectedViewId: string | null }
export function BenchmarkRuns({ filter, onFilterChange, onQueryChange, onSelect, query, runs, selectedViewId }: Props) {
  const { ui, language } = useConsoleLanguage()
  const [expanded, setExpanded] = useState(Boolean(query) || filter !== 'ALL')
  const visible = expanded ? runs : runs.slice(0, 6)
  return <section className="panel benchmark-recent-runs" aria-label={ui('Published Runs')}>
    <div className="benchmark-section-heading"><h2>{ui('Published Runs')}</h2><button type="button" className="panel-action" aria-expanded={expanded} aria-controls="benchmark-recent-list" onClick={() => { setExpanded(!expanded); if (expanded) { onQueryChange(''); onFilterChange('ALL') } }}>{ui(expanded ? 'Collapse' : 'Filter')}</button></div>
    {expanded && <div className="benchmark-controls">
      <input aria-label={ui('Search benchmark runs')} placeholder={ui('Search benchmark runs...')} value={query} onChange={event => onQueryChange(event.target.value)} />
      <select aria-label={ui('Execution status')} value={filter} onChange={event => onFilterChange(event.target.value as BenchmarkRunFilter)}>{['ALL', 'COMPLETED', 'FAILED'].map(status => <option key={status}>{status}</option>)}</select>
    </div>}
    <div id="benchmark-recent-list" className="benchmark-table-wrap" tabIndex={0} role="region" aria-label={ui('Recent Benchmark Runs')}>
      <table className="benchmark-data-table benchmark-runs-table"><thead><tr>{['Evaluation Run', 'Dataset', 'Model', 'Tasks', 'Completed At', 'Execution Status', 'View'].map(label => <th key={label}>{ui(label)}</th>)}</tr></thead>
        <tbody>{visible.map(run => <tr key={run.evaluationRunId} className={run.evaluationRunId === selectedViewId ? 'is-selected' : ''} onClick={() => onSelect(run.evaluationRunId)}>
          <td><span className="benchmark-recent-id" title={run.evaluationRunId}>{run.displayName}</span></td>
          <td><span className="benchmark-recent-dataset" title={run.datasetId}>APIOps-Bench 105</span><small>{run.datasetVersion}</small></td>
          <td><span className="benchmark-recent-model" title={configurationSummary(run.model)}>{configurationSummary(run.model)}</span></td>
          <td>{run.selectedTaskCount}</td>
          <td><time dateTime={run.completedAt} title={run.completedAt}>{Number.isNaN(Date.parse(run.completedAt)) ? run.completedAt : new Date(run.completedAt).toLocaleString(undefined, {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}</time></td>
          <td><span className="benchmark-execution-badge">{run.status}</span></td>
          <td><button className="benchmark-text-button" type="button" aria-current={run.evaluationRunId === selectedViewId ? 'true' : undefined} aria-label={ui('Select') + ' ' + run.evaluationRunId} onClick={event => { event.stopPropagation(); onSelect(run.evaluationRunId) }}>{ui(run.evaluationRunId === selectedViewId ? 'Selected' : 'View')}</button></td>
        </tr>)}</tbody>
      </table>
    </div>
    {!runs.length && <p className="benchmark-caption" role="status">{ui('No benchmark runs match the current filters.')}</p>}
    <p className="benchmark-caption">{ui('COMPLETED describes execution, not a PASS verdict.')}</p>
    <p className="benchmark-caption">{language === 'zh-CN' ? '仅显示 publication manifest 明确发布的完整结果。' : 'Only complete results explicitly declared by the publication manifest are shown.'}</p>
  </section>
}
