/**
 * Presentation-only projection for Java Runner/TestReport execution steps.
 *
 * This module deliberately knows nothing about React or a particular feature.
 * Callers provide the Java TestReport-shaped step/case values and keep the
 * returned raw values for drill-down and traceability.
 */

export type ExecutionAssertionLike = {
  type: string
  passed: boolean
  expected: unknown
  actual: unknown
  message: string | null
}

export type ExecutionStepLike = {
  stepId: string
  status: string
  failureType: string
  responseStatusCode: number | null
  durationMs: number | null
  assertionResults: readonly ExecutionAssertionLike[]
}

export type ExecutionStepCaseLike<Step extends ExecutionStepLike = ExecutionStepLike> = {
  caseId: string
  steps: readonly Step[]
}

type AssertionOf<Step extends ExecutionStepLike> = Step extends {
  assertionResults: readonly (infer Assertion)[]
} ? Assertion : never

export type ExecutionStepDisplayItem<Step extends ExecutionStepLike = ExecutionStepLike> =
  | {
      kind: 'single'
      step: Step
      representativeStep: Step
      rawSteps: readonly Step[]
      count: 1
      totalDurationMs: number | null
      averageDurationMs: number | null
    }
  | {
      kind: 'repeated'
      representativeStep: Step
      rawSteps: readonly Step[]
      count: number
      totalDurationMs: number | null
      averageDurationMs: number | null
    }

export type ExecutionStepDisplayCase<
  Step extends ExecutionStepLike = ExecutionStepLike,
  Case extends ExecutionStepCaseLike<Step> = ExecutionStepCaseLike<Step>,
> = {
  caseId: string
  sourceCase: Case
  items: ExecutionStepDisplayItem<Step>[]
}

export type ExecutionStepDisplayProjection<
  Step extends ExecutionStepLike = ExecutionStepLike,
  Case extends ExecutionStepCaseLike<Step> = ExecutionStepCaseLike<Step>,
> = {
  cases: ExecutionStepDisplayCase<Step, Case>[]
}

export type ExecutionAssertionDisplayEntry<Step extends ExecutionStepLike = ExecutionStepLike> = {
  assertion: AssertionOf<Step>
  step: Step
  executionIndex: number
  assertionIndex: number
}

export type ExecutionAssertionDisplayGroup<Step extends ExecutionStepLike = ExecutionStepLike> = {
  representativeAssertion: AssertionOf<Step>
  count: number
  rawAssertions: readonly ExecutionAssertionDisplayEntry<Step>[]
}

const VOLATILE_EXECUTION_STEP_FIELDS = new Set([
  'stepId',
  'executionIndex',
  'sequenceNumber',
  'sequence',
  'durationMs',
  'startedAt',
  'finishedAt',
])

function stableSerialize(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'

  if (typeof value === 'string') return JSON.stringify(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') {
    if (Number.isNaN(value)) return 'number:NaN'
    if (value === Infinity) return 'number:Infinity'
    if (value === -Infinity) return 'number:-Infinity'
    if (Object.is(value, -0)) return 'number:-0'
    return `number:${value}`
  }
  if (typeof value === 'bigint') return `bigint:${value.toString()}`
  if (typeof value !== 'object') return `${typeof value}:${String(value)}`

  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(',')}]`
  }

  const objectValue = value as Record<string, unknown>
  return `{${Object.keys(objectValue)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableSerialize(objectValue[key])}`)
    .join(',')}}`
}

function executionStepSignature<Step extends ExecutionStepLike>(step: Step) {
  const facts = Object.fromEntries(
    Object.entries(step as unknown as Record<string, unknown>)
      .filter(([key]) => !VOLATILE_EXECUTION_STEP_FIELDS.has(key)),
  )
  return stableSerialize(facts)
}

function aggregateDurationMs<Step extends ExecutionStepLike>(steps: readonly Step[]) {
  if (steps.some((step) => typeof step.durationMs !== 'number' || !Number.isFinite(step.durationMs))) {
    return { totalDurationMs: null, averageDurationMs: null }
  }

  const totalDurationMs = steps.reduce((total, step) => total + (step.durationMs as number), 0)
  return {
    totalDurationMs,
    averageDurationMs: totalDurationMs / steps.length,
  }
}

function createDisplayItem<Step extends ExecutionStepLike>(rawSteps: readonly Step[]): ExecutionStepDisplayItem<Step> {
  const steps = rawSteps.slice()
  const representativeStep = steps[0]
  const duration = aggregateDurationMs(steps)

  if (steps.length === 1) {
    return {
      averageDurationMs: duration.averageDurationMs,
      count: 1,
      kind: 'single',
      rawSteps: steps,
      representativeStep,
      step: representativeStep,
      totalDurationMs: duration.totalDurationMs,
    }
  }

  return {
    ...duration,
    count: steps.length,
    kind: 'repeated',
    rawSteps: steps,
    representativeStep,
  }
}

/**
 * Groups only adjacent equivalent Java execution steps. A run of one remains
 * a single item; a run of two or more becomes a repeated display item.
 */
export function buildExecutionStepDisplayGroups<Step extends ExecutionStepLike>(steps: readonly Step[]) {
  const items: ExecutionStepDisplayItem<Step>[] = []
  let currentSteps: Step[] = []
  let currentSignature: string | null = null

  const flush = () => {
    if (!currentSteps.length) return
    items.push(createDisplayItem(currentSteps))
    currentSteps = []
    currentSignature = null
  }

  steps.forEach((step) => {
    const signature = executionStepSignature(step)
    if (currentSteps.length && signature !== currentSignature) flush()
    currentSteps.push(step)
    currentSignature = signature
  })
  flush()

  return items
}

/** Builds the same step projection independently for each TestReport case. */
export function buildExecutionStepDisplayProjection<Case extends ExecutionStepCaseLike>(
  cases: readonly Case[],
): ExecutionStepDisplayProjection<Case['steps'][number], Case> {
  return {
    cases: cases.map((sourceCase) => ({
      caseId: sourceCase.caseId,
      items: buildExecutionStepDisplayGroups(sourceCase.steps),
      sourceCase,
    })),
  }
}

/** Stable UI selection key; raw step ids never become a grouping key. */
export function executionStepDisplayKey<Step extends ExecutionStepLike>(
  caseId: string,
  item: ExecutionStepDisplayItem<Step>,
) {
  return `${caseId}::${item.kind}::${item.representativeStep.stepId}`
}

function groupAssertionEntries<Step extends ExecutionStepLike>(
  entries: readonly ExecutionAssertionDisplayEntry<Step>[],
) {
  const groups: ExecutionAssertionDisplayGroup<Step>[] = []
  let currentEntries: ExecutionAssertionDisplayEntry<Step>[] = []
  let currentSignature: string | null = null

  const flush = () => {
    if (!currentEntries.length) return
    groups.push({
      count: currentEntries.length,
      rawAssertions: currentEntries.slice(),
      representativeAssertion: currentEntries[0].assertion,
    })
    currentEntries = []
    currentSignature = null
  }

  entries.forEach((entry) => {
    const signature = stableSerialize(entry.assertion)
    if (currentEntries.length && signature !== currentSignature) flush()
    currentEntries.push(entry)
    currentSignature = signature
  })
  flush()

  return groups
}

/**
 * Derives assertion display groups from one step display item. Assertions are
 * compared within their assertion position, so a missing, reordered, or
 * changed assertion remains visible instead of being silently merged.
 */
export function buildExecutionAssertionDisplayGroups<Step extends ExecutionStepLike>(
  item: ExecutionStepDisplayItem<Step>,
) {
  const assertionCount = item.rawSteps.reduce(
    (maximum, step) => Math.max(maximum, step.assertionResults.length),
    0,
  )
  const groups: ExecutionAssertionDisplayGroup<Step>[] = []

  for (let assertionIndex = 0; assertionIndex < assertionCount; assertionIndex += 1) {
    const entries: ExecutionAssertionDisplayEntry<Step>[] = []
    let previousStepHadAssertion = true

    item.rawSteps.forEach((step, executionIndex) => {
      const assertion = step.assertionResults[assertionIndex] as AssertionOf<Step> | undefined
      if (!assertion) {
        previousStepHadAssertion = false
        return
      }

      if (!previousStepHadAssertion) {
        groups.push(...groupAssertionEntries(entries))
        entries.length = 0
      }
      entries.push({ assertion, assertionIndex, executionIndex, step })
      previousStepHadAssertion = true
    })

    groups.push(...groupAssertionEntries(entries))
  }

  return groups
}
