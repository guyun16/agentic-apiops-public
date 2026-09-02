import { FileOutput } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatDuration } from '../presentation'
import type { TestReportStep } from '../types'

export function RunResponse({ steps }: { steps: TestReportStep[] }) {
  const { t, ui } = useConsoleLanguage()
  const responseSteps = steps.filter((step) => step.responseStatusCode !== null && step.responseStatusCode !== undefined)

  return (
    <section className="run-tab-panel" aria-labelledby="run-response-title">
      <div className="run-tab-panel-heading">
        <div>
          <h3 id="run-response-title">{ui('Response')}</h3>
          <p>{t('runs.noResponseSnapshot')}</p>
        </div>
        <FileOutput size={18} strokeWidth={1.8} />
      </div>
      {responseSteps.length ? (
        <div className="response-list">
          {responseSteps.map((step) => (
            <div className="response-overview-row" key={step.stepId}>
              <span className="response-http-status">HTTP {step.responseStatusCode}</span>
              <strong>{step.stepId}</strong>
              <span>{formatDuration(step.durationMs)}</span>
            </div>
          ))}
        </div>
      ) : (
        <pre className="runs-code-viewer">{t('runs.noResponseFacts')}</pre>
      )}
    </section>
  )
}
