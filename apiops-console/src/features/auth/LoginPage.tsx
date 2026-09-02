import { ArrowRight, Bot, Info, LockKeyhole, Mail } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useAuth, type AuthFailureCode } from '../../app/AuthContext'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import type { Theme } from '../../app/App'
import { ThemeToggle } from '../../components/layout/ThemeToggle'

type LoginPageProps = {
  mode: 'login' | 'expired' | 'loading'
  theme: Theme
  onThemeChange: (theme: Theme) => void
}

export function LoginPage({ mode, onThemeChange, theme }: LoginPageProps) {
  const { language, setLanguage, t } = useConsoleLanguage()
  const { signIn, signOut, status } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<AuthFailureCode | ''>('')
  const isSubmitting = status === 'loading'

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')

    if (!username.trim() || !password.trim()) {
      setError('INVALID_CREDENTIALS')
      return
    }

    try {
      const result = await signIn(username, password)
      if (!result.ok) {
        setError(result.reason)
      }
    } catch {
      setError('GENERIC')
    }
  }

  return (
    <div className="login-page">
      <div className="login-grid-art" aria-hidden="true" />
      <header className="login-header">
        <div className="login-brand" aria-label="APIOps">
          <span className="login-brand-mark"><Bot size={22} strokeWidth={1.8} /></span>
          <span>
            <strong>APIOps</strong>
            <small>Agentic API Operations</small>
          </span>
        </div>
        <div className="login-preferences">
          <button
            aria-label={language === 'zh-CN' ? t('auth.languageSwitchToEnglish') : t('auth.languageSwitchToChinese')}
            className="login-language-button"
            onClick={() => setLanguage(language === 'zh-CN' ? 'en' : 'zh-CN')}
            type="button"
          >
            {language === 'zh-CN' ? 'English' : '中文'}
          </button>
          <ThemeToggle theme={theme} onChange={onThemeChange} />
        </div>
      </header>

      <main className="login-main">
        <section className="login-card" aria-labelledby="login-title">
          <div className="login-card-icon" aria-hidden="true">
            {mode === 'expired' ? <LockKeyhole size={26} strokeWidth={1.8} /> : <Bot size={28} strokeWidth={1.8} />}
          </div>

          {mode === 'loading' ? (
            <div className="login-state-content" aria-live="polite">
              <h1 id="login-title">{t('auth.restoringSessionTitle')}</h1>
              <p>{t('auth.restoringSessionDescription')}</p>
            </div>
          ) : mode === 'expired' ? (
            <div className="login-state-content">
              <h1 id="login-title">{t('auth.sessionExpiredTitle')}</h1>
              <p>{t('auth.sessionExpiredDescription')}</p>
              <button className="login-submit" onClick={signOut} type="button">
                {t('auth.signInAgain')}
                <ArrowRight size={18} strokeWidth={1.8} />
              </button>
            </div>
          ) : (
            <>
              <h1 id="login-title">{t('auth.signInTitle')}</h1>
              <p className="login-description">{t('auth.loginDescription')}</p>

              <form aria-busy={isSubmitting} className="login-form" noValidate onSubmit={submit}>
                <label htmlFor="login-username">{t('auth.username')}</label>
                <div className="login-input-wrap">
                  <Mail size={18} strokeWidth={1.8} aria-hidden="true" />
                  <input
                    autoComplete="username"
                    id="login-username"
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder={t('auth.usernamePlaceholder')}
                    type="text"
                    value={username}
                  />
                </div>

                <label htmlFor="login-password">{t('auth.password')}</label>
                <div className="login-input-wrap">
                  <LockKeyhole size={18} strokeWidth={1.8} aria-hidden="true" />
                  <input
                    autoComplete="current-password"
                    id="login-password"
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder={t('auth.passwordPlaceholder')}
                    type="password"
                    value={password}
                  />
                </div>

                {error ? <p className="login-error" role="alert">{error === 'INVALID_CREDENTIALS' ? t('auth.invalidCredentials') : error === 'NETWORK' ? t('auth.networkFailure') : t('auth.genericFailure')}</p> : null}

                <button className="login-submit" disabled={isSubmitting} type="submit">
                  {isSubmitting ? t('auth.signingIn') : t('auth.signIn')}
                  <ArrowRight size={18} strokeWidth={1.8} />
                </button>
              </form>

              <div className="login-demo-note">
                <Info size={17} strokeWidth={1.8} aria-hidden="true" />
                <span>{t('auth.javaAuthNotice')}</span>
              </div>
            </>
          )}
        </section>
      </main>

      <footer className="login-footer">
        <span>{t('auth.internalDeveloperPlatform')}</span>
      </footer>
    </div>
  )
}
