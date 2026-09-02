import {
  Bot,
  ChevronDown,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  Clock3,
  Hand,
  Info,
  Search,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { TraceRecord, TraceStep } from '../types'

type TraceWaterfallProps = {
  expandedStepIds: Set<string>
  onCollapseAll: () => void
  onExpandAll: () => void
  onStepSelect: (stepId: string) => void
  onToggleStep: (stepId: string) => void
  selectedStepId: string
  trace: TraceRecord
}

type TraceVisualType = 'agent' | 'llm' | 'tool' | 'rag' | 'human' | 'waiting'

type StepPresentation = {
  Icon: LucideIcon
  key: TraceVisualType
  label: string
}

const visualTypes: TraceVisualType[] = ['agent', 'llm', 'tool', 'rag', 'human', 'waiting']

function isStepVisible(step: TraceStep, stepsById: Map<string, TraceStep>, expandedStepIds: Set<string>) {
  let parentId = step.parentId

  while (parentId) {
    if (!expandedStepIds.has(parentId)) return false
    parentId = stepsById.get(parentId)?.parentId
  }

  return true
}

function getStepPresentation(step: TraceStep): StepPresentation {
  if (step.status === 'WAITING' || step.status === 'RUNNING' || step.status === 'INTERRUPTED') {
    return { Icon: Clock3, key: 'waiting', label: 'Waiting' }
  }
  if (step.detail.approval) return { Icon: Hand, key: 'human', label: 'Human Action' }
  if (step.detail.contextEvidence) return { Icon: Search, key: 'rag', label: 'RAG Query' }
  if (step.detail.modelCall || step.kind === 'MODEL') return { Icon: Sparkles, key: 'llm', label: 'LLM Call' }
  if (step.detail.toolActivity || step.kind === 'TOOL') return { Icon: Wrench, key: 'tool', label: 'Tool Call' }
  return { Icon: Bot, key: 'agent', label: 'Agent Step' }
}

function formatDuration(durationMs: number) {
  return durationMs >= 1000 ? `${(durationMs / 1000).toFixed(2)} s` : `${durationMs} ms`
}

const scalePositions = [0, 20, 40, 60, 80, 100]

function getScaleMarks(durationMs: number) {
  return scalePositions.map((position) => ({
    label: formatDuration(Math.round(durationMs * position / 100)),
    position,
  }))
}

export function TraceWaterfall({
  expandedStepIds,
  onCollapseAll,
  onExpandAll,
  onStepSelect,
  onToggleStep,
  selectedStepId,
  trace,
}: TraceWaterfallProps) {
  const { ui } = useConsoleLanguage()
  const stepsById = new Map(trace.steps.map((step) => [step.id, step]))
  const visibleSteps = trace.steps.filter((step) => isStepVisible(step, stepsById, expandedStepIds))
  const scaleMarks = getScaleMarks(trace.durationMs)
  const timelineDuration = Math.max(trace.durationMs, 1)
  const presentVisualTypes = visualTypes.filter((key) => trace.steps.some((step) => getStepPresentation(step).key === key))

  return (
    <section className="trace-waterfall panel" aria-labelledby="trace-waterfall-title">
      <header className="trace-waterfall-header-bar">
        <div className="traces-heading">
          <Sparkles size={17} strokeWidth={1.8} />
          <h2 id="trace-waterfall-title">{ui('Execution Waterfall')}</h2>
          <span className="trace-waterfall-info" title={ui('Observed execution timing and step hierarchy')}>
            <Info size={14} strokeWidth={1.8} />
          </span>
        </div>
        <div className="trace-waterfall-actions">
          <button className="trace-control-button" onClick={onExpandAll} type="button">
            <ChevronsDown size={14} strokeWidth={1.8} />
            {ui('Expand all')}
          </button>
          <button className="trace-control-button" onClick={onCollapseAll} type="button">
            <ChevronsUp size={14} strokeWidth={1.8} />
            {ui('Collapse all')}
          </button>
        </div>
      </header>

      <div className="trace-waterfall-legend" aria-label={ui('Waterfall legend')}>
        {presentVisualTypes.map((key) => {
          const legendStep = trace.steps.find((step) => getStepPresentation(step).key === key)
          if (!legendStep) return null
          const presentation = getStepPresentation(legendStep)
          const Icon = presentation.Icon
          return (
            <span className={`trace-legend-item trace-legend-${key}`} key={key}>
              <Icon size={13} strokeWidth={1.9} />
              {ui(presentation.label)}
            </span>
          )
        })}
      </div>

      <div className="trace-waterfall-scroll">
        <div className="trace-waterfall-table">
          <div className="trace-waterfall-column-head">
            <span>{ui('Step')}</span>
            <span>{ui('Type')}</span>
            <span>{ui('Step Name')}</span>
            <div className="trace-waterfall-timeline-heading">
              <span>{ui('Timeline')} ({formatDuration(0)} — {trace.durationLabel})</span>
              <div className="trace-waterfall-scale" aria-hidden="true">
                {scaleMarks.map((mark) => (
                  <span key={`${mark.position}-${mark.label}`} style={{ left: `${mark.position}%` }}>{mark.label}</span>
                ))}
              </div>
            </div>
            <span>{ui('Duration')}</span>
          </div>

          <div className="trace-waterfall-rows">
            {visibleSteps.map((step) => {
              const presentation = getStepPresentation(step)
              const Icon = presentation.Icon
              const left = `${(step.startMs / timelineDuration) * 100}%`
              const width = `${Math.max(2.2, (step.durationMs / timelineDuration) * 100)}%`
              const isExpanded = expandedStepIds.has(step.id)

              return (
                <button
                  aria-label={`${ui('Select')} ${step.name}`}
                  className={`trace-step-row${selectedStepId === step.id ? ' is-selected' : ''}`}
                  key={step.id}
                  onClick={() => onStepSelect(step.id)}
                  type="button"
                >
                  <span className="trace-step-number">{step.index}</span>
                  <span className={`trace-step-type trace-step-type-${presentation.key}`} title={`${presentation.label} · ${step.source}`}>
                    <Icon size={14} strokeWidth={1.9} />
                    <span>{ui(presentation.label)}</span>
                  </span>
                  <span className="trace-step-name" style={{ paddingLeft: `${8 + step.depth * 18}px` }}>
                    {step.expandable ? (
                      <span
                        aria-label={isExpanded ? `Collapse ${step.name}` : `Expand ${step.name}`}
                        className="trace-step-toggle"
                        onClick={(event) => {
                          event.stopPropagation()
                          onToggleStep(step.id)
                        }}
                        onKeyDown={(event) => {
                          if (event.key !== 'Enter' && event.key !== ' ') return
                          event.preventDefault()
                          event.stopPropagation()
                          onToggleStep(step.id)
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        {isExpanded ? <ChevronDown size={14} strokeWidth={1.8} /> : <ChevronRight size={14} strokeWidth={1.8} />}
                      </span>
                    ) : (
                      <span className="trace-step-toggle-spacer" />
                    )}
                    <strong>{step.name}</strong>
                  </span>
                  <span className="trace-waterfall-track">
                    <span
                      aria-hidden="true"
                      className={`trace-waterfall-bar trace-waterfall-bar-${presentation.key}${step.kind === 'AGENT' ? ' is-root' : ''}`}
                      style={{ left, width }}
                    />
                  </span>
                  <span className="trace-step-duration">{formatDuration(step.durationMs)}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <footer className="trace-waterfall-footer">
        <span><Info size={14} strokeWidth={1.8} /> {ui('Click a step in the waterfall to view details.')}</span>
        <strong>{ui('Total Duration')}: {trace.durationLabel}</strong>
      </footer>
    </section>
  )
}
