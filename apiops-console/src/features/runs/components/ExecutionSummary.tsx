import { Database, FileCheck2, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { RunLiveState, RunProgress, RunSummary, TestReport } from '../types'

type ExecutionSummaryProps = {
  run: RunSummary | null
  report: TestReport | null
  progress: RunProgress | null
  liveState: RunLiveState
}

export function ExecutionSummary({ liveState, progress, report, run }: ExecutionSummaryProps) {
  const { t, ui } = useConsoleLanguage()

  if (!run) {
    return (
      <section className="execution-summary" aria-label={ui('Run summary')}>
        <div className="run-empty-panel">{t('runs.noRunSelected')}</div>
      </section>
    )
  }

  const summary = report?.summary
  const metrics = [
    { icon: Database, label: 'Cases', value: summary?.totalCases },
    { icon: FileCheck2, label: 'Steps', value: summary?.totalSteps },
    { icon: ShieldCheck, label: 'Assertions', value: summary?.totalAssertions },
    { icon: TriangleAlert, label: 'Failed', value: summary?.failedAssertions },
  ]

  return (
    <section className="execution-summary" aria-label={ui('Run summary')}>
      <div className="run-summary-card-grid">
        {metrics.map(({ icon: Icon, label, value }) => (
          <div className="run-summary-card" key={label}>
            <div className="run-summary-card-label">
              <span>{ui(label)}</span>
              <Icon size={16} strokeWidth={1.8} />
            </div>
            <strong>{value ?? '—'}</strong>
          </div>
        ))}
      </div>
      {run.status === 'RUNNING' ? (
        <div className={`run-live-status is-${liveState}`}>
          <span className="run-live-dot" />
          <span>{liveState === 'disconnected' ? t('runs.disconnected') : t('runs.live')}</span>
          {progress && progress.total > 0 ? <strong>{progress.completed} / {progress.total} {t('runs.progressCompleted')}</strong> : null}
        </div>
      ) : null}
    </section>
  )
}
