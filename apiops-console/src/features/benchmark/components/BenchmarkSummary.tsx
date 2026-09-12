import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { configurationSummary } from '../benchmarkViewModel'
import type { BenchmarkRunSummary, BenchmarkTask } from '../types'
import { CopyValue } from './CopyValue'

type Props = { run: BenchmarkRunSummary; runs: BenchmarkRunSummary[]; onSelect: (id: string) => void; tasks: BenchmarkTask[]; tasksState: 'loading' | 'ready' | 'error' }

export function BenchmarkSummary({ run, runs, onSelect, tasks, tasksState }: Props) {
  const { ui } = useConsoleLanguage()
  const modes = tasksState === 'ready' ? [...new Set(tasks.map(task => task.executionMode))].join(' · ') || 'MISSING' : tasksState === 'loading' ? ui('Loading task results') : ui('Task results unavailable')
  return <section className="benchmark-result-context" aria-label={ui('Current result identity')}>
    <div className="benchmark-context-top">
      <label className="benchmark-result-selector"><span>{ui('Selected Benchmark Result')}</span>
        <select aria-label={ui('Selected Benchmark Result')} value={run.evaluationRunId} onChange={event => onSelect(event.target.value)}>
          {runs.map(item => <option key={item.evaluationRunId} value={item.evaluationRunId} title={item.evaluationRunId}>{item.displayName}</option>)}
        </select>
      </label>
      <span className="benchmark-execution-badge" title={ui('COMPLETED describes execution, not a PASS verdict.')}>{run.status}</span>
    </div>
    <div className="benchmark-context-facts">
      <span>{ui('Dataset')}: <strong>APIOps-Bench 105</strong></span>
      <span title={configurationSummary(run.model)}>{ui('Model')}: <strong>{configurationSummary(run.model)}</strong></span>
      <span>{ui('Completed At')}: <time dateTime={run.completedAt}>{Number.isNaN(Date.parse(run.completedAt)) ? run.completedAt : new Date(run.completedAt).toLocaleString()}</time></span>
      <span>{ui('Execution mode')}: <strong>{modes}</strong></span>
      {run.benchmarkRevision && <span>{ui('Revision')}: <CopyValue value={run.benchmarkRevision} /></span>}
    </div>
    <details className="benchmark-identity-run"><summary>{ui('Technical identity')}</summary><CopyValue value={run.evaluationRunId} /></details>
    {run.resultSource && <p className="benchmark-source-notice">{ui('Verified v5 artifact snapshot · API does not expose final outcome fields. Refresh reads historical APIs; this sealed snapshot stays pinned.')}</p>}
  </section>
}
