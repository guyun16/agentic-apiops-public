import type { StrategyId, TestCaseAgentRuntime } from './types'

const PREFIX = 'apiops-console-studio:'
const memory = new Map<string, string>()

export type StudioSelection = {
  apiDocId: string
  apiId: string
  strategy: StrategyId | null
  runtime: TestCaseAgentRuntime
}

export function studioDraftKey(userId: string, projectId: string, selection: StudioSelection) {
  return PREFIX + JSON.stringify([userId, projectId, selection.apiDocId, selection.apiId, selection.strategy, selection.runtime])
}

function selectionKey(userId: string, projectId: string) {
  return PREFIX + JSON.stringify([userId, projectId, 'selection'])
}

function read(key: string): string | null {
  if (memory.has(key)) return memory.get(key)!
  try { return window.sessionStorage.getItem(key) } catch { return null }
}

function write(key: string, value: string): boolean {
  memory.set(key, value)
  try { window.sessionStorage.setItem(key, value); return true } catch { return false }
}

// Drafts belong to this browser tab and never authorize execution after restoration.
export function readStudioDraft(key: string) { return read(key) }
export function writeStudioDraft(key: string, dsl: string) { return write(key, dsl) }

export function readStudioSelection(userId: string, projectId: string): StudioSelection | null {
  try {
    const value = JSON.parse(read(selectionKey(userId, projectId)) ?? 'null')
    if (!value || typeof value.apiDocId !== 'string' || typeof value.apiId !== 'string'
      || !['JAVA_AGENT', 'PYTHON_AGENTLAB'].includes(value.runtime)
      || (value.strategy !== null && !['HAPPY_PATH', 'MISSING_REQUIRED', 'BOUNDARY', 'AUTH_FAILURE', 'IDEMPOTENCY', 'BUSINESS_ERROR'].includes(value.strategy))) return null
    return value
  } catch { return null }
}

export function writeStudioSelection(userId: string, projectId: string, selection: StudioSelection) {
  write(selectionKey(userId, projectId), JSON.stringify(selection))
}

export function clearStudioDrafts() {
  memory.clear()
  try {
    for (let index = window.sessionStorage.length - 1; index >= 0; index--) {
      const key = window.sessionStorage.key(index)
      if (key?.startsWith(PREFIX)) window.sessionStorage.removeItem(key)
    }
  } catch { /* Storage may be unavailable. */ }
}
