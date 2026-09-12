import { ChevronDown, ChevronsLeft, ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useConsoleLanguage } from '../../app/ConsoleLanguage'
import { resolveEndpointIdentityForRun } from '../../app/contextTrailModel'
import {
  useContextTrail,
  type ActiveContext,
  type ContextReadModelGap,
  type ContextTrailDiagnosis,
  type ContextTrailEndpoint,
  type ContextTrailReport,
  type ContextTrailRun,
  type ContextTrailTarget,
  type ContextTrailTestCase,
} from '../../app/ContextTrailContext'

export type TrailGroup = 'endpoint' | 'testcase' | 'run' | 'diagnosis' | 'report'

const allTrailGroups: TrailGroup[] = ['endpoint', 'testcase', 'run', 'diagnosis', 'report']

const groupLabels: Record<TrailGroup, string> = {
  endpoint: 'Endpoint',
  testcase: 'TestCase',
  run: 'Runs',
  diagnosis: 'Diagnosis',
  report: 'Report',
}

type ContextTrailProps = {
  onNavigate: (target: ContextTrailTarget) => void
  compact?: boolean
  visibleGroups?: readonly TrailGroup[]
}

export function ContextTrail({ compact = false, onNavigate, visibleGroups = allTrailGroups }: ContextTrailProps) {
  const { ui } = useConsoleLanguage()
  const {
    activateContext,
    activeContext,
    activeTarget,
    contextReadModelGap,
    diagnoses,
    endpoints,
    reports,
    runs,
    testCases,
  } = useContextTrail()
  const endpointResolution = activeContext?.endpointResolution ?? null
  const endpoint = useMemo(() => {
    if (endpointResolution?.endpoint) return endpointResolution.endpoint
    if (!activeContext?.endpointId) return null
    return endpoints.find((item) => (
      item.id === activeContext.endpointId
      && (!activeContext.endpointApiDocId || item.apiDocId === activeContext.endpointApiDocId)
    )) ?? null
  }, [activeContext, endpointResolution, endpoints])
  const endpointSourceValue = endpointResolution?.sourceValue ?? activeContext?.endpointId ?? null
  const visibleTestCases = useMemo(
    () => {
      if (!activeContext || !endpointSourceValue) return []
      if (endpoint) {
        return testCases.filter((testCase) => (
          testCase.apiId === endpoint.id
          && (!endpoint.apiDocId || testCase.apiDocId === endpoint.apiDocId)
        ))
      }
      if (!activeContext.caseId) return []
      return testCases.filter((testCase) => testCase.id === activeContext.caseId && testCase.apiId === endpointSourceValue)
    },
    [activeContext, endpoint, endpointSourceValue, testCases],
  )
  const currentTestCase = useMemo(() => {
    if (!activeContext?.caseId || !endpointSourceValue) return null
    const matches = testCases.filter((testCase) => (
      testCase.id === activeContext.caseId
      && testCase.apiId === (endpoint?.id ?? endpointSourceValue)
      && (!endpoint?.apiDocId || testCase.apiDocId === endpoint.apiDocId)
    ))
    return matches.length === 1 ? matches[0] : null
  }, [activeContext, endpoint, endpointSourceValue, testCases])
  const currentRun = useMemo(() => {
    if (!activeContext?.runId || !activeContext.caseId || !endpointSourceValue) return null
    return runs.find((run) => (
      run.runId === activeContext.runId
      && run.caseId === activeContext.caseId
      && run.apiId === endpointSourceValue
    )) ?? null
  }, [activeContext, endpointSourceValue, runs])
  const relatedRuns = useMemo(
    () => currentTestCase
      ? runs.filter((run) => {
        if (run.caseId !== currentTestCase.id) return false
        if (run.apiId === currentTestCase.apiId) return true
        const resolution = resolveEndpointIdentityForRun(run.apiId, endpoints)
        return resolution.endpoint?.id === currentTestCase.apiId
          && (!currentTestCase.apiDocId || resolution.endpoint.apiDocId === currentTestCase.apiDocId)
      })
      : currentRun ? [currentRun] : [],
    [currentRun, currentTestCase, endpoints, runs],
  )
  const relatedDiagnoses = useMemo(
    () => currentRun
      ? diagnoses.filter((diagnosis) => diagnosis.runId === currentRun.runId)
      : activeContext?.runId !== null && activeContext?.runId !== undefined
        ? diagnoses.filter((diagnosis) => diagnosis.runId === activeContext.runId)
        : [],
    [activeContext, currentRun, diagnoses],
  )
  const currentDiagnosis = useMemo(() => {
    if (!activeContext?.agentRunId) return null
    return relatedDiagnoses.find((diagnosis) => diagnosis.agentRunId === activeContext.agentRunId) ?? diagnoses.find((diagnosis) => (
      diagnosis.agentRunId === activeContext.agentRunId
      && diagnosis.runId === activeContext.runId
    )) ?? null
  }, [activeContext, diagnoses, relatedDiagnoses])
  const relatedReports = useMemo(
    () => (currentDiagnosis?.reportId ?? activeContext?.reportId)
      ? reports.filter((report) => (
        report.reportId === (currentDiagnosis?.reportId ?? activeContext?.reportId)
        && report.agentRunId === (currentDiagnosis?.agentRunId ?? activeContext?.agentRunId)
        && report.runId === (currentDiagnosis?.runId ?? activeContext?.runId)
      ))
      : [],
    [activeContext, currentDiagnosis, reports],
  )
  const currentReport = useMemo(() => {
    if (!activeContext?.reportId || !currentDiagnosis) return null
    return relatedReports.find((report) => report.reportId === activeContext.reportId) ?? null
  }, [activeContext, currentDiagnosis, relatedReports])
  const [collapsed, setCollapsed] = useState(false)
  const [expanded, setExpanded] = useState<Record<TrailGroup, boolean>>({
    endpoint: true,
    testcase: false,
    run: false,
    diagnosis: false,
    report: false,
  })
  const [userExpanded, setUserExpanded] = useState<Record<TrailGroup, boolean>>({
    endpoint: false,
    testcase: false,
    run: false,
    diagnosis: false,
    report: false,
  })

  useEffect(() => {
    if (!activeContext) return
    setExpanded((current) => ({
      ...current,
      endpoint: Boolean(endpoint || endpointResolution),
      testcase: Boolean(currentTestCase),
      run: Boolean(currentRun),
      diagnosis: Boolean(currentDiagnosis),
      report: Boolean(currentReport),
    }))
  }, [activeContext, currentDiagnosis, currentReport, currentRun, currentTestCase, endpoint, endpointResolution])

  useEffect(() => {
    setUserExpanded({
      endpoint: false,
      testcase: false,
      run: false,
      diagnosis: false,
      report: false,
    })
  }, [activeContext])

  const toggleGroup = (group: TrailGroup) => {
    setExpanded((current) => ({
      ...current,
      [group]: current[group] && userExpanded[group] ? false : true,
    }))
    setUserExpanded((current) => ({ ...current, [group]: true }))
  }

  const navigate = (target: ContextTrailTarget) => {
    activateContext(target)
    onNavigate(target)
  }

  if (collapsed) {
    return (
      <aside className={`context-trail context-trail-collapsed panel${compact ? ' context-trail-compact' : ''}`} aria-label={ui('Context Trail')}>
        <button
          aria-label={ui('Expand Context Trail')}
          className="context-trail-expand"
          onClick={() => setCollapsed(false)}
          title={ui('Expand Context Trail')}
          type="button"
        >
          <ChevronRight size={16} strokeWidth={1.8} />
        </button>
      </aside>
    )
  }

  return (
    <aside className={`context-trail panel${compact ? ' context-trail-compact' : ''}`} aria-labelledby="context-trail-title">
      <header className="context-trail-header">
        <h2 id="context-trail-title">{ui('Context Trail')}</h2>
        <button
          aria-label={ui('Collapse Context Trail')}
          className="studio-icon-button context-trail-collapse"
          onClick={() => setCollapsed(true)}
          title={ui('Collapse Context Trail')}
          type="button"
        >
          <ChevronsLeft size={17} strokeWidth={1.8} />
        </button>
      </header>

      <div className="context-trail-scroll">
        <ActiveTrailContent
          activeContext={activeContext}
          activeTarget={activeTarget}
          currentDiagnosis={currentDiagnosis}
          currentReport={currentReport}
          currentRun={currentRun}
          currentTestCase={currentTestCase}
          contextReadModelGap={contextReadModelGap}
          endpoint={endpoint}
          endpointResolution={endpointResolution}
          expanded={expanded}
          onNavigate={navigate}
          onToggle={toggleGroup}
          relatedDiagnoses={relatedDiagnoses}
          relatedReports={relatedReports}
          relatedRuns={relatedRuns}
          testCases={visibleTestCases}
          userExpanded={userExpanded}
          visibleGroups={visibleGroups}
        />
      </div>
    </aside>
  )
}

type ActiveTrailContentProps = {
  activeContext: ActiveContext | null
  activeTarget: ContextTrailTarget | null
  contextReadModelGap: ContextReadModelGap | null
  currentDiagnosis: ContextTrailDiagnosis | null
  currentReport: ContextTrailReport | null
  currentRun: ContextTrailRun | null
  currentTestCase: ContextTrailTestCase | null
  endpoint: ContextTrailEndpoint | null
  endpointResolution: ActiveContext['endpointResolution']
  expanded: Record<TrailGroup, boolean>
  onNavigate: (target: ContextTrailTarget) => void
  onToggle: (group: TrailGroup) => void
  relatedDiagnoses: ContextTrailDiagnosis[]
  relatedReports: ContextTrailReport[]
  relatedRuns: ContextTrailRun[]
  testCases: ContextTrailTestCase[]
  userExpanded: Record<TrailGroup, boolean>
  visibleGroups: readonly TrailGroup[]
}

function ActiveTrailContent({
  activeContext,
  activeTarget,
  currentDiagnosis,
  currentReport,
  currentRun,
  currentTestCase,
  contextReadModelGap,
  endpoint,
  endpointResolution,
  expanded,
  onNavigate,
  onToggle,
  relatedDiagnoses,
  relatedReports,
  relatedRuns,
  testCases,
  userExpanded,
  visibleGroups,
}: ActiveTrailContentProps) {
  const { ui } = useConsoleLanguage()
  const visibleTestCases = userExpanded.testcase
    ? testCases
    : currentTestCase ? [currentTestCase] : []
  const visibleRuns = userExpanded.run
    ? relatedRuns
    : currentRun ? [currentRun] : []
  const visibleDiagnoses = userExpanded.diagnosis
    ? relatedDiagnoses
    : currentDiagnosis ? [currentDiagnosis] : []
  const visibleReports = userExpanded.report
    ? relatedReports
    : currentReport ? [currentReport] : []

  return (
    <>
      {visibleGroups.includes('endpoint') && (endpoint || endpointResolution) ? (
        <TrailGroupSection
          count={null}
          expanded={expanded.endpoint}
          group="endpoint"
          onToggle={() => onToggle('endpoint')}
        >
          {endpoint ? (
            <TrailNode
              active={activeTarget?.type === 'endpoint' && activeTarget.id === endpoint.id}
              className="trail-endpoint"
              onClick={() => onNavigate({ type: 'endpoint', id: endpoint.id, apiDocId: endpoint.apiDocId })}
              title={ui('Endpoint')}
            >
              <span className="trail-endpoint-route">
                <span className="trail-endpoint-method" data-method={endpoint.method}>{endpoint.method}</span>
                <strong>{endpoint.path}</strong>
                <span className="trail-node-badge">{ui('ROOT')}</span>
              </span>
              {endpoint.operationId && <small>{endpoint.operationId}</small>}
            </TrailNode>
          ) : endpointResolution ? (
            <TrailNode
              active={false}
              className="trail-endpoint trail-endpoint-unresolved"
              disabled
              onClick={() => undefined}
              title={ui(endpointResolution.resolution === 'AMBIGUOUS_OPERATION_ID' ? 'Unresolved / Ambiguous' : 'Unresolved')}
            >
              <strong>{ui(endpointResolution.resolution === 'AMBIGUOUS_OPERATION_ID' ? 'Unresolved / Ambiguous' : 'Unresolved')}</strong>
              <small>operationId: {endpointResolution.sourceValue}</small>
              <small>{ui(endpointResolution.resolution === 'AMBIGUOUS_OPERATION_ID' ? 'Multiple endpoints share this operationId.' : 'Endpoint identity is unavailable.')}</small>
            </TrailNode>
          ) : null}
        </TrailGroupSection>
      ) : null}

      {visibleGroups.includes('testcase') && testCases.length > 0 ? (
        <TrailGroupSection
          count={testCases.length}
          expanded={expanded.testcase}
          group="testcase"
          onToggle={() => onToggle('testcase')}
        >
          {visibleTestCases.map((testCase) => (
            <TrailNode
              active={activeTarget?.type === 'testcase' && activeTarget.id === testCase.id}
              className="trail-testcase"
              key={`${testCase.id}::${testCase.apiId}::${testCase.apiDocId}`}
              onClick={() => onNavigate({
                type: 'testcase',
                id: testCase.id,
                apiId: testCase.apiId,
                apiDocId: testCase.apiDocId,
                dsl: testCase.dsl,
                generator: testCase.generator,
                strategy: testCase.strategy,
              })}
              title={testCase.id}
            >
              <strong>{testCase.id}</strong>
              <small>{testCase.name}</small>
              {testCase.strategy && <small>{testCase.strategy}</small>}
            </TrailNode>
          ))}
        </TrailGroupSection>
      ) : null}

      {visibleGroups.includes('run') && currentRun && relatedRuns.length > 0 ? (
        <TrailGroupSection
          count={relatedRuns.length}
          expanded={expanded.run}
          group="run"
          onToggle={() => onToggle('run')}
        >
          {visibleRuns.map((run) => (
            <TrailNode
              active={activeTarget?.type === 'run' && activeTarget.runId === run.runId}
              className="trail-run"
              key={run.id}
              onClick={() => onNavigate({ type: 'run', id: run.id, runId: run.runId, caseId: run.caseId, apiId: run.apiId })}
              title={`#${run.runId}`}
            >
              <strong>#{run.runId}</strong>
              <small>{run.name}</small>
              <small>{ui(run.status)}</small>
            </TrailNode>
          ))}
        </TrailGroupSection>
      ) : null}

      {visibleGroups.includes('diagnosis') && currentRun && relatedDiagnoses.length > 0 ? (
        <TrailGroupSection
          count={relatedDiagnoses.length}
          expanded={expanded.diagnosis}
          group="diagnosis"
          onToggle={() => onToggle('diagnosis')}
        >
          {visibleDiagnoses.map((diagnosis) => (
            <TrailNode
              active={activeTarget?.type === 'diagnosis' && activeTarget.agentRunId === diagnosis.agentRunId && activeTarget.runId === diagnosis.runId}
              className="trail-diagnosis"
              key={`${diagnosis.agentRunId}::${diagnosis.runId}`}
              onClick={() => onNavigate({
                type: 'diagnosis',
                id: diagnosis.id,
                agentRunId: diagnosis.agentRunId,
                runId: diagnosis.runId,
              })}
              title={diagnosis.agentRunId}
            >
              <strong>{diagnosis.agentRunId}</strong>
              <small>{ui(diagnosis.status)}</small>
            </TrailNode>
          ))}
        </TrailGroupSection>
      ) : null}

      {visibleGroups.includes('report') && currentDiagnosis && relatedReports.length > 0 ? (
        <TrailGroupSection
          count={null}
          expanded={expanded.report}
          group="report"
          onToggle={() => onToggle('report')}
        >
          {visibleReports.map((report) => (
            <TrailNode
              active={activeTarget?.type === 'report' && activeTarget.reportId === report.reportId && activeTarget.agentRunId === report.agentRunId && activeTarget.runId === report.runId}
              className="trail-report"
              key={`${report.reportId}::${report.agentRunId}::${report.runId}`}
              onClick={() => onNavigate({
                type: 'report',
                id: report.id,
                reportId: report.reportId,
                agentRunId: report.agentRunId,
                runId: report.runId,
              })}
              title={report.reportId}
            >
              <strong>{report.reportId}</strong>
              <small>{ui('Run')} #{report.runId}</small>
            </TrailNode>
          ))}
        </TrailGroupSection>
      ) : null}

      {contextReadModelGap ? (
        <div className="context-trail-gap" role="status">
          <strong>{ui('Context Read Model Gap')}</strong>
          <span>{contextReadModelGap.reason}</span>
        </div>
      ) : null}

      {!activeContext && <div className="context-trail-empty">{ui('No active context')}</div>}
    </>
  )
}

function TrailGroupSection({ children, count, expanded, group, onToggle }: { children: ReactNode; count: number | null; expanded: boolean; group: TrailGroup; onToggle: () => void }) {
  const { ui } = useConsoleLanguage()
  return (
    <section className={`context-trail-group trail-group-${group}`}>
      <button className="context-trail-group-heading" onClick={onToggle} type="button">
        <ChevronDown className={`context-trail-chevron${expanded ? ' is-expanded' : ''}`} size={13} strokeWidth={1.8} />
        <span className="trail-group-dot" />
        <strong>{ui(groupLabels[group])}</strong>
        {count !== null && <span className="trail-group-count">({count})</span>}
      </button>
      {expanded && <div className="context-trail-group-content">{children}</div>}
    </section>
  )
}

function TrailNode({ active, children, className, disabled = false, onClick, title }: { active: boolean; children: ReactNode; className: string; disabled?: boolean; onClick: () => void; title: string }) {
  return (
    <button aria-current={active ? 'page' : undefined} className={`context-trail-node ${className}${active ? ' is-active' : ''}`} disabled={disabled} onClick={onClick} title={title} type="button">
      <span className="trail-node-dot" />
      <span className="trail-node-copy">{children}</span>
    </button>
  )
}
