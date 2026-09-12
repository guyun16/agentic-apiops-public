import { Activity, ArrowRight, Braces, Clock3, FileSearch, Play, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { runtimeNavigation } from '../evaluationViewModel'
import type { RuntimeRunDetail } from '../types'

type EvaluationSummaryProps = {
  onViewDiagnosis?: (agentRunId: string) => void
  onViewRun?: (runId: number) => void
  onViewTrace?: (traceId: string) => void
  run: RuntimeRunDetail
}

function formatTimestamp(value: string | null) {
  if (!value) return 'UNKNOWN'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' }).format(date)
}

function executionTitle(type: RuntimeRunDetail['executionType']) {
  return type === 'TESTCASE_GENERATION' ? 'TESTCASE GENERATION' : 'DIAGNOSIS'
}

export function EvaluationSummary({ onViewDiagnosis, onViewRun, onViewTrace, run }: EvaluationSummaryProps) {
  const { ui } = useConsoleLanguage()
  const navigation = runtimeNavigation(run)
  const identityFacts = [
    run.apiId ? { label: 'API', value: run.apiId } : null,
    run.reportId ? { label: 'Report', value: run.reportId } : null,
    { label: 'Started', value: formatTimestamp(run.startedAt) },
    run.finishedAt ? { label: 'Finished', value: formatTimestamp(run.finishedAt) } : null,
  ].filter((item): item is { label: string; value: string } => item !== null)

  return (
    <section className="evaluation-summary panel" aria-labelledby="evaluation-summary-title">
      <div className="evaluation-identity-main">
        <div className="evaluation-identity-mark" aria-hidden="true"><Activity size={27} strokeWidth={1.8} /></div>
        <div className="evaluation-summary-title">
          <div className="evaluation-title-line">
            <h2 id="evaluation-summary-title">{ui(executionTitle(run.executionType))}</h2>
          </div>
          <code className="evaluation-summary-code" title={run.agentRunId}>{run.agentRunId}</code>
        </div>
        <span className={`evaluation-status evaluation-status-${run.status.toLowerCase()}`}>{ui(run.status).replace(/_/g, ' ')}</span>
      </div>

      <div className="evaluation-identity-links">
        {navigation.runId !== null ? (
          <button onClick={() => onViewRun?.(navigation.runId!)} type="button">
            <Play size={14} strokeWidth={1.8} />
            <span><small>{ui('Run')}</small><strong>#{navigation.runId}</strong></span>
            <ArrowRight size={13} strokeWidth={1.8} />
          </button>
        ) : null}
        {navigation.traceId ? (
          <button onClick={() => onViewTrace?.(navigation.traceId!)} type="button">
            <FileSearch size={14} strokeWidth={1.8} />
            <span><small>{ui('Trace')}</small><strong title={navigation.traceId}>{navigation.traceId}</strong></span>
            <ArrowRight size={13} strokeWidth={1.8} />
          </button>
        ) : null}
        {navigation.diagnosisAgentRunId ? (
          <button onClick={() => onViewDiagnosis?.(navigation.diagnosisAgentRunId!)} type="button">
            <Braces size={14} strokeWidth={1.8} />
            <span><small>{ui('Diagnosis')}</small><strong title={run.agentRunId}>{run.agentRunId}</strong></span>
            <ArrowRight size={13} strokeWidth={1.8} />
          </button>
        ) : null}
        <div className="evaluation-identity-runtime">
          <span><ShieldCheck size={13} strokeWidth={1.8} /> {run.provider} / {run.model}</span>
          <span><Clock3 size={13} strokeWidth={1.8} /> {formatTimestamp(run.startedAt)}</span>
        </div>
      </div>

      {identityFacts.length > 0 ? (
        <div className="evaluation-identity-facts">
          {identityFacts.map((fact) => <span key={fact.label}><small>{ui(fact.label)}</small><code title={fact.value}>{fact.value}</code></span>)}
        </div>
      ) : null}

      {run.failureCode || run.failureMessage ? (
        <div className="evaluation-failure-note">
          <TriangleAlert size={14} strokeWidth={1.8} />
          <span>{run.failureCode ?? 'FAILED'}: {run.failureMessage ?? ui('Runtime execution failed.')}</span>
        </div>
      ) : null}
    </section>
  )
}
