import {
  Activity,
  Braces,
  CircleDollarSign,
  Clock3,
  FileCheck2,
  Info,
  Scale,
  ShieldCheck,
  Sparkles,
  Wrench,
} from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatMetricStatus, formatRuntimeMetric, statusTone } from '../evaluationViewModel'
import type { RuntimeMetric, RuntimeRunDetail } from '../types'
import { EvaluationOverviewPanels } from './EvaluationOverviewPanels'

type EvaluationTabContentProps = {
  detail: RuntimeRunDetail
}

const validationMetrics = [
  { key: 'validJson', label: 'VALID_JSON' },
  { key: 'schemaValid', label: 'SCHEMA_VALID' },
  { key: 'contractAccepted', label: 'CONTRACT_ACCEPTED' },
] as const

const costLatencyMetrics = [
  { key: 'wallClockLatencyMs', label: 'Wall-clock latency', icon: Clock3, duration: true },
  { key: 'modelLatencyMs', label: 'Model latency', icon: Activity, duration: true },
  { key: 'promptTokens', label: 'Prompt tokens', icon: Braces, duration: false },
  { key: 'completionTokens', label: 'Completion tokens', icon: Braces, duration: false },
  { key: 'totalTokens', label: 'Total tokens', icon: Braces, duration: false },
  { key: 'cost', label: 'Cost', icon: CircleDollarSign, duration: false },
] as const

function MetricFact({ label, metric, duration = false, percentage = false, unavailableReason = 'Recorded runtime fact.' }: { label: string; metric: RuntimeMetric | undefined; duration?: boolean; percentage?: boolean; unavailableReason?: string }) {
  const { ui } = useConsoleLanguage()
  const status = metric?.status ?? 'UNKNOWN'
  return (
    <article className="evaluation-fact-card">
      <div className="evaluation-fact-card-heading">
        <span>{ui(label)}</span>
        <strong className={`evaluation-fact-status is-${statusTone(status)}`}>{ui(formatMetricStatus(status))}</strong>
      </div>
      <div className={`evaluation-fact-value is-${statusTone(status)}`}>{ui(formatRuntimeMetric(metric, { compactDuration: duration, percentage }))}</div>
      <p>{metric?.reason ?? ui(unavailableReason)}</p>
    </article>
  )
}

function UnavailableEvaluation({ children, description, title }: { children?: React.ReactNode; description: string; title: string }) {
  const { ui } = useConsoleLanguage()
  return (
    <section className="evaluation-unavailable-card">
      <span className="evaluation-unavailable-icon"><Info size={20} strokeWidth={1.8} /></span>
      <div>
        <span className="evaluation-unavailable-kicker">{ui('NOT EVALUATED')}</span>
        <h2>{ui(title)}</h2>
        <p>{ui(description)}</p>
        {children}
      </div>
    </section>
  )
}

export function EvaluationOverviewTab({ detail }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <EvaluationOverviewPanels detail={detail} />
      <div className="evaluation-boundary-note">
        <Info size={15} strokeWidth={1.8} />
        <span>{ui('Evaluation is analysis only and does not change execution facts or Java authorization. Runtime facts, deterministic scores, and model-based Judge opinions remain separate.')}</span>
      </div>
    </div>
  )
}

export function EvaluationDeterministicTab({ detail }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  const result = detail.evaluationResult
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro"><div><h2>{ui('Deterministic Evaluation')}</h2><p>{ui('Rule-based evaluation requires a persisted EvaluationResult correlated to this Agent Run.')}</p></div><Scale size={18} strokeWidth={1.8} /></div>
      {result ? (
        <>
          <section className="evaluation-runtime-section">
            <div className="evaluation-section-heading"><h2>{ui('Persisted EvaluationResult')}</h2></div>
            <div className="evaluation-runtime-identity-grid">
              <div><span>{ui('Evaluation ID')}</span><code>{result.evaluation_id}</code></div>
              <div><span>{ui('Case ID')}</span><code>{result.case_id}</code></div>
              <div><span>{ui('Evaluator version')}</span><code>{result.evaluator_version}</code></div>
              <div><span>{ui('Ground Truth')}</span><code>{result.ground_truth_id}</code></div>
              <div><span>{ui('Ground Truth version')}</span><code>{result.ground_truth_version}</code></div>
              <div><span>{ui('Trace ID')}</span><code>{result.trace_id}</code></div>
            </div>
          </section>
          <div className="evaluation-fact-grid">
            {result.metrics.map((metric) => <MetricFact key={metric.metric} label={metric.metric} metric={metric} unavailableReason="Persisted deterministic evaluator result." />)}
          </div>
        </>
      ) : (
        <UnavailableEvaluation
          description={`GROUND TRUTH UNAVAILABLE for this Agent Run (${detail.agentRunId}).`}
          title="Deterministic result unavailable"
        >
          <p>{ui('No formal EvaluationCase and Ground Truth were available, so no accuracy score was inferred from Trace facts.')}</p>
        </UnavailableEvaluation>
      )}
    </div>
  )
}

export function EvaluationJudgeTab({ detail }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro"><div><h2>{ui('LLM Judge')}</h2><p>{ui('Model-based semantic evaluation remains separate from deterministic and execution facts.')}</p></div><Sparkles size={18} strokeWidth={1.8} /></div>
      {detail.judgeResults.length > 0 ? detail.judgeResults.map((judge) => (
        <section className="evaluation-runtime-section" key={judge.judge_result_id}>
          <div className="evaluation-section-heading"><h2>{ui(judge.dimension)}</h2><strong>{judge.score.toFixed(2)} / 1.00</strong></div>
          <p className="evaluation-section-description">{judge.reason}</p>
          <div className="evaluation-runtime-identity-grid">
            <div><span>{ui('Judge result ID')}</span><code>{judge.judge_result_id}</code></div>
            <div><span>{ui('Rubric')}</span><code>{judge.configuration.rubric.rubric_id}</code></div>
            <div><span>{ui('Rubric version')}</span><code>{judge.configuration.rubric.version}</code></div>
            <div><span>{ui('Judge model')}</span><code>{judge.configuration.model_identity.provider} / {judge.configuration.model_identity.model}</code></div>
            <div><span>{ui('Model version')}</span><code>{judge.configuration.model_identity.version ?? 'UNAVAILABLE'}</code></div>
            <div><span>{ui('Prompt version')}</span><code>{judge.configuration.prompt.name} / {judge.configuration.prompt.version}</code></div>
          </div>
        </section>
      )) : (
        <UnavailableEvaluation
          description={`No persisted JudgeResult was recorded for this Agent Run (${detail.agentRunId}).`}
          title="Judge result unavailable"
        >
          <ul className="evaluation-boundary-list">
            <li>{ui('Judge is model-based evaluation.')}</li>
            <li>{ui('Judge is not run automatically to fill this page.')}</li>
            <li>{ui('Judge does not change execution facts.')}</li>
            <li>{ui('Judge does not authorize tools.')}</li>
          </ul>
        </UnavailableEvaluation>
      )}
    </div>
  )
}

export function EvaluationRuntimeFactsTab({ detail }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  const runtimeFacts = [
    ['Execution type', detail.executionType],
    ['Status', detail.status],
    ['Agent run ID', detail.agentRunId],
    ['Trace ID', detail.traceId],
    ['Provider / model', `${detail.provider} / ${detail.model}`],
    ['Trace records', String(detail.traceRecordCount)],
  ]
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro"><div><h2>{ui('Runtime Facts')}</h2><p>{ui('Observed execution facts from Python AgentLab; these are not Evaluation scores.')}</p></div><Activity size={18} strokeWidth={1.8} /></div>

      <section className="evaluation-runtime-section">
        <div className="evaluation-section-heading"><h2>{ui('Runtime identity')}</h2></div>
        <div className="evaluation-runtime-identity-grid">
          {runtimeFacts.map(([label, value]) => <div key={label}><span>{ui(label)}</span><code title={value}>{value}</code></div>)}
        </div>
      </section>

      <section className="evaluation-runtime-section">
        <div className="evaluation-section-heading"><h2>{ui('Validation')}</h2><FileCheck2 size={16} strokeWidth={1.8} /></div>
        <p className="evaluation-section-description">{ui('Validation is N/A for Diagnosis runs and is never rendered as numeric zero.')}</p>
        <div className="evaluation-fact-grid">
          {validationMetrics.map(({ key, label }) => <MetricFact key={key} label={label} metric={detail.metrics[key]} percentage />)}
        </div>
      </section>

      <section className="evaluation-runtime-section">
        <div className="evaluation-section-heading"><h2>{ui('Tool Execution')}</h2><Wrench size={16} strokeWidth={1.8} /></div>
        <p className="evaluation-section-description">{ui('These are observed ToolIntent / ToolResult outcomes, not Tool Accuracy.')}</p>
        <div className="evaluation-tool-grid">
          {Object.entries({
            Attempted: detail.toolCounts.attempted,
            SUCCESS: detail.toolCounts.success,
            FAILED: detail.toolCounts.failed,
            DENIED: detail.toolCounts.denied,
            TIMEOUT: detail.toolCounts.timeout,
            UNKNOWN: detail.toolCounts.unknown,
            'N/A': detail.toolCounts.notApplicable,
          }).map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
        </div>
      </section>

      <section className="evaluation-runtime-section">
        <div className="evaluation-section-heading"><h2>{ui('Safety')}</h2><ShieldCheck size={16} strokeWidth={1.8} /></div>
        <p className="evaluation-section-description">{ui('A Python runtime ALLOW observation does not replace Java Tool Gateway authorization.')}</p>
        <div className="evaluation-safety-readout">
          <span className={`is-${statusTone(detail.safetyStatus)}`}>{formatMetricStatus(detail.safetyStatus)}</span>
          <strong>{detail.safetyOutcome ?? formatMetricStatus(detail.safetyStatus)}</strong>
          <p>{detail.safetyReason ?? ui('An explicit runtime safety outcome was recorded.')}</p>
        </div>
      </section>
    </div>
  )
}

export function EvaluationCostLatencyTab({ detail }: EvaluationTabContentProps) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="evaluation-tab-stack">
      <div className="evaluation-tab-intro"><div><h2>{ui('Cost & Latency')}</h2><p>{ui('Runtime timing and provider usage retain their original VALUE, UNKNOWN, ERROR, or N/A semantics.')}</p></div><Clock3 size={18} strokeWidth={1.8} /></div>
      <div className="evaluation-cost-grid">
        {costLatencyMetrics.map(({ duration, icon: Icon, key, label }) => {
          const metric = detail.metrics[key]
          const status = metric?.status ?? 'UNKNOWN'
          return (
            <article className="evaluation-cost-card" key={key}>
              <span className="evaluation-cost-icon"><Icon size={18} strokeWidth={1.8} /></span>
              <div><span>{ui(label)}</span><strong className={`is-${statusTone(status)}`}>{formatRuntimeMetric(metric, { compactDuration: duration })}</strong><small>{metric?.reason ?? ui('Recorded runtime fact.')}</small></div>
              <span className={`evaluation-fact-status is-${statusTone(status)}`}>{ui(formatMetricStatus(status))}</span>
            </article>
          )
        })}
      </div>
      <div className="evaluation-boundary-note"><Info size={15} strokeWidth={1.8} /><span>{ui('The frontend does not infer provider pricing. Missing versioned runtime pricing remains UNKNOWN.')}</span></div>
    </div>
  )
}
