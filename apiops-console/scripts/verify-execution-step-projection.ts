import assert from 'node:assert/strict'
import {
  buildExecutionAssertionDisplayGroups,
  buildExecutionStepDisplayGroups,
  buildExecutionStepDisplayProjection,
} from '../src/shared/presentation/executionStepProjection.ts'
import type { TestReportAssertion, TestReportStep } from '../src/features/runs/types.ts'

const baseAssertion: TestReportAssertion = {
  type: 'STATUS_CODE',
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

function assertSingle(items: ReturnType<typeof buildExecutionStepDisplayGroups>) {
  assert.deepEqual(itemShape(items), ['single'])
  assert.equal(items[0].count, 1)
}

// Case 1: one execution remains one display item.
const single = buildExecutionStepDisplayGroups([makeStep('step-1')])
assertSingle(single)

// Case 2: two equivalent executions aggregate even though stepId differs.
const twoEquivalent = [makeStep('step-1'), makeStep('step-2')]
const twoEquivalentGroups = buildExecutionStepDisplayGroups(twoEquivalent)
assert.deepEqual(itemShape(twoEquivalentGroups), ['repeated:2'])
assert.strictEqual(twoEquivalentGroups[0].rawSteps[0], twoEquivalent[0])
assert.strictEqual(twoEquivalentGroups[0].rawSteps[1], twoEquivalent[1])

// Case 3: thirty equivalent executions aggregate into one display item.
const thirtySteps = Array.from({ length: 30 }, (_, index) => makeStep(`step-${index + 1}`))
const thirtyGroups = buildExecutionStepDisplayGroups(thirtySteps)
assert.deepEqual(itemShape(thirtyGroups), ['repeated:30'])
assert.equal(thirtyGroups[0].rawSteps.length, 30)

// Case 4: duration is volatile and does not prevent grouping.
const durationGroups = buildExecutionStepDisplayGroups([
  makeStep('duration-1', { durationMs: 1_001 }),
  makeStep('duration-2', { durationMs: 1_002 }),
])
assert.deepEqual(itemShape(durationGroups), ['repeated:2'])
assert.equal(durationGroups[0].totalDurationMs, 2_003)
assert.equal(durationGroups[0].averageDurationMs, 1_001.5)

// Case 5: grouping is consecutive-only: A A B A A.
const consecutiveGroups = buildExecutionStepDisplayGroups([
  makeStep('a-1'),
  makeStep('a-2'),
  makeStep('b', { responseStatusCode: 201 }),
  makeStep('a-3'),
  makeStep('a-4'),
])
assert.deepEqual(itemShape(consecutiveGroups), ['repeated:2', 'single', 'repeated:2'])

// Cases 6-8: status, failure type, and HTTP status are business/execution facts.
for (const [field, first, second] of [
  ['status', makeStep('status-1'), makeStep('status-2', { status: 'ASSERTION_FAILED' })],
  ['failureType', makeStep('failure-1'), makeStep('failure-2', { failureType: 'TIMEOUT' })],
  ['HTTP status', makeStep('http-1'), makeStep('http-2', { responseStatusCode: 500 })],
] as const) {
  const groups = buildExecutionStepDisplayGroups([first, second])
  assert.deepEqual(itemShape(groups), ['single', 'single'], `${field} difference must prevent aggregation`)
}

// Case 9: assertion expected/actual differences are part of step equivalence.
const expectedDifference = buildExecutionStepDisplayGroups([
  makeStep('expected-1'),
  makeStep('expected-2', { assertionResults: [{ ...baseAssertion, expected: 201 }] }),
])
assert.deepEqual(itemShape(expectedDifference), ['single', 'single'])

const actualDifference = buildExecutionStepDisplayGroups([
  makeStep('actual-1'),
  makeStep('actual-2', { assertionResults: [{ ...baseAssertion, actual: 201, passed: false }] }),
])
assert.deepEqual(itemShape(actualDifference), ['single', 'single'])

// Case 10: assertion passed differences cannot be merged.
const passedDifference = buildExecutionStepDisplayGroups([
  makeStep('passed-1'),
  makeStep('passed-2', { assertionResults: [{ ...baseAssertion, passed: false, actual: 500 }] }),
])
assert.deepEqual(itemShape(passedDifference), ['single', 'single'])

// The current Java StepReport schema has no request identity fields. The
// projection therefore has no request fixture to invent; any future
// non-volatile fields are included by the schema-shaped signature.

// Case 12: assertions derive from the repeated Step group and retain count.
const assertionGroups = buildExecutionAssertionDisplayGroups(thirtyGroups[0])
assert.equal(assertionGroups.length, 1)
assert.equal(assertionGroups[0].count, 30)
assert.equal(assertionGroups[0].rawAssertions.length, 30)
assert.equal(assertionGroups[0].representativeAssertion.type, 'STATUS_CODE')

// Case 13: one differing assertion splits the Step projection, so a false
// assertion can never be rendered as passed ×30.
const oneAssertionDifference = buildExecutionStepDisplayGroups([
  ...Array.from({ length: 29 }, (_, index) => makeStep(`same-${index + 1}`)),
  makeStep('different', { assertionResults: [{ ...baseAssertion, actual: 500, passed: false }] }),
])
assert.deepEqual(itemShape(oneAssertionDifference), ['repeated:29', 'single'])
const firstAssertionGroup = buildExecutionAssertionDisplayGroups(oneAssertionDifference[0])
const finalAssertionGroup = buildExecutionAssertionDisplayGroups(oneAssertionDifference[1])
assert.equal(firstAssertionGroup[0].count, 29)
assert.equal(finalAssertionGroup[0].count, 1)
assert.equal(finalAssertionGroup[0].representativeAssertion.passed, false)

// Projection is case-local; the same facts in separate cases never cross-merge.
const projection = buildExecutionStepDisplayProjection([
  { caseId: 'case-a', steps: twoEquivalent },
  { caseId: 'case-b', steps: [makeStep('case-b-step')] },
])
assert.deepEqual(projection.cases.map((item) => item.items[0].kind), ['repeated', 'single'])

console.log('Shared execution step projection: passed')
