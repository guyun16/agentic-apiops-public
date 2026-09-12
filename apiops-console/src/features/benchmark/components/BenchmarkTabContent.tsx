import { BenchmarkInfo } from './BenchmarkOverview'
import type { FinalResultReport } from '../finalResultAdapter'
import { CheckCircle2, CircleX, Clock3, Database } from 'lucide-react'
import { useState } from 'react'
import { categories, configurationText, failureGroups, filterTasks, outcome } from '../benchmarkViewModel'
import { CopyValue } from './CopyValue'
import { BenchmarkCategories } from './BenchmarkOverview'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type {
  BenchmarkMetricResult,
  BenchmarkRunDetail,
  BenchmarkTask,
  BenchmarkTab,
} from '../types'

type BenchmarkTabContentProps = {
  finalReport?: FinalResultReport
  detail: BenchmarkRunDetail
  tasks: BenchmarkTask[]
  tasksState: 'loading' | 'ready' | 'error'
  category: string
  onCategoryChange: (category: string) => void
  tab: BenchmarkTab
}

function displayValue(value: unknown) {
  if (value === null || value === undefined) return 'MISSING'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return 'UNKNOWN'
  }
}

function metricValue(metric: BenchmarkMetricResult | undefined) {
  if (!metric) return 'MISSING'
  if (metric.status === 'NOT_APPLICABLE') return 'N/A'
  if (metric.status === 'UNKNOWN') return 'UNKNOWN'
  if (metric.status === 'ERROR') return 'ERROR'
  return displayValue(metric.value) + (metric.unit ? ' ' + metric.unit : '')
}

function TaskStatus({ status }: { status: BenchmarkTask['status'] }) {
  const icon = status === 'SUCCESS'
    ? <CheckCircle2 size={14} strokeWidth={1.9} />
    : status === 'TIMEOUT'
      ? <Clock3 size={14} strokeWidth={1.9} />
      : <CircleX size={14} strokeWidth={1.9} />
  return <span className={'benchmark-task-status benchmark-task-status-' + status.toLowerCase()}>{icon}{status}</span>
}

function TaskSuccess({ task }: { task: BenchmarkTask }) {
  const status = outcome(task)
  return <span className={'benchmark-value benchmark-value-' + status.toLowerCase()}>{status === 'NOT_APPLICABLE' ? 'N/A' : status}</span>
}

function TasksTab({ detail, tasks, tasksState, category, onCategoryChange }: Omit<BenchmarkTabContentProps, 'tab'>) {
  const { ui } = useConsoleLanguage()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState('ALL')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const visible = filterTasks(tasks, query, category, result)
  const selected = visible.find(task => task.benchmarkTaskId === selectedId)
  return (
    <section className="benchmark-tab-card benchmark-tasks-card panel">
      <div className="benchmark-tab-heading">
        <div>
          <h2>{ui('Benchmark Tasks')}</h2>
          <p>{ui('Task-level envelopes and EvaluationResult metrics from the persisted artifacts.')}</p>
        </div>
        <span className="benchmark-panel-count">{tasks.length} / {detail.selectedTaskCount}</span>
      </div>
      <div className="benchmark-controls">
        <input aria-label={ui('Search tasks')} placeholder={ui('Search tasks')} value={query} onChange={event => { setQuery(event.target.value); setSelectedId(null) }} />
        <select aria-label={ui('Task category')} value={category} onChange={event => { onCategoryChange(event.target.value); setSelectedId(null) }}><option value="ALL">{ui('All types')}</option>{[...new Set([...Object.keys(categories), ...tasks.map(task => task.taskType)])].map(type => <option value={type} key={type}>{ui(categories[type] ?? type)}</option>)}</select>
        <select aria-label={ui('Formal outcome')} value={result} onChange={event => { setResult(event.target.value); setSelectedId(null) }}><option value="ALL">{ui('All outcomes')}</option>{[...new Set(['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE', 'MISSING', ...tasks.map(outcome)])].map(status => <option key={status}>{status}</option>)}</select>
      </div>
      <p className="benchmark-caption">{ui('Filters affect this task list only; official run scores remain unchanged.')}</p>
      {!visible.length && tasks.length > 0 ? <p role="status">{ui('No tasks match the current filters.')}</p> : null}
      {selected ? <TaskDetail task={selected} /> : null}
      {tasksState === 'loading' ? <p className="benchmark-inline-state">{ui('Loading task results')}</p> : null}
      {tasksState === 'error' ? <p className="benchmark-inline-state">{ui('Task results unavailable')}</p> : null}
      {tasksState === 'ready' && tasks.length === 0 ? <p className="benchmark-inline-state">{ui('No task results are available.')}</p> : null}
      {tasks.length > 0 ? (
        <div className="benchmark-table-wrap" tabIndex={0} role="region" aria-label={ui("Benchmark Tasks")}>
          <table className="benchmark-task-table">
            <thead>
              <tr>
                {['Benchmark Task', 'Category', 'Evaluation Result', 'Execution Status', 'Mode', 'Duration', 'Details'].map(label => <th key={label}>{ui(label)}</th>)}
              </tr>
            </thead>
            <tbody>
              {visible.map((task) => (
                <tr className={selectedId === task.benchmarkTaskId ? 'is-selected' : ''} key={task.benchmarkTaskId}>
                  <td><span className="benchmark-task-id" title={task.benchmarkTaskId}>{task.benchmarkTaskId}</span></td>
                  <td>{ui(categories[task.taskType] ?? task.taskType)}</td>
                  <td><TaskSuccess task={task} /></td>
                  <td><TaskStatus status={task.status} /></td>
                  <td>{task.executionMode}</td>
                  <td>{task.durationMs === null ? 'MISSING' : task.durationMs.toFixed(2) + ' ms'}</td>
                  <td><button className="benchmark-text-button" type="button" aria-pressed={selectedId === task.benchmarkTaskId} aria-label={ui('Details') + ' ' + task.benchmarkTaskId} onClick={() => setSelectedId(selectedId === task.benchmarkTaskId ? null : task.benchmarkTaskId)}>{ui(selectedId === task.benchmarkTaskId ? 'Collapse' : 'Details')}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="benchmark-table-footer">{ui('Showing')} {visible.length} {ui('persisted task results')} {ui('of')} {detail.selectedTaskCount}</div>
    </section>
  )
}

function FailuresTab({ tasks }: { tasks: BenchmarkTask[] }) {
  const { ui } = useConsoleLanguage()
  const groups = failureGroups(tasks)
  return <div className="benchmark-tab-stack">{groups.map(group => <section className={'panel benchmark-failure-group is-' + group.tone} key={group.title}>
    <div className="benchmark-section-heading"><h2>{ui(group.title)}</h2><span>{group.members.length}</span></div>
    {!group.members.length && <p className="benchmark-caption">{ui('No matching tasks')}</p>}
    {group.members.map(task => <article className="benchmark-failure-item" key={task.benchmarkTaskId}>
      <div className="benchmark-failure-heading"><strong className="benchmark-task-id" title={task.benchmarkTaskId}>{task.benchmarkTaskId}</strong><TaskSuccess task={task} /><TaskStatus status={task.status} /></div>
      <p className="benchmark-caption">{ui(categories[task.taskType] ?? task.taskType)} · {task.executionMode}</p>
      <p>{task.failureReason ?? ui('No failure reason provided')}</p>
      {task.formalOutcome ? <FormalOutcomeEvidence task={task} /> : <ul className="benchmark-condition-list">{task.taskSuccess?.conditions.filter(condition => condition.required && condition.status !== 'PASS').map((condition, index) => <li key={index}><strong>{condition.status} · {condition.name}</strong><span>{condition.reason}</span></li>)}</ul>}
      <details><summary>{ui('Task detail')}</summary><TaskDetail task={task} /></details>
    </article>)}
  </section>)}</div>
}

function ReproducibilityTab({ detail, tasks, tasksState, finalReport }: Pick<BenchmarkTabContentProps, 'detail' | 'tasks' | 'tasksState' | 'finalReport'>) {
  const { ui } = useConsoleLanguage()
  const fields = [
    [ui('Dataset ID'), detail.datasetId],
    [ui('Dataset Version'), detail.datasetVersion],
    [ui('Dataset Split'), detail.datasetSplit ?? 'UNKNOWN'],
    [ui('Task Schema'), detail.taskSchemaVersion],
    [ui('Data Source'), detail.dataSource],
    [ui('Execution mode'), tasksState === 'ready' ? [...new Set(tasks.map(task => task.executionMode))].join(' · ') || 'MISSING' : ui(tasksState === 'loading' ? 'Loading task results' : 'Task results unavailable')],
    [ui('Model'), configurationText(detail.model)],
    [ui('Prompt Version'), detail.prompt.map((value) => configurationText(value)).join(' · ') || 'UNKNOWN'],
    [ui('Evaluator Version'), configurationText(detail.evaluator)],
    [ui('Benchmark Config'), detail.benchmarkConfigVersion ?? 'UNKNOWN'],
    [ui('Model parameters / Tools / Workflow'), ui('Snapshot fields not exposed by this API')],
  ]
  const references = detail.artifactReferences
  const artifactRows = [
    [ui('Run artifact'), references.run],
    [ui('Baseline run artifact'), references.baselineRun],
    [ui('Baseline config artifact'), references.baselineConfig],
    [ui('Reproducibility artifact'), references.reproducibility],
    [ui('Evaluation CSV artifact'), references.evaluationCsv],
    [ui('Baseline report artifact'), references.baselineReport],
    [ui('Failure inventory artifact'), references.failureInventory],
    [ui('Collateral damage artifact'), references.collateralDamage],
  ]
  return (
    <div className="benchmark-tab-stack">
      <section className="benchmark-tab-card panel">
        <div className="benchmark-section-heading">
          <div>
            <h2>{ui('Configuration Snapshot')}</h2>
            <p>{ui('Configuration and artifact references captured for this existing result.')}</p>
          </div>
          <Database size={16} strokeWidth={1.8} />
        </div>
        <div className="benchmark-repro-grid">
          {fields.map(([label, value]) => <div key={label}><span>{label}</span><strong title={value}>{value}</strong></div>)}
        </div>
      </section>
      {finalReport && <section className="panel benchmark-tab-card"><h2>{ui('Final v5 source evidence')}</h2><p className="benchmark-caption">{ui('Verified artifact snapshot, not an API response. Only allowlisted facts are bundled; source files are not edited.')}</p><CopyValue value={finalReport.revision} /><p>{ui('Verified At')}: {finalReport.verifiedAt}</p><p>{ui('Published display fields')}: DEV / HELD_OUT Pass Rate; Quality Validation — {finalReport.published.source}.</p><p>{ui('Reproducibility')}: <strong>{finalReport.reproducibility.status}</strong> — {ui(finalReport.reproducibility.reason)}</p><details><summary>{ui('Source paths and SHA-256')} ({finalReport.sources.length})</summary>{finalReport.sources.map(source => <div className="benchmark-formal-evidence" key={source.path}><CopyValue value={source.path} /><CopyValue value={source.sha256} /></div>)}</details><p className="benchmark-caption">{ui('The Task Success Rate definition below describes legacy v1 diagnostics, not the official v5 Pass Rate or Outcome Accuracy.')}</p></section>}
      <BenchmarkInfo detail={detail} tasks={tasks} tasksState={tasksState} />
      <section className="benchmark-tab-card panel">
        <h3>{ui('Artifact References')}</h3><p className="benchmark-caption">{ui('Local references only; availability and download are not verified by this API.')}</p>
        <div className="benchmark-artifact-list">
          {artifactRows.filter(([, value]) => value != null).map(([label, value]) => <div key={label}><span>{label}</span>{value ? <CopyValue value={value} /> : <code>MISSING</code>}</div>)}
          <details><summary>{ui('Task result artifacts')} ({references.taskResults.length})</summary>{references.taskResults.map((ref, index) => <CopyValue key={index} value={ref} />)}</details>
        </div>
      </section>
    </div>
  )
}

export function BenchmarkTabContent({ detail, tasks, tasksState, tab, category, onCategoryChange, finalReport }: BenchmarkTabContentProps) {
  const { ui } = useConsoleLanguage()
  if ((tab === 'Tasks' || tab === 'Failures') && tasksState !== 'ready') {
    return <p role="status">{ui(tasksState === 'loading' ? 'Loading task results' : 'Task results unavailable')}</p>
  }
  if (tab === 'Overview') return null
  if (tab === 'Categories') return <BenchmarkCategories detail={detail} tasks={tasks} tasksState={tasksState} onSelect={onCategoryChange} />
  if (tab === 'Tasks') return <TasksTab detail={detail} tasks={tasks} tasksState={tasksState} category={category} onCategoryChange={onCategoryChange} />
  if (tab === 'Failures') return <FailuresTab tasks={tasks} />
  return <ReproducibilityTab finalReport={finalReport} detail={detail} tasks={tasks} tasksState={tasksState} />
}

function TaskDetail({ task }: { task: BenchmarkTask }) {
  const { ui } = useConsoleLanguage()
  return <article className="benchmark-task-detail" aria-label={ui('Task detail')}>
    <h3>{ui('Task detail')}</h3><CopyValue value={task.benchmarkTaskId} />
    <p>{ui('Formal outcome')}: <TaskSuccess task={task} /> · {ui('Execution status')}: <TaskStatus status={task.status} /></p>
    <p>{task.failureReason ?? ui('No failure reason provided')}</p>
    {task.formalOutcome ? <><FormalOutcomeEvidence task={task} /><p className="benchmark-caption">{ui('Legacy v1 strict conditions below are diagnostic evidence; the official v5 outcome is shown above.')}</p></> : <p className="benchmark-caption">{ui('Saved evaluation conditions below are formal results. No later audit verdict is supplied.')}</p>}
    <details open={!task.formalOutcome}><summary>{ui(task.formalOutcome ? 'Legacy v1 strict conditions' : 'Task success conditions')}</summary><ul className="benchmark-condition-list">{task.taskSuccess?.conditions.map((condition, index) => <li key={index}><strong>{condition.status} · {condition.name}</strong><span>{condition.reason}</span><small>{condition.metric ?? 'MISSING'} · {condition.metricStatus ?? 'MISSING'} · {condition.required ? 'required' : 'optional'}</small></li>)}</ul></details>
    <p>{ui('Expected / Actual: not provided by this API.')}</p>
    <details><summary>{ui('Metrics and evidence references')}</summary>{task.metrics.map(metric => <div key={metric.metric}><strong>{metric.metric}: {metricValue(metric)}</strong><p>{metric.reason}</p>{metric.details.map((text, index) => <p key={index}>{text}</p>)}</div>)}</details>
    <dl>{[['Category', task.taskType], ['Mode', task.executionMode], ['Duration', task.durationMs == null ? null : String(task.durationMs) + ' ms'], ['Failure Stage', task.failureStage], ['Failure Category', task.failureCategory], ['Failure Code', task.failureCode], ['Case ID', task.caseId], ['Evaluation', task.evaluationId], ['Agent Run', task.agentRunId], ['Trace', task.traceId], ['Java Run', task.runId == null ? null : String(task.runId)], ['Java Report', task.reportId], ['Artifact', task.artifactRef]].map(([label, value]) => <div key={label}><dt>{ui(label!)}</dt><dd>{value ? <CopyValue value={value} /> : 'MISSING'}</dd></div>)}</dl>
  </article>
}

function FormalOutcomeEvidence({ task }: { task: BenchmarkTask }) {
  const { ui } = useConsoleLanguage()
  const saved = task.formalOutcome
  if (!saved) return null
  return <div className="benchmark-formal-evidence"><strong>{ui('Official v5 outcome')}: {saved.status}</strong><p>{saved.revision} · {saved.split} · {saved.authority}</p><details><summary>{ui('Persisted outcome metrics')}</summary>{saved.metrics.map(metric => <p key={metric.metric}><strong>{metric.metric}</strong> · {metric.status === 'NOT_APPLICABLE' ? 'N/A' : metric.status} · {ui('Value')}: {metric.value ?? 'MISSING'} · {ui('Expected metric value')}: {metric.expectedValue ?? 'MISSING'}{metric.reason ? ' · ' + metric.reason : ''}</p>)}</details><p className="benchmark-caption">{ui('Recorded metric observations are evidence, not a new frontend verdict.')}</p></div>
}
