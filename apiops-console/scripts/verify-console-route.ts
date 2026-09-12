import assert from 'node:assert/strict'
import { consoleRouteUrl, consoleViews, parseConsoleRoute } from '../src/app/consoleRoute.ts'

const href = 'http://localhost:5173/?unrelated=keep'
const route = consoleRouteUrl(href, 'diagnosis-studio', 123, '41')
assert.equal(parseConsoleRoute(route.search).activeItem, 'Diagnosis Studio')
assert.equal(parseConsoleRoute(route.search).runId, 123)
assert.equal(route.searchParams.get('projectId'), '41')
assert.equal(route.searchParams.get('unrelated'), 'keep')
for (const id of ['', '0', '-1', '1.2', '1e2', '9007199254740992', 'abc']) {
  assert.equal(parseConsoleRoute('?view=diagnosis-studio&runId=' + id).runId, null)
}
assert.equal(parseConsoleRoute('?view=runs&runId=12').runId, 12)
for (const [view, item] of Object.entries(consoleViews)) {
  const url = consoleRouteUrl(href, view as keyof typeof consoleViews, 123, '41', {
    agentRunId: 'agent_run:1', traceId: 'trace:with / symbols', apiId: 'api-one', apiDocId: 'doc-2',
  })
  const restored = parseConsoleRoute(url.search)
  assert.equal(restored.activeItem, item)
  assert.equal(restored.projectId, '41')
  assert.equal(restored.agentRunId, view === 'diagnosis' ? 'agent_run:1' : null)
  assert.equal(restored.traceId, view === 'traces' ? 'trace:with / symbols' : null)
  assert.equal(restored.apiId, view === 'api-studio' ? 'api-one' : null)
  assert.equal(restored.runId, ['runs', 'diagnosis-studio'].includes(view) ? 123 : null)
  const switched = consoleRouteUrl(url.href, 'runs', null, '42')
  for (const key of ['runId', 'agentRunId', 'traceId', 'apiId', 'apiDocId']) assert.equal(switched.searchParams.has(key), false)
}
assert.equal(parseConsoleRoute('?view=__proto__').activeItem, 'Overview')
const cleared = consoleRouteUrl(route.href, null, null, null)
assert.equal(cleared.searchParams.has('runId'), false)
assert.equal(cleared.searchParams.has('projectId'), false)
assert.equal(cleared.searchParams.has('view'), false)
console.log('Console route restoration, invalid IDs and stale-route clearing: passed')
