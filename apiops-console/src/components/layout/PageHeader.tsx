import { useConsoleLanguage } from '../../app/ConsoleLanguage'

type PageHeaderProps = {
  title: string
  description?: string
}

export function PageHeader({ title, description }: PageHeaderProps) {
  const { language, t } = useConsoleLanguage()
  const pageKey = {
    Overview: 'overview',
    'API Studio': 'apiStudio',
    Runs: 'runs',
    'Diagnosis Studio': 'diagnosisStudio',
    Diagnosis: 'diagnosis',
    Traces: 'traces',
    Evaluation: 'evaluation',
    Benchmark: 'benchmark',
    Settings: 'settings',
  }[title]
  const localizedTitle = language === 'en' || !pageKey ? title : t(`page.${pageKey}.title`)
  const localizedDescription = language === 'en' || !pageKey ? description : t(`page.${pageKey}.description`)

  return (
    <header className="page-header">
      <h1>{localizedTitle}</h1>
      {description ? <p>{localizedDescription}</p> : null}
    </header>
  )
}
