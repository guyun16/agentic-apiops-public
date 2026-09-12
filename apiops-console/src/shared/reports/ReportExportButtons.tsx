import { Download } from 'lucide-react'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { downloadReport, type ReportExport } from './reportExport'

export function ReportExportButtons({ document }: { document: ReportExport }) {
  const { language } = useConsoleLanguage()
  return <>
    {(['md', 'json'] as const).map((format) => <button className="panel-action" key={format} type="button"
      onClick={() => downloadReport({ ...document, exportedAt: new Date().toISOString() }, format, language)}>
      <Download size={14} strokeWidth={1.8} />
      {language === 'zh-CN' ? '导出' : 'Export'} {format === 'md' ? 'Markdown' : 'JSON'}
    </button>)}
  </>
}
