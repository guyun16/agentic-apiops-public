import { Check, Clipboard, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatMetadataJson, formatMetadataValue, type ApiMetadataDetail, type ExpectedResponse } from '../types'

type EndpointHeaderProps = {
  detail: ApiMetadataDetail
  expectedResponse: ExpectedResponse | null
  selectedStrategy: string | null
}

export function EndpointHeader({ detail, expectedResponse, selectedStrategy }: EndpointHeaderProps) {
  const { ui } = useConsoleLanguage()
  const [isQuickExampleOpen, setIsQuickExampleOpen] = useState(false)
  const methodClass = detail.method.toLowerCase().replace(/[^a-z0-9_-]/g, '-')
  const requestExample = detail.examples.find((example) => example.owner?.type === 'REQUEST_SCHEMA')?.value ?? null
  const tags = formatMetadataValue(detail.tags)
  const security = formatMetadataValue(detail.security)

  return (
    <>
      <section className="endpoint-header" aria-labelledby="selected-endpoint-title">
        <div className="endpoint-header-main">
          <div className="endpoint-route-line">
            <span className={`method-badge studio-method method-${methodClass}`}>{detail.method}</span>
            <h2 id="selected-endpoint-title">{detail.path}</h2>
          </div>
          <span className="endpoint-operation">operationId: {detail.operationId || '—'}</span>
          <strong className="endpoint-summary-title">{detail.summary || ui('Untitled endpoint')}</strong>
          <p className="endpoint-description">{detail.description || ui('No description is documented for this endpoint.')}</p>
          <div className="endpoint-contract-meta">
            <span><b>{ui('Security')}</b> {security}</span>
            <span><b>{ui('Tags')}</b> {tags}</span>
          </div>
        </div>
        <button className="quick-example-button" onClick={() => setIsQuickExampleOpen(true)} type="button">
          {ui('Quick Example')}
        </button>
      </section>

      {isQuickExampleOpen ? (
        <QuickExampleDialog
          expectedResponse={expectedResponse}
          onClose={() => setIsQuickExampleOpen(false)}
          requestExample={requestExample}
          selectedStrategy={selectedStrategy}
        />
      ) : null}
    </>
  )
}

function QuickExampleDialog({ expectedResponse, onClose, requestExample, selectedStrategy }: { expectedResponse: ExpectedResponse | null; onClose: () => void; requestExample: unknown | null; selectedStrategy: string | null }) {
  const { ui } = useConsoleLanguage()

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div className="quick-example-backdrop" onMouseDown={onClose} role="presentation">
      <div aria-labelledby="quick-example-title" aria-modal="true" className="quick-example-dialog" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <header className="quick-example-dialog-header">
          <div>
            <span className="studio-eyebrow">{ui('Endpoint example')}</span>
            <h2 id="quick-example-title">{ui('Quick Example')}</h2>
          </div>
          <button aria-label={ui('Close')} className="studio-icon-button" onClick={onClose} title={ui('Close')} type="button">
            <X size={16} strokeWidth={1.8} />
          </button>
        </header>

        <div className="quick-example-content">
          <ExampleBlock label={ui('Request Example')} value={requestExample} emptyLabel={ui('No request example is documented.')} />
          <div className="quick-example-divider" aria-hidden="true" />
          <div className="quick-example-response-heading">
            <span>{ui('Expected Response Example')}</span>
            <strong>{selectedStrategy ?? ui('No applicable strategy selected')}</strong>
          </div>
          <ExampleBlock
            label={`${expectedResponse?.statusCode ?? '—'} · ${expectedResponse?.mediaType ?? ui('Response')}`}
            value={expectedResponse?.example ?? null}
            emptyLabel={expectedResponse ? ui('No response example is documented.') : ui('No Expected Response is available for this strategy.')}
          />
          {expectedResponse?.description && <p className="quick-example-description">{expectedResponse.description}</p>}
          {!expectedResponse && <p className="quick-example-description">{ui('Select an applicable strategy with documented response evidence.')}</p>}
        </div>
      </div>
    </div>
  )
}

function ExampleBlock({ emptyLabel, label, value }: { emptyLabel: string; label: string; value: unknown | null }) {
  const { ui } = useConsoleLanguage()
  const [copied, setCopied] = useState(false)
  const formattedValue = value === null || value === undefined ? '' : formatMetadataJson(value)

  const copy = async () => {
    if (!formattedValue) return
    try {
      await navigator.clipboard?.writeText(formattedValue)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className="quick-example-block">
      <div className="quick-example-block-heading">
        <span>{label}</span>
        <button className="panel-action quick-example-copy" disabled={!formattedValue} onClick={copy} type="button">
          {copied ? <Check size={13} strokeWidth={1.8} /> : <Clipboard size={13} strokeWidth={1.8} />}
          {copied ? ui('Copied') : ui('Copy')}
        </button>
      </div>
      {formattedValue ? <pre className="code-block quick-example-code"><code>{formattedValue}</code></pre> : <p className="quick-example-empty">{emptyLabel}</p>}
    </section>
  )
}
