import { Info } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatMetadataJson, type ExpectedResponse } from '../types'

type ResponseListProps = {
  expectedResponse: ExpectedResponse | null
  strategy: string | null
}

export function ResponseList({ expectedResponse, strategy }: ResponseListProps) {
  const { ui } = useConsoleLanguage()
  const responseTone = getResponseTone(expectedResponse?.statusCode)

  return (
    <div className="response-tab-content">
      <div className="response-tab-heading">
        <div>
          <span className="studio-eyebrow">{ui('Expected Response')}</span>
          <h3>{strategy ?? ui('No applicable strategy selected')}</h3>
          <small>{ui('Expected contract from metadata; not a Runner response.')}</small>
        </div>
        <Info size={15} strokeWidth={1.8} />
      </div>

      {expectedResponse ? (
        <article className="expected-response-card">
          <div className="expected-response-status-row">
            <div className="expected-response-status">
              <span className="expected-response-status-label">{ui('Expected HTTP Status')}</span>
              <span className={`response-status response-${responseTone}`}>{expectedResponse.statusCode}</span>
            </div>
            <div>
              <strong>{expectedResponse.description || ui('Documented response')}</strong>
              <small>{expectedResponse.mediaType || ui('No media type documented')}</small>
            </div>
          </div>

          <div className="expected-response-reason">
            <strong>{ui('Why this response?')}</strong>
            <p>{ui(expectedResponse.why)}</p>
          </div>

          {expectedResponse.schema !== null && expectedResponse.schema !== undefined ? (
            <div className="expected-response-contract">
              <span>{ui('Response schema')}</span>
              <pre className="code-block response-code"><code>{formatMetadataJson(expectedResponse.schema)}</code></pre>
            </div>
          ) : null}

          {expectedResponse.example !== null && expectedResponse.example !== undefined ? (
            <div className="expected-response-contract">
              <span>{ui('Response example')}</span>
              <pre className="code-block response-code"><code>{formatMetadataJson(expectedResponse.example)}</code></pre>
            </div>
          ) : (
            <p className="expected-response-empty">{ui('No response example is documented.')}</p>
          )}
        </article>
      ) : (
        <div className="studio-empty-state compact-empty-state">
          <strong>{ui('Expected Response unavailable')}</strong>
          <span>{ui('This strategy has no documented response evidence for the selected endpoint.')}</span>
        </div>
      )}
    </div>
  )
}

function getResponseTone(statusCode: string | undefined): 'success' | 'warning' | 'danger' | 'neutral' {
  const status = Number(statusCode)
  if (status >= 200 && status < 300) return 'success'
  if (status >= 400) return 'danger'
  if (status >= 300) return 'warning'
  return 'neutral'
}
