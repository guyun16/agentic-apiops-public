import { Braces, Check, Code2 } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { DiagnosisExecutionResponse } from '../../diagnosis/types'

export type DiagnosisRuntime = 'JAVA_PLATFORM' | 'PYTHON_AGENTLAB'

type DiagnosisRuntimeSelectorProps = {
  runtime: DiagnosisRuntime
  execution: DiagnosisExecutionResponse | null
  onChange: (runtime: DiagnosisRuntime) => void
}

export function DiagnosisRuntimeSelector({ execution, onChange, runtime }: DiagnosisRuntimeSelectorProps) {
  const { ui } = useConsoleLanguage()
  const pythonSelected = runtime === 'PYTHON_AGENTLAB'

  return (
    <section className="diagnosis-runtime-selector" aria-labelledby="diagnosis-runtime-title">
      <header className="diagnosis-runtime-selector-header">
        <span>{ui('Select Runtime')}</span>
        <h3 id="diagnosis-runtime-title">{pythonSelected ? ui('Python AgentLab') : ui('Java Platform')}</h3>
      </header>
      <div className="diagnosis-runtime-options" role="radiogroup" aria-label={ui('Select Runtime')}>
        <button
          aria-pressed={runtime === 'JAVA_PLATFORM'}
          className={`diagnosis-runtime-option${runtime === 'JAVA_PLATFORM' ? ' is-selected' : ''}`}
          onClick={() => onChange('JAVA_PLATFORM')}
          type="button"
        >
          <span className="diagnosis-runtime-icon"><Code2 size={21} strokeWidth={1.7} /></span>
          <span className="diagnosis-runtime-copy">
            <strong>{ui('Java Platform')}</strong>
            <small>Spring AI Diagnosis Agent</small>
            <small className="diagnosis-runtime-unavailable">{ui('Browser execution not wired')}</small>
          </span>
          <span className="diagnosis-runtime-unwired">{ui('Not wired')}</span>
          <span className="diagnosis-runtime-radio" aria-hidden="true">{runtime === 'JAVA_PLATFORM' ? <Check size={13} strokeWidth={2.2} /> : null}</span>
        </button>

        <button
          aria-pressed={runtime === 'PYTHON_AGENTLAB'}
          className={`diagnosis-runtime-option${runtime === 'PYTHON_AGENTLAB' ? ' is-selected' : ''}`}
          onClick={() => onChange('PYTHON_AGENTLAB')}
          type="button"
        >
          <span className="diagnosis-runtime-icon"><Braces size={21} strokeWidth={1.7} /></span>
          <span className="diagnosis-runtime-copy">
            <strong>{ui('Python AgentLab')}</strong>
            <small>{execution ? `${execution.workflow} · ${execution.model}` : ui('Real workflow · metadata appears after start')}</small>
          </span>
          <span className="diagnosis-runtime-recommended">{ui('Real')}</span>
          <span className="diagnosis-runtime-radio" aria-hidden="true">{runtime === 'PYTHON_AGENTLAB' ? <Check size={13} strokeWidth={2.2} /> : null}</span>
        </button>
      </div>
      {pythonSelected && execution ? (
        <div className="diagnosis-runtime-metadata">
          <div><span>{ui('Provider')}</span><strong>{execution.provider}</strong></div>
          <div><span>{ui('Workflow')}</span><strong>{execution.workflow}</strong></div>
          <div><span>{ui('Implementation')}</span><strong>{execution.implementation}</strong></div>
        </div>
      ) : null}
    </section>
  )
}
