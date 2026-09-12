import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { clearStudioDrafts, readStudioDraft, readStudioSelection, studioDraftKey, writeStudioDraft, writeStudioSelection } from '../src/features/api-studio/studioDrafts.ts'
import { mergeRunPages, nextRunCursor } from '../src/features/runs/runPaging.ts'
import type { RunSummary } from '../src/features/runs/types.ts'

const storage = new Map<string, string>()
globalThis.window = { sessionStorage: {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
  key: (index: number) => [...storage.keys()][index],
  get length() { return storage.size },
} } as unknown as Window & typeof globalThis
const selection = { apiDocId: 'doc', apiId: 'api', strategy: 'HAPPY_PATH' as const, runtime: 'JAVA_AGENT' as const }
const key = studioDraftKey('user1', '41', selection)
assert.equal(writeStudioDraft(key, '{unfinished'), true)
assert.equal(readStudioDraft(key), '{unfinished')
assert.equal(storage.get(key), '{unfinished')
for (const other of [studioDraftKey('user2', '41', selection), studioDraftKey('user1', '42', selection),
  studioDraftKey('user1', '41', { ...selection, apiId: 'other' }),
  studioDraftKey('user1', '41', { ...selection, strategy: 'BOUNDARY' })]) assert.equal(readStudioDraft(other), null)
writeStudioSelection('user1', '41', selection)
assert.deepEqual(readStudioSelection('user1', '41'), selection)
clearStudioDrafts()
assert.equal(readStudioDraft(key), null)
assert.equal(storage.size, 0)

const page = Array.from({ length: 100 }, (_, index) => ({ runId: 200 - index, createdAt: null, status: 'PENDING' })) as RunSummary[]
assert.equal(nextRunCursor(page), 101)
assert.equal(nextRunCursor(page.slice(1)), null)
const older = [{ runId: 100, createdAt: '2026-09-09', status: 'SUCCESS' }] as RunSummary[]
const loaded = mergeRunPages(page, older)
const refreshed = mergeRunPages(loaded, [{ ...page[0], status: 'SUCCESS' }, older[0]])
assert.equal(refreshed.length, 101)
assert.equal(refreshed[0].status, 'SUCCESS')
assert.equal(refreshed.at(-1)?.runId, 100)

// Execute the actual submission handler with delayed API responses. No browser or model needed.
const source = readFileSync(new URL('../src/features/api-studio/ApiStudioPage.tsx', import.meta.url), 'utf8')
const begin = source.indexOf('  const runTest = async () => {')
const end = source.indexOf('\n  return (', begin)
assert.ok(begin >= 0 && end > begin)
const handler = ts.transpile(source.slice(begin, end) + '\nglobalThis.runTest = runTest', { target: ts.ScriptTarget.ES2022 })
for (const stage of ['normal', 'submit', 'detail', 'error', 'unmount']) {
  let release!: (value: unknown) => void
  let reject!: (reason: unknown) => void
  const delayed = new Promise((resolve, fail) => { release = resolve; reject = fail })
  const writes: string[] = []
  const scope = {
    projectId: '41', draftKey: 'old', currentDraftKey: { current: 'old' }, submissionController: { current: null as AbortController | null },
    generationStatus: 'ACCEPTED', validatedTestCase: {}, generatedDsl: '{}', validatedDsl: '{}', isSubmitting: false,
    AbortController, encodeURIComponent,
    runnerRequestForEditor: () => ({ testCases: [{}] }),
    setIsSubmitting: () => {}, setRunnerSubmission: (value: unknown) => { if (value) writes.push('submission') },
    setRunnerError: (value: unknown) => { if (value) writes.push('error') },
    apiFetch: () => stage === 'detail' ? Promise.resolve({ runId: 701 }) : delayed,
    singleRunnerSubmission: (value: unknown) => value,
    fetchExactRun: () => stage === 'detail' ? delayed : Promise.resolve({ runId: 701 }),
    recordRun: () => writes.push('run'), activateContext: () => writes.push('context'),
    apiErrorFor: (error: unknown) => error, expireSession: () => writes.push('expired'), refreshProjects: () => writes.push('refresh'),
  }
  vm.createContext(scope)
  vm.runInContext(handler, scope)
  const pending = (scope as unknown as { runTest: () => Promise<void> }).runTest()
  await Promise.resolve()
  if (stage !== 'normal') { scope.currentDraftKey.current = 'new'; writes.length = 0 }
  if (stage === 'unmount') scope.submissionController.current?.abort()
  if (stage === 'error') reject(new Error('old request failed'))
  else release({ runId: 701 })
  await pending
  assert.deepEqual(writes, stage === 'normal' ? ['submission', 'run', 'context'] : [], stage)
}
console.log('Draft isolation, logout cleanup, historical pagination, and delayed submission races: passed')
