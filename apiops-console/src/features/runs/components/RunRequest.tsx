import { FileText } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { TestReportStep } from '../types'
import { HttpSnapshotBody } from './HttpSnapshotBody'

export function RunRequest({ step }: { step?: TestReportStep }) {
  const { t, ui } = useConsoleLanguage()
  const snapshot = step?.httpExchange?.request

  return (
    <section className="run-tab-panel" aria-label={ui('Request')}>
      <div className="run-tab-panel-heading">
        <div>
          <h3>{ui('Request')}</h3>
          {!snapshot ? <p>{t('runs.noRequestSnapshot')}</p> : null}
        </div>
        <FileText size={18} strokeWidth={1.8} />
      </div>
      {snapshot ? <>
        <pre className="runs-code-viewer">{snapshot.method} {snapshot.url}</pre>
        <HttpSnapshotBody snapshot={snapshot} />
      </> : <pre className="runs-code-viewer">{t('runs.noRequestSnapshot')}</pre>}
    </section>
  )
}
