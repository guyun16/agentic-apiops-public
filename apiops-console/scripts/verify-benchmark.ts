import assert from 'node:assert/strict'
import fs from 'node:fs'
import { categoryRows, configurationSummary, comparisonView, filterTasks, formatMetric, isCurrentResult, outcome, snapshotForEvaluationRun } from '../src/features/benchmark/benchmarkViewModel.ts'
import type { BenchmarkMetric, BenchmarkRunDetail, BenchmarkTask } from '../src/features/benchmark/types.ts'
import type { FinalResultReport } from '../src/features/benchmark/finalResultAdapter.ts'

const metric: BenchmarkMetric = { metric: 'valid_json', state: 'VALUE', value: 0, mean: 0, rate: 0, unit: null, reason: null, totalCount: 6, applicableCount: 5, valueCount: 3, notApplicableCount: 1, unknownCount: 1, errorCount: 1 }
const config = { value: 'fixture model v1', availability: 'AVAILABLE', source: 'test fixture', reason: null }
const run = { evaluationRunId: 'evaluation_run:mock-a-long-identity-for-layout-verification', datasetId: 'APIOps fixture dataset', datasetVersion: 'fixture-v1', datasetSplit: 'all', taskSchemaVersion: '1', status: 'COMPLETED', selectedTaskCount: 6, executedTaskCount: 6, evaluatedTaskCount: 6, completedTaskCount: 5, failedTaskCount: 1, startedAt: '2026-09-05T01:00:00Z', completedAt: '2026-09-05T01:01:00Z', model: config, prompt: [{ ...config, value: 'fixture prompt v1' }], evaluator: { ...config, value: 'fixture evaluator v1' }, benchmarkConfigVersion: 'fixture-v1', dataSource: 'ARTIFACT', aggregateMetrics: [metric, { ...metric, metric: 'diagnosis_accuracy', value: 0.5, rate: 0.5 }, { ...metric, metric: 'tool_precision', state: 'NOT_APPLICABLE', value: null, rate: null }, { ...metric, metric: 'exact_match', state: 'UNKNOWN', value: null, rate: null }], taskSuccess: { status: null, rate: 0.5, passCount: 2, failCount: 2, unknownCount: 1, notApplicableCount: 1 }, artifactReferences: { run: 'results/mock-a/run.json', baselineRun: null, baselineConfig: null, reproducibility: 'results/mock-a/reproducibility.json', evaluationCsv: null, baselineReport: null, failureInventory: null, collateralDamage: null, taskResults: ['results/mock-a/task.json'] } } as BenchmarkRunDetail
const tasks = ['TESTCASE_GENERATION', 'FAILURE_DIAGNOSIS', 'TOOL_SAFETY', 'RAG_EVIDENCE_RETRIEVAL', 'E2E_APIOPS', 'FUTURE_TYPE'].map((taskType, i) => ({ evaluationRunId: run.evaluationRunId, benchmarkTaskId: 'fixture-task-' + i, caseId: 'fixture-case-' + i, taskType, status: i === 4 ? 'TIMEOUT' : 'SUCCESS', executionMode: 'DETERMINISTIC_FIXTURE', failureStage: null, failureCategory: null, failureCode: null, failureReason: i === 1 ? 'Saved fixture failure reason. '.repeat(18) : null, evaluationId: 'evaluation:fixture-' + i, agentRunId: 'agent_run:fixture-' + i, traceId: 'trace:fixture-' + i, runId: null, reportId: null, durationMs: i === 0 ? 0 : 20, modelLatencyMs: null, promptTokens: null, completionTokens: null, totalTokens: null, taskSuccess: { status: ['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE', 'FAIL', 'PASS'][i], passCount: 0, failCount: 0, unknownCount: 0, notApplicableCount: 0, conditions: [{ name: 'saved condition', metric: 'valid_json', metricStatus: 'VALUE', status: i === 1 ? 'FAIL' : 'PASS', required: true, reason: 'Fixture condition only; no evaluation is executed.' }] }, metrics: [{ metric: 'diagnosis_accuracy', status: i === 1 ? 'VALUE' : 'NOT_APPLICABLE', value: i === 1 ? 0 : null, unit: null, reason: null, details: ['fixture evidence reference'] }], artifactRef: 'results/mock-a/task-' + i + '.json' })) as BenchmarkTask[]

assert.equal(configurationSummary({ ...config, availability: 'AVAILABLE', value: { provider: 'Qwen', model: 'model-v1' } }), 'Qwen · model-v1')
assert.equal(formatMetric(metric), '0.0%')
assert.equal(formatMetric(undefined), 'MISSING')
for (const [state, text] of [['NOT_APPLICABLE', 'N/A'], ['UNKNOWN', 'UNKNOWN'], ['ERROR', 'ERROR'], ['MISSING', 'MISSING']] as const) assert.equal(formatMetric({ ...metric, state }), text)
assert.equal(formatMetric({ ...metric, rate: null, value: 0, unit: 'ms' }), '0 ms')
assert.equal(run.status, 'COMPLETED')
assert.equal(outcome(tasks[1]), 'FAIL')
assert.equal(outcome({ ...tasks[0], taskSuccess: null }), 'MISSING')
const original = JSON.stringify(run)
assert.equal(filterTasks(tasks, 'fixture-task-1', 'ALL', 'FAIL').length, 1)
assert.equal(filterTasks(tasks, 'absent', 'ALL', 'ALL').length, 0)
assert.equal(filterTasks(tasks, '', 'TOOL_SAFETY', 'UNKNOWN').length, 1)
assert.equal(JSON.stringify(run), original)
assert.equal(categoryRows(tasks, 6).length, 6)
assert.equal(categoryRows(tasks, 6).find(row => row.type === 'FUTURE_TYPE')?.recognized, false)
assert.equal(categoryRows(tasks.slice(0, 2), 6).every(row => !row.complete), true)
assert.equal(comparisonView(run).available, false)
assert.equal(comparisonView({ ...run, artifactReferences: { ...run.artifactReferences, baselineRun: 'incompatible/baseline.json' } }).available, false)
assert.equal(comparisonView({ ...run, aggregateMetrics: [] }).metrics.length, 0)
assert.equal(comparisonView({ ...run, aggregateMetrics: [{ ...metric, metric: 'cost', rate: null, value: 0.1, unit: 'USD' }] }).metrics.length, 0)

// Simulate out-of-order completion, including a transport that ignores abort.
const oldRequest = new AbortController()
const newRequest = new AbortController()
const secondRun = { ...run, evaluationRunId: 'evaluation_run:mock-b', datasetVersion: 'fixture-v2', aggregateMetrics: [], taskSuccess: { ...run.taskSuccess, rate: null } }
let committed = ''
let releaseOld: () => void = () => {}
const oldResponse = new Promise<void>(resolve => { releaseOld = resolve }).then(() => { if (isCurrentResult(oldRequest.signal, run.evaluationRunId, run, tasks)) committed = run.evaluationRunId })
oldRequest.abort()
if (isCurrentResult(newRequest.signal, secondRun.evaluationRunId, secondRun, [])) committed = secondRun.evaluationRunId
releaseOld()
await oldResponse
assert.equal(committed, secondRun.evaluationRunId)
assert.equal(isCurrentResult(newRequest.signal, secondRun.evaluationRunId, run, tasks), false)

const currentSnapshot = JSON.parse(fs.readFileSync('src/features/benchmark/final-result.snapshot.json', 'utf8')) as FinalResultReport
assert.equal(snapshotForEvaluationRun(currentSnapshot, 'evaluation_run:stage21-real-model-full-105-20260826T171200Z'), null, 'Baseline must not use Current snapshot')
assert.equal(snapshotForEvaluationRun(currentSnapshot, 'evaluation_run:stage21-real-model-full-105-20260831T024951Z'), null, 'RAG-Enhanced must not use Current snapshot')
assert.equal(snapshotForEvaluationRun(currentSnapshot, currentSnapshot.sourceEvaluationRunId), currentSnapshot, 'Exact Current identity may use snapshot')
assert.equal(snapshotForEvaluationRun({ ...currentSnapshot, evaluationRunId: 'evaluation_run:mismatch' }, currentSnapshot.sourceEvaluationRunId), null, 'Mismatched snapshot identity must fall back')
assert.equal(snapshotForEvaluationRun({ ...currentSnapshot, detail: { ...currentSnapshot.detail, evaluationRunId: 'evaluation_run:mismatch' } }, currentSnapshot.sourceEvaluationRunId), null)
assert.equal(snapshotForEvaluationRun({ ...currentSnapshot, tasks: [{ ...currentSnapshot.tasks[0], evaluationRunId: 'evaluation_run:mismatch' }] }, currentSnapshot.sourceEvaluationRunId), null)
const manifest = JSON.parse(fs.readFileSync('../artifacts/benchmark/portfolio-manifest.json', 'utf8'))
const authority = JSON.parse(fs.readFileSync('../docs/stage21-benchmark-authority.json', 'utf8'))
assert.equal(manifest.publications.length, authority.full105RunCount, 'History count must match the published complete runs')
assert.equal(authority.history.length, authority.full105RunCount)
assert.equal(manifest.publications.filter((entry: { evaluationRunId: string }) => entry.evaluationRunId === currentSnapshot.evaluationRunId).length, 1, 'Current snapshot needs exactly one explicit publication')
const overview = fs.readFileSync('src/features/benchmark/components/FinalBenchmarkOverview.tsx', 'utf8')
assert.ok(overview.includes('benchmarkAuthority.full105RunCount'), 'History card must use the verified count instead of a stale hardcoded count')

const page = fs.readFileSync('src/features/benchmark/BenchmarkPage.tsx', 'utf8')
const summarySource = fs.readFileSync('src/features/benchmark/components/BenchmarkSummary.tsx', 'utf8')
assert.ok(page.includes("runsState === 'ready' && runs.length > 0"))
assert.ok(page.includes("runsState === 'error'"))
assert.ok(page.includes('key={detail.evaluationRunId}'))
assert.ok(page.includes('controller.abort()'))
assert.ok(!page.includes('Promise.all(['), 'Slow task retrieval must not gate saved summary display')
assert.ok(page.includes('setRuns(nextRuns)'), 'Only the API publication list controls selectable runs')
assert.ok(!page.includes('showing the verified v5 artifact snapshot'), 'API errors must not claim a snapshot fallback')
assert.ok(summarySource.includes('{item.displayName}'), 'The selector must use publication display names')
assert.ok(summarySource.includes("ui('Technical identity')"), 'Raw run identity belongs in technical details')
for (const forbidden of ['Run Benchmark', 'Stop Benchmark', 'Edit Dataset', 'Edit Ground Truth', 'Tune Prompt', 'Change Evaluator']) {
  assert.ok(!page.includes(forbidden), `Read-only Benchmark page must not expose ${forbidden}`)
}
const tabSource = fs.readFileSync('src/features/benchmark/components/BenchmarkTabContent.tsx', 'utf8')
assert.ok(tabSource.includes("(tab === 'Tasks' || tab === 'Failures') && tasksState !== 'ready'"), 'Unavailable tasks must not be presented as zero failures')
for (const entry of fs.readdirSync('src/features/benchmark', { recursive: true })) {
  if (!String(entry).endsWith('.tsx')) continue
  const source = fs.readFileSync('src/features/benchmark/' + entry, 'utf8')
  assert.doesNotMatch(source, /method:\s*['"](?:POST|PUT|PATCH|DELETE)['"]|streamSse\(/)
}
const css = fs.readFileSync('src/features/benchmark/benchmark.css', 'utf8')
for (const line of css.split('\n')) if (line.includes('{') && !line.trim().startsWith('@')) assert.ok(line.trim().startsWith('.benchmark-redesign'), line)
console.log('PASS: values, absence, outcomes, filtering, complete category counts, no comparison contract, identity and abort race, read-only API and style scope')

// Optional, explicit browser-only fixture harness. No files/artifacts are modified.
// The production AppShell and authentication remain unchanged. A 224px gutter
// reserves the existing sidebar width for content-layout testing.
if (process.argv.includes('--serve')) {
  const { createServer, transformWithEsbuild } = await import('vite')
  let browserCode = `
    import React from 'react'; import { createRoot } from 'react-dom/client';
    import '/src/styles.css';
    import { ConsoleLanguageProvider, useConsoleLanguage } from '/src/app/ConsoleLanguage.tsx';
    import { BenchmarkPage } from '/src/features/benchmark/BenchmarkPage.tsx';
    let scenario = 'normal'; let listCalls = 0; let reads = 0;
    const runs = ${JSON.stringify([run, secondRun])}; const tasks = ${JSON.stringify(tasks)};
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init = {}) => {
      const url = String(input);
      if (!url.includes('/api/v1/benchmark/results')) return originalFetch(input, init);
      reads++; document.getElementById('request-count').textContent = 'Mock GET requests: ' + reads;
      if (init.method && init.method !== 'GET') throw new Error('Execution API forbidden');
      const tail = decodeURIComponent(url.split('/api/v1/benchmark/results')[1]);
      const captured = scenario;
      if (!tail) { listCalls++; if (captured === 'refresh-error' && listCalls > 1) return new Response('{}', {status: 503}); if (captured === 'empty') return Response.json([]); return Response.json(runs); }
      const selected = tail.includes(runs[1].evaluationRunId) ? runs[1] : runs[0];
      await new Promise(resolve => setTimeout(resolve, selected === runs[1] ? 800 : 100));
      if (captured === 'artifact-error') return new Response('{}', {status: 404});
      return Response.json(tail.endsWith('/tasks') ? tasks.map(task => ({...task, evaluationRunId: selected.evaluationRunId})) : selected);
    };
    document.documentElement.dataset.theme = 'light';
    function Harness() { const {setLanguage} = useConsoleLanguage(); return <><header style={{padding:12, fontSize:12}}>MOCK — Benchmark content verification only; sidebar width reserved. <select aria-label="Fixture scenario" onChange={e => {scenario=e.target.value; listCalls=1}}>{['normal','refresh-error','empty','artifact-error'].map(s=><option key={s}>{s}</option>)}</select> <select aria-label="Fixture theme" onChange={e => document.documentElement.dataset.theme=e.target.value}><option>light</option><option>dark</option></select> <button onClick={()=>setLanguage('zh-CN')}>中文</button> <button onClick={()=>setLanguage('en')}>English</button> <span id="request-count">Mock GET requests: 0</span></header><main style={{marginLeft:224,padding:24}}><BenchmarkPage /></main></> }
    createRoot(document.getElementById('root')).render(<ConsoleLanguageProvider><Harness /></ConsoleLanguageProvider>);
  `
  if (process.argv.includes('--shell')) {
    browserCode = browserCode.replace("import React from 'react';", "import App from '/src/app/App.tsx'; import React from 'react';")
    browserCode = browserCode.replace("if (!url.includes('/api/v1/benchmark/results')) return originalFetch(input, init);", `
      if (!url.includes('/api/v1/benchmark/results')) {
        if (url.endsWith('/api/v1/auth/me')) return Response.json({success:true,code:'OK',message:'fixture',data:{userId:1,username:'MOCK viewer'}});
        if (url.endsWith('/api/v1/projects')) return Response.json({success:true,code:'OK',message:'fixture',data:[{projectId:1,projectName:'MOCK Benchmark verification',projectRole:'VIEWER'}]});
        if (url.includes('/api') || url.includes('/actuator')) return new Response('{}',{status:503});
        return originalFetch(input,init);
      }
    `)
    browserCode = browserCode.replace("reads++; document.getElementById('request-count').textContent = 'Mock GET requests: ' + reads;", "reads++;")
    browserCode = browserCode.replace("createRoot(document.getElementById('root')).render(<ConsoleLanguageProvider><Harness /></ConsoleLanguageProvider>);", `
      // In-memory fixture session for this isolated test page only. No credential
      // is persisted; production authentication source is never modified.
      const readStorage = Storage.prototype.getItem;
      Storage.prototype.getItem = function(key) { return key === 'apiops-console-access-token' ? 'mock-session-for-browser-verification-only' : readStorage.call(this,key); };
      createRoot(document.getElementById('root')).render(<App />);
    `)
  }
  const server = await createServer({ server: { host: '127.0.0.1', port: 5173, strictPort: true, hmr: false }, plugins: [{ name: 'benchmark-verification-only', resolveId(id) { if (id === 'virtual:benchmark-harness') return '\0benchmark-harness' }, async load(id) { if (id === '\0benchmark-harness') return (await transformWithEsbuild(browserCode, 'benchmark-harness.tsx', { loader: 'tsx', jsx: 'automatic' })).code }, configureServer(vite) { vite.middlewares.use('/__benchmark', async (_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(await vite.transformIndexHtml('/__benchmark', '<html><head><title>MOCK Benchmark verification</title></head><body><div id="root"></div><script type="module" src="/@id/virtual:benchmark-harness"></script></body></html>')) }) } }] })
  await server.listen()
  console.log('MOCK harness: http://127.0.0.1:5173/__benchmark ; unchanged Console: http://127.0.0.1:5173/')
}
