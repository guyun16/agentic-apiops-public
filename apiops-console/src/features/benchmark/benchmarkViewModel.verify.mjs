import assert from 'node:assert/strict'
import { categoryRows, failureGroups, filterTasks, formatMetric } from './benchmarkViewModel.ts'
const task = (id, outcome, execution = 'SUCCESS', category = 'FAILURE_DIAGNOSIS') => ({ benchmarkTaskId: id, taskType: category, status: execution, taskSuccess: outcome === null ? null : { status: outcome } })
const tasks = [task('a', 'FAIL'), task('b', 'UNKNOWN', 'TIMEOUT'), task('c', 'PASS', 'FAILED'), task('d', null), task('e', 'NOT_APPLICABLE', 'SUCCESS', 'TOOL_SAFETY'), task('f', 'PASS', 'SUCCESS', 'NEW_TYPE')]
const groups = failureGroups(tasks)
assert.deepEqual(groups.map(group => group.members.map(item => item.benchmarkTaskId)), [['a'], ['b'], ['c', 'd']])
assert.equal(new Set(groups.flatMap(group => group.members)).size, 4)
assert.equal(groups[1].members[0].status, 'TIMEOUT')
const rows = categoryRows(tasks, tasks.length)
assert.equal(rows.reduce((count, row) => count + row.count, 0), tasks.length)
assert.equal(rows.find(row => row.type === 'FAILURE_DIAGNOSIS')?.counts.MISSING, 1)
assert.equal(rows.find(row => row.type === 'TOOL_SAFETY')?.counts.NOT_APPLICABLE, 1)
assert.equal(rows.find(row => row.type === 'NEW_TYPE')?.recognized, false)
assert.ok(categoryRows(tasks.slice(0, 2), tasks.length).every(row => !row.complete))
assert.deepEqual(filterTasks(tasks, '', 'FAILURE_DIAGNOSIS', 'FAIL').map(item => item.benchmarkTaskId), ['a'])
const metric = { state: 'VALUE', value: 0, rate: 0 }
assert.equal(formatMetric(metric), '0.0%')
for (const [state, label] of [['NOT_APPLICABLE','N/A'], ['UNKNOWN','UNKNOWN'], ['MISSING','MISSING'], ['ERROR','ERROR']]) assert.equal(formatMetric({...metric,state}),label)
console.log('PASS: formal failure/uncertainty groups, execution exceptions, complete category counts, missing/N/A, filters, zero and availability')

// Layout reset: each segment count must equal the source tasks, including absent outcomes.
const { categoryDistribution } = await import('./benchmarkViewModel.ts')
for (const row of rows) {
  const segments = categoryDistribution(row)
  assert.equal(segments.reduce((sum, item) => sum + item.count, 0), row.count)
  assert.ok(Math.abs(segments.reduce((sum, item) => sum + item.width, 0) - (row.count ? 100 : 0)) < 0.00001)
  for (const segment of segments) assert.equal(segment.count, tasks.filter(task => task.taskType === row.type && (task.taskSuccess?.status ?? 'MISSING') === segment.status).length)
}
assert.deepEqual(categoryDistribution(categoryRows(tasks.slice(0, 1), tasks.length)[0]), [])
const fs = await import('node:fs')
const css = fs.readFileSync(new URL('./benchmark.css', import.meta.url), 'utf8')
assert.doesNotMatch(css, /overflow(?:-y)?:\s*auto/, 'Only horizontal table overflow is permitted in the dashboard')
assert.doesNotMatch(css, /benchmark-run-browser|benchmark-outcome-donut|max-height:\s*\d/)
const overview = fs.readFileSync(new URL('./components/BenchmarkOverview.tsx', import.meta.url), 'utf8')
assert.doesNotMatch(overview, /<circle|benchmark-category-table/)
assert.match(overview, /detail\.taskSuccess\.rate/)
assert.match(overview, /categoryDistribution\(row\)/)
const runsSource = fs.readFileSync(new URL('./components/BenchmarkRuns.tsx', import.meta.url), 'utf8')
assert.match(runsSource, /runs\.slice\(0, 6\)/)
assert.match(runsSource, /onSelect\(run\.evaluationRunId\)/)
console.log('PASS: category segments exactly match artifacts; no donut, permanent run sidebar or vertical card scroll; recent runs limited to six')
