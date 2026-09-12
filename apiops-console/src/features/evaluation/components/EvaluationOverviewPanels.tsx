import {
  Activity,
  CheckCircle2,
  CircleDollarSign,
  CircleHelp,
  Clock3,
  FileCheck2,
  FileText,
  Gauge,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { evaluationCoverage, formatMetricStatus, formatRuntimeMetric, statusTone, validationSummary } from '../evaluationViewModel'
import type { RuntimeMetric, RuntimeRunDetail } from '../types'

type EvaluationOverviewPanelsProps = {
  detail: RuntimeRunDetail
}

function CoverageState({ label, metric, reason, tone: explicitTone }: { label?: string; metric?: RuntimeMetric; reason: string; tone?: 'neutral' | 'success' }) {
  const { ui } = useConsoleLanguage()
  const status = metric?.status
  const value = label ?? (status === 'VALUE' ? formatRuntimeMetric(metric) : formatMetricStatus(status))
  const tone = explicitTone ?? (status ? statusTone(status) : label === 'AVAILABLE' ? 'success' : 'neutral')
  return (
    <div className="evaluation-coverage-state">
      <span className={`evaluation-coverage-value is-${tone}`}>
        {tone === 'success' ? <CheckCircle2 size={13} /> : <CircleHelp size={13} />}
        {ui(value)}
      </span>
      <small>{reason}</small>
    </div>
  )
}

function OverviewCard({ icon: Icon, label, note, tone, value }: {
  icon: typeof Activity
  label: string
  note: string
  tone: 'accent' | 'danger' | 'neutral' | 'success' | 'warning'
  value: string
}) {
  const { ui } = useConsoleLanguage()
  return (
    <article className={`evaluation-overview-card is-${tone}`}>
      <span className="evaluation-overview-icon"><Icon size={22} strokeWidth={1.9} /></span>
      <div>
        <span>{ui(label)}</span>
        <strong>{ui(value)}</strong>
        <small>{ui(note)}</small>
      </div>
    </article>
  )
}

function toolSummary(detail: RuntimeRunDetail) {
  const tool = detail.toolCounts
  if (tool.notApplicable > 0 && tool.attempted === 0) return { value: 'N/A', note: 'No tool attempt' }
  if (tool.unknown > 0) return { value: `${tool.success} SUCCESS`, note: `${tool.unknown} UNKNOWN` }
  const nonSuccess = tool.failed + tool.denied + tool.timeout
  return { value: `${tool.success} SUCCESS`, note: nonSuccess ? `${nonSuccess} non-success` : `${tool.denied} DENIED` }
}

export function EvaluationOverviewPanels({ detail }: EvaluationOverviewPanelsProps) {
  const { ui } = useConsoleLanguage()
  const validation = validationSummary(detail)
  const coverage = evaluationCoverage(detail)
  const tool = toolSummary(detail)
  const safetyValue = detail.safetyStatus === 'VALUE' ? detail.safetyOutcome ?? 'UNKNOWN' : formatMetricStatus(detail.safetyStatus)
  const executionTone = statusTone(detail.status)
  const validationTone = validation.tone
  const toolTone = detail.toolCounts.failed > 0 || detail.toolCounts.timeout > 0 ? 'danger' : detail.toolCounts.denied > 0 || detail.toolCounts.unknown > 0 ? 'warning' : detail.toolCounts.notApplicable > 0 ? 'neutral' : 'success'
  const safetyTone = detail.safetyStatus === 'VALUE' ? 'accent' : statusTone(detail.safetyStatus)
  const atGlance = [
    { label: 'Total Runtime', value: formatRuntimeMetric(detail.metrics.wallClockLatencyMs, { compactDuration: true }), note: 'wall clock', icon: Clock3, status: detail.metrics.wallClockLatencyMs?.status },
    { label: 'Model Latency', value: formatRuntimeMetric(detail.metrics.modelLatencyMs, { compactDuration: true }), note: 'model time', icon: Gauge, status: detail.metrics.modelLatencyMs?.status },
    { label: 'Tool Calls', value: detail.toolCounts.notApplicable > 0 && detail.toolCounts.attempted === 0 ? 'N/A' : String(detail.toolCounts.attempted), note: detail.toolCounts.notApplicable > 0 && detail.toolCounts.attempted === 0 ? 'no tool attempt' : `${detail.toolCounts.success} success`, icon: Wrench, status: detail.toolCounts.notApplicable > 0 && detail.toolCounts.attempted === 0 ? 'NOT_APPLICABLE' as const : detail.toolCounts.unknown ? 'UNKNOWN' as const : 'VALUE' as const },
    { label: 'Tokens', value: formatRuntimeMetric(detail.metrics.totalTokens), note: 'total tokens', icon: FileText, status: detail.metrics.totalTokens?.status },
    { label: 'Estimated Cost', value: formatRuntimeMetric(detail.metrics.cost), note: detail.metrics.cost?.reason ?? 'runtime pricing fact', icon: CircleDollarSign, status: detail.metrics.cost?.status },
    { label: 'Safety Outcome', value: safetyValue, note: detail.safetyReason ?? 'explicit fact', icon: ShieldCheck, status: detail.safetyStatus },
  ]

  return (
    <div className="evaluation-overview-stack">
      <section aria-labelledby="evaluation-execution-overview-title">
        <div className="evaluation-section-heading">
          <h2 id="evaluation-execution-overview-title">{ui('Execution Overview')}</h2>
        </div>
        <div className="evaluation-execution-grid">
          <OverviewCard icon={Activity} label="Execution" note="Runtime fact" tone={executionTone} value={detail.status} />
          <OverviewCard icon={FileCheck2} label="Validation" note={validation.note} tone={validationTone} value={validation.label} />
          <OverviewCard icon={Wrench} label="Tool Outcome" note={tool.note} tone={toolTone} value={tool.value} />
          <OverviewCard icon={ShieldCheck} label="Safety" note={detail.safetyReason ?? 'Explicit runtime fact'} tone={safetyTone} value={safetyValue} />
        </div>
      </section>

      <section className="evaluation-coverage-card" aria-labelledby="evaluation-coverage-title">
        <div className="evaluation-section-heading">
          <h2 id="evaluation-coverage-title">{ui('Evaluation Coverage')}</h2>
        </div>
        <div className="evaluation-coverage-grid">
          <div className="evaluation-coverage-row"><span>{ui('Runtime Facts')}</span><CoverageState label="AVAILABLE" reason={ui('Execution facts were recorded.')} /></div>
          <div className="evaluation-coverage-row"><span>{ui('Deterministic Evaluation')}</span><CoverageState {...coverage.deterministic} reason={ui(coverage.deterministic.reason)} /></div>
          <div className="evaluation-coverage-row"><span>{ui('LLM Judge')}</span><CoverageState {...coverage.judge} reason={ui(coverage.judge.reason)} /></div>
          <div className="evaluation-coverage-row"><span>{ui('Token Usage')}</span><CoverageState metric={detail.metrics.totalTokens} reason={detail.metrics.totalTokens?.reason ?? ui('Provider usage was recorded.')} /></div>
          <div className="evaluation-coverage-row"><span>{ui('Cost')}</span><CoverageState metric={detail.metrics.cost} reason={detail.metrics.cost?.reason ?? ui('Runtime cost was recorded.')} /></div>
        </div>
      </section>

      <section aria-labelledby="evaluation-at-glance-title">
        <div className="evaluation-section-heading">
          <h2 id="evaluation-at-glance-title">{ui('At a Glance')}</h2>
        </div>
        <div className="evaluation-glance-grid">
          {atGlance.map(({ icon: Icon, label, note, status, value }) => (
            <article className="evaluation-glance-card" key={label}>
              <Icon size={17} strokeWidth={1.8} />
              <span>{ui(label)}</span>
              <strong className={`is-${statusTone(status ?? 'UNKNOWN')}`}>{ui(value)}</strong>
              <small title={note}>{ui(note)}</small>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
