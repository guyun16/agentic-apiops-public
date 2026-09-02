import { AlertTriangle, ArrowRight, CircleHelp, CircleX, ShieldAlert } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { HealthItem } from '../types'
import type { RuntimeEvaluationSummary } from '../../evaluation/types'
import type { RunSummary } from '../../runs/types'

type NavigationTarget = 'Runs' | 'Diagnosis' | 'Traces' | 'Evaluation'

type AttentionItemsProps = {
  healthItems: HealthItem[]
  healthLoading: boolean
  runs: RunSummary[]
  runsState: 'loading' | 'ready' | 'error'
  evaluation: RuntimeEvaluationSummary | null
  onNavigate: (target: NavigationTarget) => void
}

type AttentionItem = {
  detail: string
  icon: LucideIcon
  id: string
  target?: NavigationTarget
  title: string
  tone: 'danger' | 'warning'
}

const failureStatuses = new Set(['ASSERTION_FAILED', 'EXECUTION_FAILED', 'TIMEOUT'])

export function AttentionItems({
  evaluation,
  healthItems,
  healthLoading,
  onNavigate,
  runs,
  runsState,
}: AttentionItemsProps) {
  const { t, ui } = useConsoleLanguage()
  const items: AttentionItem[] = []

  if (!healthLoading) {
    healthItems
      .filter((health) => health.status !== 'UP')
      .forEach((health) => {
        const icon = health.sourceAvailable
          ? health.status === 'DOWN' ? CircleX : AlertTriangle
          : CircleHelp
        items.push({
          detail: health.sourceAvailable
            ? ui('The live health source reported an attention state.')
            : ui('The health source is unavailable; status remains UNKNOWN.'),
          icon,
          id: `health-${health.id}`,
          title: `${ui(health.name)} · ${health.status}`,
          tone: health.status === 'DOWN' ? 'danger' : 'warning',
        })
      })
  }

  if (runsState === 'ready') {
    runs
      .filter((run) => failureStatuses.has(run.status))
      .slice(0, 3)
      .forEach((run) => {
        items.push({
          detail: `${run.testCaseName} · ${t(`runs.status.${run.status}`)}`,
          icon: AlertTriangle,
          id: `run-${run.runId}`,
          target: 'Runs',
          title: `${ui('Recent failure')} · #${run.runId}`,
          tone: 'danger',
        })
      })
  }

  if (evaluation?.execution.failure) {
    items.push({
      detail: `${evaluation.execution.failure} · ${ui('Runtime Evaluation failed executions')}`,
      icon: AlertTriangle,
      id: 'runtime-evaluation-failures',
      target: 'Evaluation',
      title: ui('Runtime Evaluation needs attention'),
      tone: 'danger',
    })
  }

  if (evaluation?.execution.approvalRequired) {
    items.push({
      detail: `${evaluation.execution.approvalRequired} · ${ui('runs awaiting approval')}`,
      icon: ShieldAlert,
      id: 'runtime-evaluation-approval',
      target: 'Evaluation',
      title: ui('Approval required'),
      tone: 'warning',
    })
  }

  return (
    <section aria-labelledby="attention-items-title" className="overview-attention panel">
      <div className="panel-header">
        <div className="panel-heading">
          <AlertTriangle size={18} strokeWidth={1.8} />
          <h2 id="attention-items-title">{ui('Recent failures / attention')}</h2>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="overview-inline-state overview-inline-state-empty">
          <CircleHelp size={17} strokeWidth={1.8} />
          <span>{ui('No recent failures or attention items.')}</span>
        </div>
      ) : (
        <div className="attention-list">
          {items.slice(0, 5).map(({ detail, icon: Icon, id, target, title, tone }) => (
            <div className={`attention-row attention-row-${tone}`} key={id}>
              <span className="attention-icon"><Icon size={16} strokeWidth={1.8} /></span>
              <div className="attention-copy">
                <strong>{title}</strong>
                <span>{detail}</span>
              </div>
              {target ? (
                <button
                  aria-label={`${ui('View details')} · ${title}`}
                  className="attention-action"
                  onClick={() => onNavigate(target)}
                  title={ui('View details')}
                  type="button"
                >
                  <ArrowRight size={15} strokeWidth={1.8} />
                </button>
              ) : <span aria-hidden="true" className="attention-action-placeholder" />}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
