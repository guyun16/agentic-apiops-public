import { Bot, Clock3, Server } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatTimestamp } from '../../runs/presentation'
import type { HealthItem } from '../types'

type SystemHealthProps = {
  items: HealthItem[]
  loading: boolean
}

const healthIcons: Record<HealthItem['id'], LucideIcon> = {
  java: Server,
  python: Bot,
}

function displayStatus(item: HealthItem, loading: boolean, ui: (text: string) => string) {
  if (loading && !item.checkedAt) return ui('Checking')
  if (!item.sourceAvailable || item.status === 'DOWN') return ui('Unavailable')
  if (item.status === 'UP') return ui('Healthy')
  if (item.status === 'DEGRADED') return ui('Degraded')
  return ui('Unknown')
}

function statusTone(item: HealthItem, loading: boolean) {
  if (loading && !item.checkedAt) return 'checking'
  if (!item.sourceAvailable || item.status === 'DOWN') return 'unavailable'
  if (item.status === 'UP') return 'healthy'
  if (item.status === 'DEGRADED') return 'degraded'
  return 'unknown'
}

function description(item: HealthItem, loading: boolean, ui: (text: string) => string) {
  if (loading && !item.checkedAt) return ui('Checking service availability...')
  if (!item.sourceAvailable) return ui('The health endpoint could not be reached.')
  if (item.status === 'DOWN') return ui('The health endpoint reported the service as unavailable.')
  if (item.status === 'DEGRADED') return ui('The health endpoint reported a degraded status.')
  if (item.status === 'UP') return ui('The service is available.')
  return ui('The health response did not include a recognized status.')
}

export function SystemHealth({ items, loading }: SystemHealthProps) {
  const { language, ui } = useConsoleLanguage()
  const timestampLocale = language === 'zh-CN' ? 'zh-CN' : 'en-US'

  return (
    <section aria-busy={loading} aria-labelledby="system-health-title" className="overview-status-section">
      <div className="overview-section-heading">
        <h2 id="system-health-title">{ui('System Status')}</h2>
      </div>
      <div className="overview-status-grid">
        {items.map((health) => {
          const Icon = healthIcons[health.id]
          const tone = statusTone(health, loading)
          return (
            <article className="overview-status-card panel" key={health.id}>
              <div className="overview-status-main">
                <span className={`overview-status-icon overview-status-icon-${tone}`}>
                  <Icon size={22} strokeWidth={1.7} />
                </span>
                <div className="overview-status-copy">
                  <div className="overview-status-title">
                    <h3>{ui(health.name)}</h3>
                    <span className={`overview-health-status overview-health-status-${tone}`}>
                      <span className="status-dot" />
                      {displayStatus(health, loading, ui)}
                    </span>
                  </div>
                  <span className="overview-status-authority">
                    {health.id === 'java'
                      ? ui('Execution & Security Authority')
                      : ui('Agent Workflow / Diagnosis / Trace / Evaluation')}
                  </span>
                  <span className="overview-status-description">{description(health, loading, ui)}</span>
                </div>
              </div>
              <footer className="overview-status-footer" title={ui('Observation time recorded by the Console when the health request completed.')}>
                <Clock3 size={14} strokeWidth={1.8} />
                <span>{ui('Console observation')}: {formatTimestamp(health.checkedAt, timestampLocale)}</span>
              </footer>
            </article>
          )
        })}
      </div>
    </section>
  )
}
