import { FileText } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'

export function RunRequest() {
  const { t, ui } = useConsoleLanguage()

  return (
    <section className="run-tab-panel" aria-labelledby="run-request-title">
      <div className="run-tab-panel-heading">
        <div>
          <h3 id="run-request-title">{ui('Request')}</h3>
          <p>{t('runs.noRequestSnapshot')}</p>
        </div>
        <FileText size={18} strokeWidth={1.8} />
      </div>
      <pre className="runs-code-viewer">{t('runs.noRequestSnapshot')}</pre>
    </section>
  )
}
