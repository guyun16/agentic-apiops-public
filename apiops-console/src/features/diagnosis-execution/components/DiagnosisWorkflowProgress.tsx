import { Check, Circle, CircleX, Clock3 } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { DiagnosisExecutionStep } from '../types'
import type { DiagnosisRuntime } from './DiagnosisRuntimeSelector'

type DiagnosisWorkflowProgressProps = {
  steps: DiagnosisExecutionStep[]
  runtime: DiagnosisRuntime
  runtimeLabel?: string
}

function StepIcon({ state }: { state: DiagnosisExecutionStep['state'] }) {
  if (state === 'COMPLETED') return <Check size={15} strokeWidth={2.3} />
  if (state === 'REJECTED') return <CircleX size={15} strokeWidth={2} />
  if (state === 'ACTIVE') return <Clock3 size={15} strokeWidth={2} />
  return <Circle size={15} strokeWidth={1.8} />
}

export function DiagnosisWorkflowProgress({ runtime, steps, runtimeLabel }: DiagnosisWorkflowProgressProps) {
  const { ui } = useConsoleLanguage()

  if (runtime === 'JAVA_PLATFORM') {
    return (
      <section className="diagnosis-execution-panel diagnosis-workflow-panel diagnosis-availability-panel panel is-unavailable" aria-disabled="true" aria-labelledby="workflow-progress-title">
        <header className="diagnosis-execution-panel-header">
          <span className="diagnosis-execution-eyebrow">5. {ui('Workflow Progress')}</span>
          <h2 id="workflow-progress-title">{ui('Workflow Progress')}</h2>
          <small className="diagnosis-control-runtime">{ui('Python AgentLab only')}</small>
        </header>
        <div className="diagnosis-execution-status-row">
          <Circle size={18} strokeWidth={1.8} />
          <span>{ui('Availability')}</span>
          <strong className="diagnosis-execution-status diagnosis-execution-status-unavailable">{ui('Unavailable')}</strong>
        </div>
        <div className="diagnosis-execution-unavailable">
          <strong>{ui('Unavailable for Java Platform')}</strong>
          <span>{ui('Python AgentLab only')}</span>
        </div>
      </section>
    )
  }

  return (
    <section className="diagnosis-execution-panel diagnosis-workflow-panel panel" aria-labelledby="workflow-progress-title">
      <header className="diagnosis-execution-panel-header">
        <span className="diagnosis-execution-eyebrow">5. {ui('Workflow Progress')}</span>
        <h2 id="workflow-progress-title">{ui('Workflow Progress')}</h2>
        {runtimeLabel ? <small className="diagnosis-workflow-runtime">{runtimeLabel}</small> : null}
      </header>
      {steps.length ? (
        <ol className="diagnosis-workflow-list">
          {steps.map((step, index) => (
            <li className={`diagnosis-workflow-step is-${step.state.toLowerCase()}`} key={step.id}>
              <span className="diagnosis-workflow-marker"><StepIcon state={step.state} /></span>
              <span className="diagnosis-workflow-line" aria-hidden="true" />
              <span className="diagnosis-workflow-copy">
                <strong>{ui(step.label)}</strong>
                <small>{ui(step.detail)}</small>
              </span>
              <span className="diagnosis-workflow-index">{index + 1}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="diagnosis-workflow-empty">{ui('Workflow steps will appear after Start Diagnosis.')}</p>
      )}
    </section>
  )
}
