import { FileOutput } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatDuration } from '../presentation'
import type { TestReportStep } from '../types'
import { HttpSnapshotBody } from './HttpSnapshotBody'

export function RunResponse({ steps }: { steps: TestReportStep[] }) {
  const { t, ui } = useConsoleLanguage()
  const responseSteps = steps.filter((step) => step.responseStatusCode !== null && step.responseStatusCode !== undefined)

  return (
    <section className="run-tab-panel" aria-label={ui('Response')}>
      <div className="run-tab-panel-heading">
        <div>
          <h3>{ui('Response')}</h3>
          {!steps.some((step) => step.httpExchange?.response) ? <p>{t('runs.noResponseSnapshot')}</p> : null}
        </div>
        <FileOutput size={18} strokeWidth={1.8} />
      </div>
      {responseSteps.length ? (
        <div className="response-list">
          {responseSteps.map((step, index) => (
            <div key={`${step.stepId}-${index}`}>
            <div className="response-overview-row">
              <span className="response-http-status">HTTP {step.responseStatusCode}</span>
              <strong>{step.stepId}</strong>
              <span>{formatDuration(step.durationMs)}</span>
            </div>
            {step.httpExchange?.response ? <HttpSnapshotBody snapshot={step.httpExchange.response} /> : null}
            </div>
          ))}
        </div>
      ) : (
        <pre className="runs-code-viewer">{t('runs.noResponseFacts')}</pre>
      )}
    </section>
  )
}
