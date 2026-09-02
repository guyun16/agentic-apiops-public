import { CheckCircle2, ChevronDown, XCircle } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import {
  buildExecutionAssertionDisplayGroups,
  type ExecutionStepDisplayItem,
} from '../../../shared/presentation/executionStepProjection'
import { formatValue } from '../presentation'
import type { TestReportStep } from '../types'

type StepGroupReference = {
  caseId: string
  item: ExecutionStepDisplayItem<TestReportStep>
}

export function RunAssertions({ stepGroups, available = true }: { stepGroups: readonly StepGroupReference[]; available?: boolean }) {
  const { t, ui } = useConsoleLanguage()
  const assertionGroups = stepGroups.flatMap(({ caseId, item }) => buildExecutionAssertionDisplayGroups(item).map((group) => ({
    caseId,
    group,
    item,
  })))
  const totalAssertions = stepGroups.reduce(
    (total, { item }) => total + item.rawSteps.reduce((stepTotal, step) => stepTotal + step.assertionResults.length, 0),
    0,
  )
  const passed = assertionGroups.reduce(
    (total, { group }) => total + (group.representativeAssertion.passed ? group.count : 0),
    0,
  )

  return (
    <section className="run-assertions-panel" aria-labelledby="run-assertions-title">
      <div className="run-assertions-summary">
        <div>
          <h3 id="run-assertions-title">{ui('Assertions evaluated')}</h3>
          <p>{available ? `${totalAssertions} ${ui('checks ran against the response contract.')}` : t('runs.noAssertions')}</p>
        </div>
        <span className="assertion-count">
          <strong>{passed}</strong> / {totalAssertions} {ui('passed')}
        </span>
      </div>

      <div className="assertions-list">
        {assertionGroups.map(({ caseId, group, item }, index) => {
          const assertion = group.representativeAssertion
          const passedAssertion = assertion.passed
          const StatusIcon = passedAssertion ? CheckCircle2 : XCircle
          const countSuffix = group.count > 1 ? ` ×${group.count}` : ''
          const contextLabel = item.kind === 'repeated'
            ? `${ui('Case')} ${caseId} · ${ui('Repeated executions')} ×${item.count}`
            : `${ui('Case')} ${caseId} · ${ui('Step')} · ${item.representativeStep.stepId}`

          return (
            <article className={`assertion-card ${passedAssertion ? 'is-pass' : 'is-fail'}`} key={`${caseId}-${item.representativeStep.stepId}-${assertion.type}-${index}`}>
              <div className="assertion-card-heading">
                <span className="assertion-status-icon">
                  <StatusIcon size={18} strokeWidth={1.9} />
                </span>
                <div className="assertion-card-title">
                  <span className="assertion-type">{assertion.type}</span>
                  <small className="assertion-card-context">{contextLabel}</small>
                  <h4>{passedAssertion ? ui('Assertion passed') : ui('Assertion failed')}{countSuffix}</h4>
                </div>
                <ChevronDown className="assertion-chevron" size={16} strokeWidth={1.8} />
              </div>
              <div className="assertion-values">
                <div>
                  <span>{ui('Expected')}</span>
                  <strong>{formatValue(assertion.expected)}</strong>
                </div>
                <div>
                  <span>{ui('Actual')}</span>
                  <strong>{formatValue(assertion.actual)}</strong>
                </div>
              </div>
              {assertion.message ? <p className="assertion-details">{assertion.message}</p> : null}
              {group.count > 1 ? (
                <details className="assertion-raw-executions">
                  <summary>{ui('Raw assertions')} ({group.rawAssertions.length})</summary>
                  <div className="assertion-raw-execution-list">
                    {group.rawAssertions.map((rawAssertion) => (
                      <div className="assertion-raw-execution-row" key={`${rawAssertion.step.stepId}-${rawAssertion.executionIndex}-${rawAssertion.assertionIndex}`}>
                        <code>{rawAssertion.step.stepId}</code>
                        <span>{formatValue(rawAssertion.assertion.expected)} → {formatValue(rawAssertion.assertion.actual)}</span>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
            </article>
          )
        })}
      </div>
    </section>
  )
}
