import { useEffect, useState } from 'react'
import { fetchJavaHealth, fetchPythonHealth } from '../overview/overview-api'
import type { HealthStatus } from '../overview/types'
import { Braces, Building2, Check, Code2, Copy, Info, Link2, Moon, Palette, Stethoscope, Sun } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ThemePreference } from '../../app/App'
import { useConsoleLanguage, type ConsoleLanguage } from '../../app/ConsoleLanguage'
import { useProject } from '../../app/ProjectContext'
import { PageHeader } from '../../components/layout/PageHeader'

type SettingsPageProps = {
  autoDiagnose: boolean
  compactDensity: boolean
  onAutoDiagnoseChange: (enabled: boolean) => void
  onCompactDensityChange: (enabled: boolean) => void
  onReducedMotionChange: (enabled: boolean) => void
  themePreference: ThemePreference
  onThemePreferenceChange: (preference: ThemePreference) => void
  reducedMotion: boolean
}

const themeOptions: Array<{ id: ThemePreference; labelKey: string; icon: LucideIcon }> = [
  { id: 'system', labelKey: 'settings.system', icon: Palette },
  { id: 'light', labelKey: 'settings.light', icon: Sun },
  { id: 'dark', labelKey: 'settings.dark', icon: Moon },
]

const languageOptions: Array<{ id: ConsoleLanguage; labelKey: string }> = [
  { id: 'zh-CN', labelKey: 'settings.chinese' },
  { id: 'en', labelKey: 'settings.english' },
]

const connections: Array<{ nameKey: string; descriptionKey: string; icon: LucideIcon }> = [
  { nameKey: 'settings.javaPlatform', descriptionKey: 'settings.javaDescription', icon: Braces },
  { nameKey: 'settings.pythonAgentLab', descriptionKey: 'settings.pythonDescription', icon: Code2 },
]

function SettingsToggle({ checked, label, onChange, disabled = false }: { checked: boolean; label: string; onChange: () => void; disabled?: boolean }) {
  return (
    <div className="settings-toggle-control">
      <button
        disabled={disabled}
        aria-checked={checked}
        aria-label={label}
        className={`settings-toggle${checked ? ' is-on' : ''}`}
        onClick={onChange}
        onKeyDown={(event) => {
          if (event.key === ' ' || event.key === 'Enter') {
            event.preventDefault()
            onChange()
          }
        }}
        role="switch"
        type="button"
      >
        <span className="settings-toggle-thumb" />
      </button>
    </div>
  )
}

function PanelHeading({ icon: Icon, id, title }: { icon: LucideIcon; id: string; title: string }) {
  return (
    <div className="settings-panel-heading">
      <span className="settings-panel-icon"><Icon size={19} strokeWidth={1.8} /></span>
      <h2 id={id}>{title}</h2>
    </div>
  )
}

export function SettingsPage({
  autoDiagnose,
  compactDensity,
  onAutoDiagnoseChange,
  onCompactDensityChange,
  onReducedMotionChange,
  onThemePreferenceChange,
  reducedMotion,
  themePreference,
}: SettingsPageProps) {
  const { language, setLanguage, t, ui } = useConsoleLanguage()
  const { currentProject } = useProject()
  const [health, setHealth] = useState<HealthStatus[]>(['UNKNOWN', 'UNKNOWN'])
  const [refresh, setRefresh] = useState(0)
  const [copyStatus, setCopyStatus] = useState('')
  const baseUrl = new URL(import.meta.env.VITE_API_BASE_URL || '/', window.location.origin).href
  useEffect(() => {
    const controller = new AbortController()
    setHealth(['UNKNOWN', 'UNKNOWN'])
    void Promise.allSettled([fetchJavaHealth(controller.signal), fetchPythonHealth(controller.signal)]).then(results => {
      if (!controller.signal.aborted) setHealth(results.map(result => result.status === 'fulfilled' ? result.value.status : 'UNKNOWN'))
    })
    return () => controller.abort()
  }, [refresh])
  const copyUrl = async () => {
    try { await navigator.clipboard.writeText(baseUrl); setCopyStatus(language === 'zh-CN' ? '已复制' : 'Copied') }
    catch { setCopyStatus(language === 'zh-CN' ? '复制失败，请手动复制地址' : 'Copy failed; copy the address manually') }
  }

  return (
    <section className="settings-page" aria-label={t('page.settings.title')}>
      <PageHeader
        description={t('page.settings.description')}
        title={t('page.settings.title')}
      />

      <p role="status">{copyStatus}</p>
      <div className="settings-grid">
        <section className="settings-card panel" aria-labelledby="settings-project-title">
          <PanelHeading icon={Building2} id="settings-project-title" title={t('settings.projectEnvironment')} />
          <div className="settings-card-body">
            <div className="settings-field-grid">
              <div className="settings-field">
                <span>{t('settings.project')}</span>
                <div className="settings-control settings-select" aria-label={t('settings.project')}>
                  <strong>{currentProject ? currentProject.projectName : t('project.noProjectSelected')}</strong>

                </div>
              </div>
              <div className="settings-field">
                <span>{t('settings.environment')}</span>
                <div className="settings-control settings-select" aria-label={t('settings.environment')}>
                  <strong>{window.location.hostname}</strong>

                </div>
              </div>
            </div>
            <div className="settings-field settings-url-field">
              <span>{t('settings.apiBaseUrl')}</span>
              <div className="settings-control settings-url-control">
                <code>{baseUrl}</code>
                <button
                  aria-label={language === 'zh-CN' ? '复制 API 基础 URL' : 'Copy API Base URL'}
                  onClick={() => { void copyUrl() }}
                  className="settings-copy-button"
                  title={language === 'zh-CN' ? '复制 API 基础 URL' : 'Copy API Base URL'}
                  type="button"
                >
                  <Copy size={16} strokeWidth={1.8} />
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="settings-card panel" aria-labelledby="settings-connections-title">
          <PanelHeading icon={Link2} id="settings-connections-title" title={t('settings.platformConnections')} />
          <div className="settings-card-body">
            <div className="settings-connection-list">
              {connections.map(({ descriptionKey, icon: Icon, nameKey }, index) => (
                <article className="settings-connection" key={nameKey}>
                  <span className="settings-connection-icon"><Icon size={19} strokeWidth={1.8} /></span>
                  <div className="settings-connection-copy">
                    <strong>{t(nameKey)}</strong>
                    <p>{t(descriptionKey)}</p>
                  </div>
                  <span className="settings-status">{health[index]}</span>
                  <button className="settings-manage-button" onClick={() => setRefresh(value => value + 1)} type="button">{ui('Refresh')}</button>
                </article>
              ))}
            </div>
            <p className="settings-muted-note"><Info size={15} strokeWidth={1.8} />{language === 'zh-CN' ? '状态来自服务健康检查；UNKNOWN 表示无法确认。' : 'Live service health; UNKNOWN means health could not be confirmed.'}</p>
          </div>
        </section>

        <section className="settings-card panel" aria-labelledby="settings-appearance-title">
          <PanelHeading icon={Palette} id="settings-appearance-title" title={t('settings.appearance')} />
          <div className="settings-card-body">
            <div className="settings-choice-grid">
              <div className="settings-choice-group">
                <span className="settings-choice-label">{t('settings.theme')}</span>
                <div className="settings-segmented settings-theme-options" role="group" aria-label={t('settings.theme')}>
                  {themeOptions.map(({ icon: Icon, id, labelKey }) => (
                    <button
                      aria-pressed={themePreference === id}
                      className={themePreference === id ? 'is-active' : ''}
                      key={id}
                      onClick={() => onThemePreferenceChange(id)}
                      type="button"
                    >
                      <Icon size={15} strokeWidth={1.8} />
                      {t(labelKey)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="settings-choice-group">
                <span className="settings-choice-label">{t('settings.language')}</span>
                <div className="settings-segmented settings-language-options" role="group" aria-label={t('settings.language')}>
                  {languageOptions.map(({ id, labelKey }) => (
                    <button
                      aria-pressed={language === id}
                      className={language === id ? 'is-active' : ''}
                      key={id}
                      onClick={() => setLanguage(id)}
                      type="button"
                    >
                      {t(labelKey)}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="settings-toggle-list">
              <div className="settings-toggle-row">
                <div>
                  <strong>{t('settings.compactDensity')}</strong>
                  <span>{t('settings.compactDensityDescription')}</span>
                </div>
                <SettingsToggle checked={compactDensity} label={t('settings.compactDensity')} onChange={() => onCompactDensityChange(!compactDensity)} />
              </div>
              <div className="settings-toggle-row">
                <div>
                  <strong>{t('settings.reducedMotion')}</strong>
                  <span>{t('settings.reducedMotionDescription')}</span>
                </div>
                <SettingsToggle checked={reducedMotion} label={t('settings.reducedMotion')} onChange={() => onReducedMotionChange(!reducedMotion)} />
              </div>
            </div>
          </div>
        </section>

        <section className="settings-card panel" aria-labelledby="settings-diagnosis-title">
          <PanelHeading icon={Stethoscope} id="settings-diagnosis-title" title={t('settings.diagnosisPreference')} />
          <div className="settings-card-body settings-preference-body">
            <div className="settings-preference-row">
              <div className="settings-preference-icon"><Check size={18} strokeWidth={1.8} /></div>
              <div className="settings-preference-copy">
                <strong>{t('settings.autoDiagnose')}</strong>
                <p>{language === 'zh-CN' ? '暂未接入自动触发，请从运行记录手动启动诊断。' : 'Automatic triggering is not available; start diagnosis from Runs.'}</p>
              </div>
              <SettingsToggle disabled checked={false} label={t('settings.autoDiagnose')} onChange={() => onAutoDiagnoseChange(!autoDiagnose)} />
            </div>
            <div className="settings-preference-note">
              <Info size={15} strokeWidth={1.8} />
              <span>{language === 'zh-CN' ? '此功能当前不可用。' : 'This feature is currently unavailable.'}</span>
            </div>
          </div>
        </section>
      </div>

      <div className="settings-info-bar">
        <Info size={20} strokeWidth={1.8} />
        <div>
          <strong>{t('settings.languageNote')}</strong>
          <span>{t('settings.languageNoteDetail')}</span>
        </div>
      </div>
    </section>
  )
}
