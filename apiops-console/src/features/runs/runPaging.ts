import type { RunSummary } from './types'

export const RUN_PAGE_SIZE = 100

export function nextRunCursor(page: readonly RunSummary[]) {
  return page.length === RUN_PAGE_SIZE ? Math.min(...page.map((run) => run.runId)) : null
}

export function mergeRunPages(current: readonly RunSummary[], incoming: readonly RunSummary[]) {
  const byId = new Map(current.map((run) => [run.runId, run]))
  incoming.forEach((run) => byId.set(run.runId, { ...run, createdAt: run.createdAt ?? byId.get(run.runId)?.createdAt ?? null }))
  return [...byId.values()].sort((a, b) => b.runId - a.runId)
}
