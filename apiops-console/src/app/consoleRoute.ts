export const consoleViews = {
  overview: 'Overview',
  'api-studio': 'API Studio',
  runs: 'Runs',
  'diagnosis-studio': 'Diagnosis Studio',
  diagnosis: 'Diagnosis',
  traces: 'Traces',
  evaluation: 'Evaluation',
  benchmark: 'Benchmark',
  settings: 'Settings',
} as const

export type ConsoleView = keyof typeof consoleViews
export type RouteDetails = { agentRunId?: string | null; traceId?: string | null; apiId?: string | null; apiDocId?: string | null }

export function consoleViewForItem(item: string): ConsoleView {
  return (Object.keys(consoleViews) as ConsoleView[]).find((key) => consoleViews[key] === item) ?? 'overview'
}

export function parseConsoleRoute(search: string) {
  const params = new URLSearchParams(search)
  const requested = params.get('view') ?? ''
  const view: ConsoleView = Object.prototype.hasOwnProperty.call(consoleViews, requested) ? requested as ConsoleView : 'overview'
  const rawRunId = params.get('runId') ?? ''
  const id = /^\d+$/.test(rawRunId) ? Number(rawRunId) : NaN
  const runId = (view === 'runs' || view === 'diagnosis-studio') && Number.isSafeInteger(id) && id > 0 ? id : null
  return {
    view, activeItem: consoleViews[view], runId, projectId: params.get('projectId') || null,
    agentRunId: view === 'diagnosis' ? params.get('agentRunId') || null : null,
    traceId: view === 'traces' ? params.get('traceId') || null : null,
    apiId: view === 'api-studio' ? params.get('apiId') || null : null,
    apiDocId: view === 'api-studio' ? params.get('apiDocId') || null : null,
  }
}

export function consoleRouteUrl(href: string, view: ConsoleView | null, runId: number | null, projectId: string | null, details: RouteDetails = {}) {
  const url = new URL(href)
  for (const key of ['view', 'runId', 'projectId', 'agentRunId', 'traceId', 'apiId', 'apiDocId']) url.searchParams.delete(key)
  if (view) url.searchParams.set('view', view)
  if ((view === 'runs' || view === 'diagnosis-studio') && runId !== null && Number.isSafeInteger(runId) && runId > 0) url.searchParams.set('runId', String(runId))
  if (view && projectId) url.searchParams.set('projectId', projectId)
  if (view === 'diagnosis' && details.agentRunId) url.searchParams.set('agentRunId', details.agentRunId)
  if (view === 'traces' && details.traceId) url.searchParams.set('traceId', details.traceId)
  if (view === 'api-studio') {
    if (details.apiId) url.searchParams.set('apiId', details.apiId)
    if (details.apiDocId) url.searchParams.set('apiDocId', details.apiDocId)
  }
  return url
}
