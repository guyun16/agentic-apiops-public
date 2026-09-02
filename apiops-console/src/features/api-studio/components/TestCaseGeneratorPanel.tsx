import { Check, LockKeyhole, PackageCheck, Repeat2, ShieldAlert, Sparkles, TriangleAlert, Zap } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { strategyOptions } from '../mock-data'
import type { StrategyAvailability, StrategyId, TestCaseAgentRuntime } from '../types'

type TestCaseGeneratorPanelProps = {
  selectedAgentRuntime: TestCaseAgentRuntime
  selectedStrategy: StrategyId | null
  isGenerating: boolean
  canGenerate: boolean
  strategyAvailability: Record<StrategyId, StrategyAvailability>
  onRuntimeChange: (runtime: TestCaseAgentRuntime) => void
  onStrategyChange: (strategy: StrategyId) => void
  onGenerate: () => void
}

const strategyIcons = {
  HAPPY_PATH: PackageCheck,
  MISSING_REQUIRED: TriangleAlert,
  BOUNDARY: Zap,
  AUTH_FAILURE: LockKeyhole,
  IDEMPOTENCY: Repeat2,
  BUSINESS_ERROR: ShieldAlert,
} satisfies Record<StrategyId, typeof PackageCheck>

export function TestCaseGeneratorPanel({ selectedAgentRuntime, selectedStrategy, isGenerating, canGenerate, strategyAvailability, onRuntimeChange, onStrategyChange, onGenerate }: TestCaseGeneratorPanelProps) {
  const { ui } = useConsoleLanguage()

  return (
    <section className="generator-panel" aria-labelledby="generator-title">
      <header className="generator-heading">
        <div>
          <span className="studio-eyebrow">{ui('Generate from the selected endpoint')}</span>
          <h2 id="generator-title">{ui('TestCase Workspace')}</h2>
        </div>
        <Sparkles size={16} strokeWidth={1.7} />
      </header>

      <div className="generator-content">
        <div className="generator-config" aria-label={ui('Configuration')}>
          <label className="configuration-field">
            <span>{ui('Environment')}</span>
            <select aria-label={ui('Environment')} className="configuration-select" disabled value="">
              <option value="">{ui('Not configured')}</option>
            </select>
          </label>
          <label className="configuration-field">
            <span>{ui('Generator')}</span>
            <select
              aria-label={ui('Generator')}
              className="configuration-select"
              onChange={(event) => onRuntimeChange(event.target.value as TestCaseAgentRuntime)}
              value={selectedAgentRuntime}
            >
              <option value="JAVA_AGENT">{ui('Java')}</option>
              <option value="PYTHON_AGENTLAB">{ui('Python AgentLab')}</option>
            </select>
          </label>
        </div>

        <div className="generator-label-row strategy-label-row">
          <span>{ui('Strategy')}</span>
          <small>{ui('Available strategies are determined from endpoint metadata.')}</small>
        </div>
        <div className="strategy-grid">
          {strategyOptions.map((option) => {
            const availability = strategyAvailability[option.id]
            const isApplicable = availability?.applicable ?? false
            const StrategyIcon = strategyIcons[option.id]

            return (
              <button
                aria-label={`${option.id}${!isApplicable ? ` · ${ui(availability?.reason ?? 'Metadata evidence is not available.')}` : ''}`}
                aria-pressed={selectedStrategy === option.id}
                className={`strategy-option strategy-${option.id.toLowerCase().replace(/_/g, '-')}${selectedStrategy === option.id ? ' is-selected' : ''}${!isApplicable ? ' is-disabled' : ''}`}
                disabled={!isApplicable}
                key={option.id}
                onClick={() => onStrategyChange(option.id)}
                title={!isApplicable ? ui(availability?.reason ?? 'Metadata evidence is not available.') : undefined}
                type="button"
              >
                <StrategyIcon size={18} strokeWidth={1.8} />
                <span>
                  <strong>{option.id}</strong>
                  <small>{ui(option.label)}</small>
                </span>
                {selectedStrategy === option.id && <Check className="strategy-check" size={14} strokeWidth={2} />}
              </button>
            )
          })}
        </div>

        <button className="generate-button" disabled={isGenerating || !canGenerate} onClick={onGenerate} type="button">
          <Sparkles size={16} strokeWidth={1.8} />
          {isGenerating ? ui('Generating...') : ui('Generate TestCase')}
        </button>
      </div>
    </section>
  )
}
