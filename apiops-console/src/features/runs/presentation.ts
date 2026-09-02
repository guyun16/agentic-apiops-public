import type { RunSummary, TimelineStep } from './types'

// Kept as compatibility exports for existing Runs-only callers. The
// implementation lives in the shared Java Execution Step projection module.
export {
  buildExecutionAssertionDisplayGroups,
  buildExecutionStepDisplayGroups,
  buildExecutionStepDisplayProjection,
  executionStepDisplayKey,
} from '../../shared/presentation/executionStepProjection'
export {
  buildExecutionStepDisplayGroups as groupRepeatedSteps,
  executionStepDisplayKey as stepPresentationKey,
} from '../../shared/presentation/executionStepProjection'
export type { ExecutionStepDisplayItem as StepPresentationItem } from '../../shared/presentation/executionStepProjection'

export function formatTimestamp(value: string | null | undefined, locale: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function formatTime(value: string | null | undefined, locale: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    hour12: false,
    minute: '2-digit',
  }).format(date)
}

export function formatDuration(durationMs: number | null | undefined) {
  if (durationMs === null || durationMs === undefined) return '—'
  if (durationMs < 1000) return `${durationMs} ms`
  return `${(durationMs / 1000).toFixed(durationMs < 10000 ? 2 : 1)} s`
}

export function formatValue(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return '—'
  }
}

function offsetFrom(start: string, current: string) {
  const offset = new Date(current).getTime() - new Date(start).getTime()
  if (!Number.isFinite(offset) || offset <= 0) return '0 ms'
  return `+${offset} ms`
}

export function runTimeline(summary: RunSummary): TimelineStep[] {
  const timeline: TimelineStep[] = [{
    label: 'Run created',
    offset: '0 ms',
    tone: 'neutral',
  }]

  if (summary.startedAt) {
    timeline.push({
      label: 'Run started',
      offset: offsetFrom(summary.createdAt, summary.startedAt),
      tone: 'accent',
    })
  }

  if (summary.finishedAt) {
    const terminalLabel = summary.status === 'SUCCESS'
      ? 'Run completed'
      : summary.status === 'ASSERTION_FAILED'
        ? 'Assertion failed'
        : summary.status === 'TIMEOUT'
          ? 'Run timed out'
          : summary.status === 'CANCELLED'
            ? 'Run cancelled'
            : 'Execution failed'
    timeline.push({
      label: terminalLabel,
      offset: offsetFrom(summary.createdAt, summary.finishedAt),
      tone: summary.status === 'SUCCESS' ? 'success' : 'danger',
    })
  }

  return timeline
}
