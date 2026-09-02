import { useEffect, useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { formatMetadataJson, formatMetadataValue, type ApiMetadataDetail, type ExpectedResponse } from '../types'
import { ResponseList } from './ResponseList'

type StudioTab = 'Overview' | 'Parameters' | 'Request Body' | 'Responses' | 'Security'
const tabs: StudioTab[] = ['Overview', 'Parameters', 'Request Body', 'Responses', 'Security']

type RequestResponsePanelProps = {
  detail: ApiMetadataDetail
  expectedResponse: ExpectedResponse | null
  selectedStrategy: string | null
}

export function RequestResponsePanel({ detail, expectedResponse, selectedStrategy }: RequestResponsePanelProps) {
  const { ui } = useConsoleLanguage()
  const [activeTab, setActiveTab] = useState<StudioTab>('Responses')

  useEffect(() => {
    setActiveTab('Responses')
  }, [selectedStrategy])

  return (
    <section className="request-panel" aria-label={ui('Endpoint contract details')}>
      <div className="studio-tabs" role="tablist" aria-label={ui('Endpoint detail tabs')}>
        {tabs.map((tab) => (
          <button
            aria-selected={activeTab === tab}
            className={`studio-tab${activeTab === tab ? ' is-active' : ''}`}
            key={tab}
            onClick={() => setActiveTab(tab)}
            role="tab"
            type="button"
          >
            {ui(tab)}
          </button>
        ))}
      </div>

      {activeTab === 'Overview' && <OverviewTab detail={detail} />}
      {activeTab === 'Parameters' && <ParametersTab detail={detail} />}
      {activeTab === 'Request Body' && <RequestBodyTab detail={detail} />}
      {activeTab === 'Responses' && <ResponseList expectedResponse={expectedResponse} strategy={selectedStrategy} />}
      {activeTab === 'Security' && <SecurityTab detail={detail} />}
    </section>
  )
}

function OverviewTab({ detail }: { detail: ApiMetadataDetail }) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="endpoint-overview-content">
      <div className="endpoint-overview-lede">
        <span className="studio-eyebrow">{ui('What this endpoint does')}</span>
        <p>{detail.description || detail.summary || ui('No description is documented for this endpoint.')}</p>
      </div>
      <dl className="endpoint-fact-grid">
        <Fact label={ui('OperationId')} value={detail.operationId || '—'} />
        <Fact label={ui('Method')} value={detail.method} />
        <Fact label={ui('Path')} value={detail.path} />
        <Fact label={ui('Tags')} value={formatMetadataValue(detail.tags)} />
      </dl>
    </div>
  )
}

function ParametersTab({ detail }: { detail: ApiMetadataDetail }) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="metadata-detail-content">
      {detail.parameters.length > 0 ? (
        <div className="parameter-list">
          {detail.parameters.map((parameter) => (
            <div className="parameter-row" key={`${parameter.location}-${parameter.name}`}>
              <div className="parameter-heading">
                <strong>{parameter.name}</strong>
                <span className="metadata-chip">{parameter.location}</span>
                {parameter.required && <span className="required-chip">{ui('Required')}</span>}
              </div>
              <span>{parameter.description || ui('No description documented.')}</span>
              <pre className="code-block inline-code"><code>{formatMetadataJson(parameter.schema)}</code></pre>
              <small>{ui('Example')}: {formatMetadataValue(parameter.example)}</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="studio-empty-state compact-empty-state">
          <strong>{ui('Parameters')}</strong>
          <span>{ui('No parameters are defined for this operation.')}</span>
        </div>
      )}
    </div>
  )
}

function RequestBodyTab({ detail }: { detail: ApiMetadataDetail }) {
  const { ui } = useConsoleLanguage()
  return (
    <div className="request-body-content">
      {detail.requestSchemas.length > 0 ? (
        <div className="contract-preview-grid">
          {detail.requestSchemas.map((requestSchema, index) => (
            <ContractPreview
              key={`${requestSchema.mediaType}-${index}`}
              label={`${ui('Schema')} · ${requestSchema.mediaType}${requestSchema.required ? ` · ${ui('Required')}` : ''}`}
              value={formatMetadataJson(requestSchema.schema)}
            />
          ))}
        </div>
      ) : (
        <div className="studio-empty-state compact-empty-state">
          <strong>{ui('Request Body')}</strong>
          <span>{ui('No request schema is defined for this operation.')}</span>
        </div>
      )}
    </div>
  )
}

function SecurityTab({ detail }: { detail: ApiMetadataDetail }) {
  const { ui } = useConsoleLanguage()
  const security = detail.security === null || detail.security === undefined
    ? null
    : formatMetadataJson(detail.security)
  const hasSecurity = Array.isArray(detail.security)
    ? detail.security.some((item) => typeof item === 'object' && item !== null && Object.keys(item).length > 0)
    : detail.security !== null && detail.security !== undefined

  return (
    <div className="security-tab-content">
      <div className="security-summary">
        <span className="studio-eyebrow">{ui('Security Contract')}</span>
        <strong>{hasSecurity ? ui('Declared security requirement') : ui('No security requirement documented.')}</strong>
      </div>
      {hasSecurity && security && <pre className="code-block security-code"><code>{security}</code></pre>}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

function ContractPreview({ label, value }: { label: string; value: string }) {
  return (
    <div className="contract-preview">
      <div className="contract-preview-heading"><span>{label}</span></div>
      <pre className="code-block contract-code"><code>{value}</code></pre>
    </div>
  )
}
