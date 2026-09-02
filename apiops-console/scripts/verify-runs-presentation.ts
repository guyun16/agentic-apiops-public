import assert from 'node:assert/strict'
import { buildExecutionStepDisplayGroups } from '../src/shared/presentation/executionStepProjection.ts'
import type { TestReportAssertion, TestReportStep } from '../src/features/runs/types.ts'

const baseAssertion: TestReportAssertion = {
  type: 'STATUS_CODE_EQUALS',
  passed: true,
  expected: 200,
  actual: 200,
  message: null,
}

function makeStep(stepId: string, overrides: Partial<TestReportStep> = {}): TestReportStep {
  return {
    stepId,
    status: 'SUCCESS',
    failureType: 'NONE',
    responseStatusCode: 200,
    durationMs: 2_000,
    assertionResults: [{ ...baseAssertion }],
    ...overrides,
  }
}

function itemShape(items: ReturnType<typeof buildExecutionStepDisplayGroups>) {
  return items.map((item) => item.kind === 'single' ? 'single' : `repeated:${item.count}`)
}

const fiveEquivalentGroups = buildExecutionStepDisplayGroups(Array.from({ length: 5 }, (_, index) => makeStep(`threshold-step-${index + 1}`)))
assert.deepEqual(itemShape(fiveEquivalentGroups), ['repeated:5'])

const fourEquivalentGroups = buildExecutionStepDisplayGroups(Array.from({ length: 4 }, (_, index) => makeStep(`four-step-${index + 1}`)))
assert.deepEqual(itemShape(fourEquivalentGroups), ['repeated:4'])

const threeEquivalentGroups = buildExecutionStepDisplayGroups(Array.from({ length: 3 }, (_, index) => makeStep(`three-step-${index + 1}`)))
assert.deepEqual(itemShape(threeEquivalentGroups), ['repeated:3'])

const thirtySteps = Array.from({ length: 30 }, (_, index) => makeStep(`step-${index + 1}`, { durationMs: 2_000 + index }))
const thirtyGroups = buildExecutionStepDisplayGroups(thirtySteps)
assert.equal(thirtyGroups.length, 1)
assert.equal(thirtyGroups[0].kind, 'repeated')
if (thirtyGroups[0].kind === 'repeated') {
  assert.equal(thirtyGroups[0].count, 30)
  assert.equal(thirtyGroups[0].totalDurationMs, 60_435)
  assert.equal(thirtyGroups[0].averageDurationMs, 2_014.5)
  assert.strictEqual(thirtyGroups[0].rawSteps[0], thirtySteps[0])
  assert.strictEqual(thirtyGroups[0].rawSteps[29], thirtySteps[29])
}

const singleGroups = buildExecutionStepDisplayGroups([makeStep('step-1')])
assert.deepEqual(itemShape(singleGroups), ['single'])

const adjacentDifferentGroups = buildExecutionStepDisplayGroups([
  makeStep('step-a'),
  makeStep('step-b', { responseStatusCode: 201 }),
])
assert.deepEqual(itemShape(adjacentDifferentGroups), ['single', 'single'])

const separatedGroups = buildExecutionStepDisplayGroups([
  ...Array.from({ length: 5 }, (_, index) => makeStep(`step-a${index + 1}`)),
  makeStep('step-b', { responseStatusCode: 201 }),
  ...Array.from({ length: 5 }, (_, index) => makeStep(`step-a${index + 6}`)),
])
assert.deepEqual(itemShape(separatedGroups), ['repeated:5', 'single', 'repeated:5'])

const identityOnlyDifferences = buildExecutionStepDisplayGroups(Array.from({ length: 5 }, (_, index) => makeStep(`identity-step-${index + 1}`, { durationMs: 1_001 + index })))
assert.deepEqual(itemShape(identityOnlyDifferences), ['repeated:5'])

const assertionDifferences = buildExecutionStepDisplayGroups([
  makeStep('step-1'),
  makeStep('step-2', { assertionResults: [{ ...baseAssertion, expected: 201 }] }),
])
assert.deepEqual(itemShape(assertionDifferences), ['single', 'single'])

const reorderedAssertionObjects = buildExecutionStepDisplayGroups(Array.from({ length: 5 }, (_, index) => makeStep(`canonical-step-${index + 1}`, {
  assertionResults: [{ ...baseAssertion, expected: index % 2 ? { right: 2, left: 1 } : { left: 1, right: 2 } }],
})))
assert.deepEqual(itemShape(reorderedAssertionObjects), ['repeated:5'])

for (const [field, overrides] of [
  ['status', { status: 'ASSERTION_FAILED' as const }],
  ['failureType', { failureType: 'TIMEOUT' as const }],
  ['responseStatusCode', { responseStatusCode: 500 }],
] as const) {
  const groups = buildExecutionStepDisplayGroups([makeStep('step-1'), makeStep('step-2', overrides)])
  assert.deepEqual(itemShape(groups), ['single', 'single'], `${field} must prevent aggregation`)
}

assert.deepEqual(buildExecutionStepDisplayGroups([]), [])
console.log('Runs presentation aggregation: passed')
