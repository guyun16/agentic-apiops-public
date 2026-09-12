import summary from './final-result.summary.json'
import authority from '../../../../docs/stage21-benchmark-authority.json'
import type { BenchmarkRunDetail, BenchmarkRunSummary, BenchmarkTask } from './types'
import { snapshotForEvaluationRun } from './benchmarkViewModel'

export const finalResultSummary = {
  ...summary,
  displayName: 'Current · APIOps-Bench 105',
  role: 'CURRENT',
  displayOrder: 3,
} as BenchmarkRunSummary
export const benchmarkAuthority = authority
export type FinalResultReport = Omit<typeof import('./final-result.snapshot.json'), 'detail' | 'tasks'> & { detail: BenchmarkRunDetail; tasks: BenchmarkTask[] }

export async function loadFinalResult(selectedEvaluationRunId: string): Promise<FinalResultReport | null> {
  const report = (await import('./final-result.snapshot.json')).default as unknown as FinalResultReport
  if (report.evaluationRunId !== authority.portfolioAuthoritative.evaluationRunId || report.revision !== authority.portfolioAuthoritative.revision || authority.frontendDisplayRunId !== report.evaluationRunId) throw new Error('Portfolio benchmark authority mismatch')
  if (report.revision !== summary.benchmarkRevision || report.evaluationRunId !== summary.evaluationRunId || report.detail.resultSource !== 'VERIFIED_ARTIFACT_SNAPSHOT' || report.tasks.some(task => task.evaluationRunId !== report.evaluationRunId || task.formalOutcome?.revision !== report.revision)) throw new Error('Final result snapshot identity mismatch')
  return snapshotForEvaluationRun(report, selectedEvaluationRunId)
}

export function finalPercent(value: number | null | undefined) { return value == null ? 'MISSING' : (value * 100).toFixed(2) + '%' }
