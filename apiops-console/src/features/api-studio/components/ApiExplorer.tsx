import { AlertTriangle, ChevronDown, LoaderCircle, Package, Search, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { ApiError } from '../../../lib/api-client'
import type { ApiDocument, ApiDocumentImportPhase, ApiMetadataSummary, OpenApiImportResponse } from '../types'

type ApiExplorerProps = {
  apiSummaries: ApiMetadataSummary[]
  apiSummariesError: ApiError | null
  apiSummariesState: 'loading' | 'ready' | 'error'
  currentProjectId: string | null
  documents: ApiDocument[]
  documentsError: ApiError | null
  documentsState: 'loading' | 'ready' | 'error'
  selectedApiDocId: string | null
  selectedApiId: string | null
  onImport: (file: File, sourceKey: string, signal: AbortSignal) => Promise<OpenApiImportResponse>
  onRetryDocuments: () => void
  onRetryApiSummaries: () => void
  onSelectDocument: (apiDocId: string) => void
  onSelectApi: (apiId: string) => void
}

type ImportState = {
  phase: ApiDocumentImportPhase
  fileName: string
  sourceKey: string
  contentHash?: string
  errorCode?: string
  errorSummary?: string
}

type TagGroup = {
  tag: string
  endpoints: ApiMetadataSummary[]
}

export function ApiExplorer({
  apiSummaries,
  apiSummariesError,
  apiSummariesState,
  currentProjectId,
  documents,
  documentsError,
  documentsState,
  selectedApiDocId,
  selectedApiId,
  onImport,
  onRetryDocuments,
  onRetryApiSummaries,
  onSelectDocument,
  onSelectApi,
}: ApiExplorerProps) {
  const { t, ui } = useConsoleLanguage()
  const [query, setQuery] = useState('')
  const [importState, setImportState] = useState<ImportState | null>(null)
  const importInput = useRef<HTMLInputElement | null>(null)
  const importController = useRef<AbortController | null>(null)
  const normalizedQuery = query.trim().toLowerCase()

  useEffect(() => {
    importController.current?.abort()
    importController.current = null
    setImportState(null)
  }, [currentProjectId])

  useEffect(() => () => importController.current?.abort(), [])

  const documentEndpointCounts = useMemo(() => {
    const counts = new Map<string, number>()
    apiSummaries.forEach((summary) => counts.set(summary.apiDocId, (counts.get(summary.apiDocId) ?? 0) + 1))
    return counts
  }, [apiSummaries])

  const documentGroups = useMemo(() => {
    const groups = new Map<string, ApiDocument[]>()
    documents.forEach((document) => {
      const group = groups.get(document.sourceKey) ?? []
      group.push(document)
      groups.set(document.sourceKey, group)
    })
    return Array.from(groups.entries()).map(([sourceKey, versions]) => ({
      sourceKey,
      versions: versions.sort((left, right) => right.versionNo - left.versionNo
        || left.apiDocId.localeCompare(right.apiDocId)),
    }))
  }, [documents])

  const startImport = (file: File) => {
    if (importState?.phase === 'PROCESSING') return

    const sourceKey = file.name.replace(/\.(?:json|ya?ml)$/i, '') || file.name
    const controller = new AbortController()
    importController.current = controller
    setImportState({ phase: 'PROCESSING', fileName: file.name, sourceKey })

    void onImport(file, sourceKey, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setImportState({
          phase: 'COMPLETED',
          fileName: result.filename,
          sourceKey: result.sourceKey,
          contentHash: result.contentHash,
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) return
        const apiError = error instanceof ApiError
          ? error
          : new ApiError('The OpenAPI document could not be imported.', 0, 'IMPORT_FAILED')
        setImportState({
          phase: 'FAILED',
          fileName: file.name,
          sourceKey,
          errorCode: apiError.code,
          errorSummary: apiError.message,
        })
      })
      .finally(() => {
        if (importController.current === controller) importController.current = null
      })
  }

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) startImport(file)
  }

  return (
    <aside className="api-explorer panel" aria-labelledby="api-explorer-title">
      <header className="studio-panel-header">
        <div className="api-browser-heading">
          <h2 id="api-explorer-title">{ui('API Browser')}</h2>
          <span>{ui('OpenAPI metadata')}</span>
        </div>
        <>
          <input
            ref={importInput}
            accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
            className="sr-only"
            onChange={handleFileChange}
            type="file"
          />
          <button
            aria-label={ui('Import OpenAPI')}
            className="studio-icon-button"
            disabled={importState?.phase === 'PROCESSING'}
            onClick={() => importInput.current?.click()}
            title={ui('Import OpenAPI')}
            type="button"
          >
            <Upload size={16} strokeWidth={1.8} />
          </button>
        </>
      </header>

      <label className="explorer-search">
        <Search size={16} strokeWidth={1.8} />
        <span className="sr-only">{ui('Search endpoints')}</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={ui('Search endpoints...')} />
      </label>

      {importState && <ImportStatus state={importState} />}

      <div className="explorer-tree">
        {documentsState === 'loading' ? (
          <div className="studio-empty-state compact-empty-state" role="status" aria-live="polite">
            <LoaderCircle size={20} strokeWidth={1.8} />
            <span>{ui('Loading documents...')}</span>
          </div>
        ) : documentsState === 'error' ? (
          <div className="studio-empty-state compact-empty-state" role="alert">
            <AlertTriangle size={20} strokeWidth={1.8} />
            <strong>{documentsError?.status === 403 ? t('auth.accessDeniedTitle') : ui('OpenAPI documents unavailable')}</strong>
            <span>{documentsError?.status === 403 ? t('auth.accessDeniedDescription') : documentsError?.message ?? ui('Unable to load OpenAPI documents.')}</span>
            <button className="panel-action" onClick={onRetryDocuments} type="button">{t('common.retry')}</button>
          </div>
        ) : documentGroups.length === 0 ? (
          <p className="explorer-empty">{ui('No OpenAPI documents found.')}</p>
        ) : (
          documentGroups.map((group) => (
            <DocumentGroup
              apiSummaries={apiSummaries}
              apiSummariesError={apiSummariesError}
              apiSummariesState={apiSummariesState}
              documentEndpointCounts={documentEndpointCounts}
              group={group}
              key={group.sourceKey}
              normalizedQuery={normalizedQuery}
              onRetryApiSummaries={onRetryApiSummaries}
              onSelectApi={onSelectApi}
              onSelectDocument={onSelectDocument}
              selectedApiDocId={selectedApiDocId}
              selectedApiId={selectedApiId}
            />
          ))
        )}
      </div>
    </aside>
  )
}

function DocumentGroup({
  apiSummaries,
  apiSummariesError,
  apiSummariesState,
  documentEndpointCounts,
  group,
  normalizedQuery,
  onRetryApiSummaries,
  onSelectApi,
  onSelectDocument,
  selectedApiDocId,
  selectedApiId,
}: {
  apiSummaries: ApiMetadataSummary[]
  apiSummariesError: ApiError | null
  apiSummariesState: 'loading' | 'ready' | 'error'
  documentEndpointCounts: Map<string, number>
  group: { sourceKey: string; versions: ApiDocument[] }
  normalizedQuery: string
  onRetryApiSummaries: () => void
  onSelectApi: (apiId: string) => void
  onSelectDocument: (apiDocId: string) => void
  selectedApiDocId: string | null
  selectedApiId: string | null
}) {
  const { t, ui } = useConsoleLanguage()
  const [expanded, setExpanded] = useState(true)

  return (
    <section className="document-group">
      <button className="document-tree-node document-tree-document" onClick={() => setExpanded((value) => !value)} type="button">
        <ChevronDown className={`document-tree-chevron${expanded ? ' is-expanded' : ''}`} size={14} strokeWidth={1.8} />
        <Package size={15} strokeWidth={1.7} />
        <span className="document-tree-copy">
          <strong>{group.versions[0].title || group.versions[0].documentName}</strong>
          <small>{group.sourceKey}</small>
        </span>
      </button>

      {expanded && (
        <div className="document-version-list">
          {group.versions.map((document) => {
            const isSelected = selectedApiDocId === document.apiDocId
            const endpointSummaries = apiSummaries.filter((summary) => summary.apiDocId === document.apiDocId)
            const tagGroups = groupByTag(endpointSummaries, normalizedQuery)

            return (
              <div className={`document-version-branch${isSelected ? ' is-selected' : ''}`} key={document.apiDocId}>
                <button
                  aria-pressed={isSelected}
                  className="document-tree-node document-tree-version"
                  onClick={() => onSelectDocument(document.apiDocId)}
                  type="button"
                >
                  <ChevronDown className={`document-tree-chevron${isSelected ? ' is-expanded' : ''}`} size={13} strokeWidth={1.8} />
                  <span className="document-version-copy">
                    <strong>v{document.versionNo} <span>{document.apiVersion}</span></strong>
                    <small>{documentEndpointCounts.get(document.apiDocId) ?? 0} {ui('endpoints')} · OpenAPI {document.openapiVersion}</small>
                  </span>
                  <span className={`document-status document-status-${document.status.toLowerCase()}`}>{document.status}</span>
                </button>

                {isSelected ? (
                  <div className="document-version-content">
                    {apiSummariesState === 'loading' ? (
                      <div className="studio-empty-state compact-empty-state" role="status" aria-live="polite">
                        <LoaderCircle size={18} strokeWidth={1.8} />
                        <span>{ui('Loading endpoints...')}</span>
                      </div>
                    ) : apiSummariesState === 'error' ? (
                      <div className="studio-empty-state compact-empty-state" role="alert">
                        <AlertTriangle size={18} strokeWidth={1.8} />
                        <strong>{apiSummariesError?.status === 403 ? t('auth.accessDeniedTitle') : ui('API endpoints unavailable')}</strong>
                        <span>{apiSummariesError?.status === 403 ? t('auth.accessDeniedDescription') : apiSummariesError?.message ?? ui('Unable to load API endpoints.')}</span>
                        <button className="panel-action" onClick={onRetryApiSummaries} type="button">{t('common.retry')}</button>
                      </div>
                    ) : tagGroups.length > 0 ? (
                      tagGroups.map((tagGroup) => (
                        <TagGroupSection
                          group={tagGroup}
                          key={tagGroup.tag}
                          onSelectApi={onSelectApi}
                          selectedApiId={selectedApiId}
                        />
                      ))
                    ) : (
                      <p className="explorer-empty">{ui('No endpoints found.')}</p>
                    )}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function groupByTag(endpoints: ApiMetadataSummary[], normalizedQuery: string): TagGroup[] {
  const visibleEndpoints = endpoints.filter((endpoint) => !normalizedQuery
    || `${endpoint.apiId} ${endpoint.apiDocId} ${endpoint.method} ${endpoint.path} ${endpoint.summary ?? ''} ${endpoint.operationId} ${formatTags(endpoint.tags).join(' ')}`.toLowerCase().includes(normalizedQuery))
  const groups = new Map<string, ApiMetadataSummary[]>()

  visibleEndpoints.forEach((endpoint) => {
    const tags = formatTags(endpoint.tags)
    const effectiveTags = tags.length > 0 ? tags : ['Untagged']
    effectiveTags.forEach((tag) => groups.set(tag, [...(groups.get(tag) ?? []), endpoint]))
  })

  return Array.from(groups.entries()).map(([tag, tagEndpoints]) => ({ tag, endpoints: tagEndpoints }))
}

function formatTags(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((tag): tag is string => typeof tag === 'string' && tag.trim().length > 0)
}

function TagGroupSection({ group, onSelectApi, selectedApiId }: { group: TagGroup; onSelectApi: (apiId: string) => void; selectedApiId: string | null }) {
  const [expanded, setExpanded] = useState(true)

  return (
    <section className="tag-group">
      <button className="tag-group-heading" onClick={() => setExpanded((value) => !value)} type="button">
        <ChevronDown className={`document-tree-chevron${expanded ? ' is-expanded' : ''}`} size={12} strokeWidth={1.8} />
        <span>{group.tag}</span>
        <small>{group.endpoints.length}</small>
      </button>
      {expanded && (
        <div className="endpoint-list">
          {group.endpoints.map((endpoint) => (
            <EndpointListItem endpoint={endpoint} isSelected={selectedApiId === endpoint.apiId} key={endpoint.apiId} onSelect={() => onSelectApi(endpoint.apiId)} />
          ))}
        </div>
      )}
    </section>
  )
}

function ImportStatus({ state }: { state: ImportState }) {
  const { ui } = useConsoleLanguage()
  const isFailure = state.phase === 'FAILED'

  return (
    <div className={`document-import-status${isFailure ? ' is-failed' : ''}`} role="status">
      <strong>{ui(state.phase === 'PROCESSING' ? 'Parsing document...' : state.phase === 'COMPLETED' ? 'Import ready' : 'Import failed')}</strong>
      <span>{ui('Document')}: {state.fileName}</span>
      {state.errorCode && <small>{state.errorCode} · {state.errorSummary}</small>}
      {state.contentHash && <small className="document-id">contentHash {state.contentHash}</small>}
    </div>
  )
}

function EndpointListItem({ endpoint, isSelected, onSelect }: { endpoint: ApiMetadataSummary; isSelected: boolean; onSelect: () => void }) {
  const { ui } = useConsoleLanguage()
  const methodClass = endpoint.method.toLowerCase().replace(/[^a-z0-9-]/g, '-')

  return (
    <button aria-pressed={isSelected} className={`endpoint-list-item${isSelected ? ' is-selected' : ''}`} onClick={onSelect} type="button">
      <span className={`method-badge studio-method method-${methodClass}`}>{endpoint.method}</span>
      <span className="endpoint-list-copy">
        <strong>{endpoint.path}</strong>
        <small>{endpoint.summary || endpoint.operationId || endpoint.apiId}</small>
        <small className="endpoint-operation-id">{endpoint.operationId || endpoint.apiId}</small>
      </span>
      {endpoint.deprecated && <span className="endpoint-deprecated">{ui('Deprecated')}</span>}
    </button>
  )
}
