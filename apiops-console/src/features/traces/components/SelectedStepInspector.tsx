import { useEffect, type ReactNode } from 'react'
import { CheckCircle2, ChevronLeft, ChevronRight, CircleX, Clock3, Copy, FileJson, Link2, Wrench, X } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type {
  TraceApprovalFacts,
  TraceContextEvidenceFacts,
  TraceInspectorTab,
  TraceModelCallFacts,
  TraceStep,
  TraceToolActivityFacts,
} from '../types'

type SelectedStepInspectorProps = {
  activeTab: TraceInspectorTab
  hasNext: boolean
  hasPrevious: boolean
  onClose: () => void
  onNext: () => void
  onPrevious: () => void
  onTabChange: (tab: TraceInspectorTab) => void
  step: TraceStep
}

const tabs: TraceInspectorTab[] = ['Overview', 'Input', 'Output', 'Attributes']

type OverviewItem = {
  label: string
  value: ReactNode
  copy?: boolean
}

type FactItem = OverviewItem

function statusIcon(status: TraceStep['status']) {
  if (status === 'WAITING' || status === 'RUNNING' || status === 'INTERRUPTED') return <Clock3 size={14} strokeWidth={2} />
  if (status === 'FAILED' || status === 'REJECTED' || status === 'DENIED') return <CircleX size={14} strokeWidth={2} />
  return <CheckCircle2 size={14} strokeWidth={2} />
}

function copyText(value: string) {
  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    void navigator.clipboard.writeText(value)
  }
}

function CopyValueButton({ label, value }: { label: string; value: string }) {
  const { ui } = useConsoleLanguage()

  return (
    <button
      aria-label={`${ui('Copy')} ${label}`}
      className="trace-copy-button"
      onClick={() => copyText(value)}
      title={`${ui('Copy')} ${label}`}
      type="button"
    >
      <Copy size={13} strokeWidth={1.8} />
    </button>
  )
}

export function SelectedStepInspector({
  activeTab,
  hasNext,
  hasPrevious,
  onClose,
  onNext,
  onPrevious,
  onTabChange,
  step,
}: SelectedStepInspectorProps) {
  const { ui } = useConsoleLanguage()

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  return (
    <div
      className="trace-step-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        aria-labelledby="selected-step-title"
        aria-modal="true"
        className="trace-step-modal panel"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="trace-step-modal-header">
          <h2 id="selected-step-title">{ui('Selected Step Details')}</h2>
          <div className="trace-step-modal-actions">
            <button className="trace-control-button" disabled={!hasPrevious} onClick={onPrevious} type="button">
              <ChevronLeft size={14} strokeWidth={1.8} />
              {ui('Previous')}
            </button>
            <button className="trace-control-button" disabled={!hasNext} onClick={onNext} type="button">
              {ui('Next')}
              <ChevronRight size={14} strokeWidth={1.8} />
            </button>
            <button aria-label={ui('Close')} className="trace-step-modal-close" onClick={onClose} title={ui('Close')} type="button">
              <X size={18} strokeWidth={1.8} />
            </button>
          </div>
        </header>

        <div className="trace-step-modal-identity">
          <div className="trace-step-modal-title-row">
            <span className={`trace-step-modal-type trace-step-modal-type-${getStepTypeLabel(step).toLowerCase().split(' ').join('-')}`}>
              <Wrench size={15} strokeWidth={1.9} />
              {ui(getStepTypeLabel(step))}
            </span>
            <div className="trace-step-modal-name">
              <h3>{step.name}</h3>
              <code title={step.id}>{step.id}</code>
            </div>
          </div>

          <div className="trace-step-modal-facts">
            <ModalFact label={ui('Step ID')} value={step.id} copy />
            <ModalFact label={ui('Duration')} value={step.detail.durationLabel} />
            <div className="trace-modal-fact">
              <span>{ui('Status')}</span>
              <strong className={`trace-inline-status is-${step.detail.status.toLowerCase()}`}>
                {statusIcon(step.detail.status)}
                {step.detail.status}
              </strong>
            </div>
            <ModalFact label={ui('Started At')} value={step.detail.startTime} />
            <ModalFact label={ui('Ended At')} value={step.detail.endTime} />
          </div>
        </div>

        <div className="trace-step-modal-tabs" role="tablist" aria-label={ui('Selected step details')}>
          {tabs.map((tab) => (
            <button
              aria-selected={activeTab === tab}
              className={`trace-step-modal-tab${activeTab === tab ? ' is-active' : ''}`}
              key={tab}
              onClick={() => onTabChange(tab)}
              role="tab"
              type="button"
            >
              {ui(tab)}
            </button>
          ))}
        </div>

        <div className="trace-step-modal-content">
          {activeTab === 'Overview' ? <OverviewContent step={step} /> : null}
          {activeTab === 'Input' ? <JsonContent label={ui('Input Parameters')} value={step.detail.input} /> : null}
          {activeTab === 'Output' ? <JsonContent label={ui('Tool Result')} value={step.detail.output} /> : null}
          {activeTab === 'Attributes' ? <AttributesContent step={step} /> : null}
        </div>

        <footer className="trace-step-modal-footer">
          <button className="trace-control-button" onClick={onClose} type="button">{ui('Close')}</button>
        </footer>
      </section>
    </div>
  )
}

function ModalFact({ copy = false, label, value }: { copy?: boolean; label: string; value: string }) {
  return (
    <div className="trace-modal-fact">
      <span>{label}</span>
      <div className="trace-modal-fact-value">
        <strong title={value}>{value}</strong>
        {copy ? <CopyValueButton label={label} value={value} /> : null}
      </div>
    </div>
  )
}

function OverviewContent({ step }: { step: TraceStep }) {
  const { ui } = useConsoleLanguage()
  const items: OverviewItem[] = [
    { label: ui('Status'), value: <span className={`trace-inline-status is-${step.detail.status.toLowerCase()}`}><span className="trace-inline-status-icon">{statusIcon(step.detail.status)}</span> {step.detail.status}</span> },
    { label: ui('Duration'), value: step.detail.durationLabel },
    { label: ui('Parent Step'), value: step.detail.parentStep },
    { label: ui('Source'), value: <span className={`trace-source-badge trace-source-${step.detail.source.toLowerCase()}`}>{step.detail.source}</span> },
    { label: ui('Start Time'), value: step.detail.startTime },
    { label: ui('End Time'), value: step.detail.endTime },
    ...getIdentityItems(step),
  ]

  return (
    <div className="trace-inspector-overview">
      <div className="trace-overview-payload-grid">
        <div className="trace-overview-payload-card">
          <JsonContent label={ui('Input Parameters')} value={step.detail.input} />
        </div>
        <div className="trace-overview-payload-card">
          <JsonContent label={ui(step.detail.toolActivity ? 'Tool Result' : 'Output (JSON)')} value={step.detail.output} />
        </div>
        <div className="trace-overview-facts">
          <TypeSpecificFacts step={step} />
          {!step.detail.modelCall && !step.detail.toolActivity && !step.detail.approval && !step.detail.contextEvidence ? (
            <div className="trace-overview-unavailable">{ui('No type-specific facts are available.')}</div>
          ) : null}
        </div>
        <RelatedLinksContent step={step} />
      </div>

      <div className="trace-overview-grid">
        {items.map((item) => (
          <div className="trace-overview-item" key={item.label}>
            <span>{item.label}</span>
            <strong title={typeof item.value === 'string' ? item.value : undefined}>{item.value}</strong>
            {item.copy && typeof item.value === 'string' ? <CopyValueButton label={item.label} value={item.value} /> : null}
          </div>
        ))}
      </div>
    </div>
  )
}

function RelatedLinksContent({ step }: { step: TraceStep }) {
  const { ui } = useConsoleLanguage()
  const links = [
    { label: ui('Trace ID'), value: step.detail.traceId, copy: true },
    { label: ui('Parent Step'), value: step.detail.parentStep },
    ...(step.detail.agentStepId ? [{ label: ui('Agent Step ID'), value: step.detail.agentStepId, copy: true }] : []),
    ...(step.detail.toolIntentId ? [{ label: ui('Tool Intent ID'), value: step.detail.toolIntentId, copy: true }] : []),
    ...(step.detail.toolCallId ? [{ label: ui('Tool Call ID'), value: step.detail.toolCallId, copy: true }] : []),
  ]

  return (
    <section className="trace-related-links">
      <div className="trace-related-links-heading">
        <Link2 size={15} strokeWidth={1.8} />
        <h3>{ui('Related Links')}</h3>
      </div>
      <div className="trace-related-link-list">
        {links.map((link) => (
          <div className="trace-related-link" key={link.label}>
            <span>{link.label}</span>
            <div>
              <code title={link.value}>{link.value}</code>
              {link.copy ? <CopyValueButton label={link.label} value={link.value} /> : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function TypeSpecificFacts({ step }: { step: TraceStep }) {
  const { ui } = useConsoleLanguage()
  const sections: ReactNode[] = []

  if (step.detail.modelCall) {
    sections.push(<ModelCallSection facts={step.detail.modelCall} key="model-call" />)
  }
  if (step.detail.toolActivity) {
    sections.push(<ToolActivitySection facts={step.detail.toolActivity} key="tool-activity" />)
  }
  if (step.detail.approval) {
    sections.push(<ApprovalSection facts={step.detail.approval} key="approval" />)
  }
  if (step.detail.contextEvidence) {
    sections.push(<ContextEvidenceSection facts={step.detail.contextEvidence} key="context-evidence" />)
  }

  if (sections.length === 0) return null

  return (
    <div className="trace-fact-sections" aria-label={ui('Step facts')}>
      {sections}
    </div>
  )
}

function ModelCallSection({ facts }: { facts: TraceModelCallFacts }) {
  const { ui } = useConsoleLanguage()
  const items: FactItem[] = [
    { label: ui('Model'), value: facts.model },
    { label: ui('Provider'), value: facts.provider },
    { label: ui('Runtime'), value: facts.runtime },
    { label: ui('Implementation'), value: facts.implementation },
    { label: ui('Prompt'), value: facts.promptName },
    { label: ui('Prompt Version'), value: facts.promptVersion },
    { label: ui('Model Call ID'), value: facts.modelCallId, copy: true },
    { label: ui('Started At'), value: facts.startedAt },
    { label: ui('Latency'), value: facts.durationLabel },
    { label: ui('Input Tokens'), value: facts.inputTokens ?? 'UNKNOWN' },
    { label: ui('Output Tokens'), value: facts.outputTokens ?? 'UNKNOWN' },
    { label: ui('Total Tokens'), value: facts.totalTokens ?? 'UNKNOWN' },
    { label: ui('Cost'), value: facts.cost ?? 'UNKNOWN' },
    { label: ui('Status'), value: <span className={`trace-inline-status is-${facts.status.toLowerCase()}`}>{statusIcon(facts.status)} {facts.status}</span> },
  ]

  if (facts.attempt !== undefined) items.push({ label: ui('Attempt'), value: facts.attempt })
  if (facts.errorType) items.push({ label: ui('Error Type'), value: facts.errorType })

  return (
    <FactSection
      description={ui('Observed model-call facts only; answer quality belongs in Evaluation.')}
      facts={items}
      title={ui('Model Call')}
    />
  )
}

function ToolActivitySection({ facts }: { facts: TraceToolActivityFacts }) {
  const { ui } = useConsoleLanguage()
  const items = compactFacts([
    { label: ui('Phase'), value: facts.phase },
    { label: ui('Tool'), value: facts.toolName },
    facts.toolIntentId ? { label: ui('Tool Intent ID'), value: facts.toolIntentId, copy: true } : null,
    facts.toolCallId ? { label: ui('Tool Call ID'), value: facts.toolCallId, copy: true } : null,
    facts.requestId ? { label: ui('Request ID'), value: facts.requestId, copy: true } : null,
    facts.risk ? { label: ui('Risk'), value: facts.risk } : null,
    facts.preflightDecision ? { label: ui('Preflight Decision'), value: facts.preflightDecision } : null,
    facts.approvalOutcome ? { label: ui('Approval Outcome'), value: facts.approvalOutcome } : null,
    facts.authorizationResult ? { label: ui('Authorization Result'), value: facts.authorizationResult } : null,
    facts.guardDecision ? { label: ui('Guard Decision'), value: facts.guardDecision } : null,
    facts.status ? { label: ui('Status'), value: facts.status } : null,
    facts.toolResultStatus ? { label: ui('ToolResult Status'), value: facts.toolResultStatus } : null,
    facts.hasData !== undefined ? { label: ui('Has Data'), value: String(facts.hasData) } : null,
    facts.latencyLabel ? { label: ui('Latency'), value: facts.latencyLabel } : null,
    facts.sanitized !== undefined ? { label: ui('Sanitized'), value: String(facts.sanitized) } : null,
    facts.truncated !== undefined ? { label: ui('Truncated'), value: String(facts.truncated) } : null,
    facts.violationCode ? { label: ui('Violation Code'), value: facts.violationCode } : null,
    facts.resultSummary ? { label: ui('Result Summary'), value: facts.resultSummary } : null,
  ])
  const javaBoundary = facts.phase === 'GATEWAY' || facts.phase === 'RESULT'

  return (
    <FactSection
      description={ui('Python intent facts and Java Tool Gateway authority facts remain separate.')}
      facts={items}
      title={ui(javaBoundary ? 'Authorization / Guard / Audit' : 'Tool Activity')}
    />
  )
}

function ApprovalSection({ facts }: { facts: TraceApprovalFacts }) {
  const { ui } = useConsoleLanguage()
  const items = compactFacts([
    { label: ui('Tool Intent ID'), value: facts.toolIntentId, copy: true },
    { label: ui('Decision'), value: facts.decision ?? 'UNKNOWN' },
    facts.reason ? { label: ui('Reason'), value: facts.reason } : null,
  ])

  return <FactSection facts={items} title={ui('HITL / Approval')} />
}

function ContextEvidenceSection({ facts }: { facts: TraceContextEvidenceFacts }) {
  const { ui } = useConsoleLanguage()
  const items = compactFacts([
    facts.ragQueryId ? { label: ui('RAG Query ID'), value: facts.ragQueryId, copy: true } : null,
    facts.query ? { label: ui('Query'), value: facts.query } : null,
    facts.contextSources.length > 0 ? { label: ui('Context Sources'), value: facts.contextSources.join(' · ') } : null,
    facts.totalChars !== undefined ? { label: ui('Context Size'), value: `${facts.totalChars} chars` } : null,
    facts.maxTotalChars !== undefined ? { label: ui('Context Budget'), value: `${facts.maxTotalChars} chars` } : null,
    facts.truncated !== undefined ? { label: ui('Truncated'), value: String(facts.truncated) } : null,
    facts.memoryId ? { label: ui('Memory ID'), value: facts.memoryId, copy: true } : null,
  ])

  return (
    <FactSection
      description={ui('Context and evidence visible to the workflow; diagnosis conclusions belong in Diagnosis.')}
      facts={items}
      title={ui('Context & Evidence')}
    >
      {facts.evidence.length > 0 ? (
        <div className="trace-evidence-list">
          <h4>{ui('Evidence Items')}</h4>
          {facts.evidence.map((item) => (
            <article className="trace-evidence-item" key={`${item.sourceType}-${item.sourceId}-${item.chunkId ?? 'source'}`}>
              <div className="trace-evidence-item-header">
                <strong>{item.sourceType}</strong>
                <code>{item.sourceId}</code>
              </div>
              <div className="trace-evidence-item-facts">
                {item.documentId ? <span><small>{ui('Document ID')}</small><code>{item.documentId}</code></span> : null}
                {item.chunkId ? <span><small>{ui('Chunk ID')}</small><code>{item.chunkId}</code></span> : null}
                {item.location ? <span><small>{ui('Location')}</small><code>{item.location}</code></span> : null}
                {item.relevanceScore !== undefined ? <span><small>{ui('Relevance')}</small><strong>{item.relevanceScore.toFixed(3)}</strong></span> : null}
              </div>
              {item.citation ? <p><span>{ui('Citation')}</span>{item.citation}</p> : null}
            </article>
          ))}
        </div>
      ) : null}
    </FactSection>
  )
}

function FactSection({ children, description, facts, title }: { children?: ReactNode; description?: string; facts: FactItem[]; title: string }) {
  return (
    <section className="trace-fact-section">
      <div className="trace-fact-section-heading">
        <h3>{title}</h3>
        {description ? <p>{description}</p> : null}
      </div>
      {facts.length > 0 ? <FactGrid facts={facts} /> : null}
      {children}
    </section>
  )
}

function FactGrid({ facts }: { facts: FactItem[] }) {
  return (
    <div className="trace-fact-grid">
      {facts.map((item) => (
        <div className="trace-fact-item" key={item.label}>
          <span>{item.label}</span>
          <strong title={typeof item.value === 'string' ? item.value : undefined}>{item.value}</strong>
          {item.copy && typeof item.value === 'string' ? <CopyValueButton label={item.label} value={item.value} /> : null}
        </div>
      ))}
    </div>
  )
}

function compactFacts(facts: Array<FactItem | null>) {
  return facts.filter((item): item is FactItem => item !== null)
}

function getStepTypeLabel(step: TraceStep) {
  if (step.status === 'WAITING' || step.status === 'RUNNING' || step.status === 'INTERRUPTED') return 'WAITING'
  if (step.detail.modelCall) return 'LLM CALL'
  if (step.detail.toolActivity) return 'TOOL CALL'
  if (step.detail.approval) return 'HUMAN ACTION'
  if (step.detail.contextEvidence) return 'RAG QUERY'
  return step.kind === 'TOOL' ? 'TOOL CALL' : step.kind
}

function getIdentityItems(step: TraceStep): OverviewItem[] {
  const candidates = [
    { label: 'traceId', value: step.detail.traceId, copy: true },
    { label: 'agentRunId', value: step.detail.agentRunId, copy: true },
    { label: 'agentStepId', value: step.detail.agentStepId, copy: true },
    { label: 'modelCallId', value: step.detail.modelCallId ?? step.detail.modelCall?.modelCallId, copy: true },
    { label: 'toolIntentId', value: step.detail.toolIntentId ?? step.detail.toolActivity?.toolIntentId ?? step.detail.approval?.toolIntentId, copy: true },
    { label: 'toolCallId', value: step.detail.toolCallId ?? step.detail.toolActivity?.toolCallId, copy: true },
    { label: 'requestId', value: step.detail.requestId ?? step.detail.toolActivity?.requestId, copy: true },
    { label: 'ragQueryId', value: step.detail.ragQueryId ?? step.detail.contextEvidence?.ragQueryId, copy: true },
    { label: 'Decision', value: step.detail.decision ?? step.detail.approval?.decision ?? step.detail.toolActivity?.approvalOutcome },
  ]

  return candidates.filter((item): item is { label: string; value: string; copy?: boolean } => Boolean(item.value))
}

function JsonContent({ label, value }: { label: string; value: string }) {
  const { ui } = useConsoleLanguage()

  return (
    <div className="trace-json-panel">
      <div className="trace-json-heading">
        <span><FileJson size={15} strokeWidth={1.8} />{label}</span>
        <button aria-label={`${ui('Copy')} ${label}`} className="trace-json-copy" onClick={() => copyText(value)} title={`${ui('Copy')} ${label}`} type="button">
          <Copy size={14} strokeWidth={1.8} /> {ui('Copy')}
        </button>
      </div>
      <pre className="trace-code-viewer"><code>{value}</code></pre>
    </div>
  )
}

function AttributesContent({ step }: { step: TraceStep }) {
  return (
    <div className="trace-attributes-grid">
      {step.detail.attributes.map((attribute) => (
        <div className="trace-attribute-item" key={attribute.label}>
          <span>{attribute.label}</span>
          <strong>{attribute.value}</strong>
        </div>
      ))}
    </div>
  )
}
