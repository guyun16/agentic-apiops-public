import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useProject } from './ProjectContext'
import { resolveActiveContext, type ActiveContext, type ContextReadModelGap, type ContextTrailCache, type ContextTrailDiagnosis, type ContextTrailEndpoint, type ContextTrailReport, type ContextTrailRun, type ContextTrailTarget, type ContextTrailTestCase } from './contextTrailModel'

export { resolveActiveContext }
export type { ActiveContext, ContextReadModelGap, ContextTrailCache, ContextTrailDiagnosis, ContextTrailEndpoint, ContextTrailReport, ContextTrailRun, ContextTrailTarget, ContextTrailTestCase, EndpointIdentityResolution, EndpointIdentityResolutionKind } from './contextTrailModel'

type ContextTrailState = ContextTrailCache & {
  activeContext: ActiveContext | null
  activeTarget: ContextTrailTarget | null
  contextReadModelGap: ContextReadModelGap | null
}

type FinalizedTestCaseInput = Omit<ContextTrailTestCase, 'runIds'> & {
  status: 'ACCEPTED'
}

type ObservedTestCaseInput = Pick<ContextTrailTestCase, 'id' | 'apiId' | 'apiDocId' | 'name'> & {
  runId: number
}

type ContextTrailContextValue = ContextTrailState & {
  recordEndpoint: (endpoint: ContextTrailEndpoint) => void
  recordFinalizedTestCase: (testCase: FinalizedTestCaseInput) => void
  recordObservedTestCase: (testCase: ObservedTestCaseInput) => void
  recordRun: (run: Omit<ContextTrailRun, 'id' | 'diagnosisIds'>) => void
  recordDiagnosis: (diagnosis: ContextTrailDiagnosis) => void
  recordReport: (report: ContextTrailReport) => void
  recordContextReadModelGap: (gap: ContextReadModelGap) => void
  activateContext: (target: ContextTrailTarget) => void
}

const emptyState: ContextTrailState = {
  endpoints: [],
  testCases: [],
  runs: [],
  diagnoses: [],
  reports: [],
  activeContext: null,
  activeTarget: null,
  contextReadModelGap: null,
}

const ContextTrailContext = createContext<ContextTrailContextValue | null>(null)

function endpointKey(endpoint: Pick<ContextTrailEndpoint, 'id' | 'apiDocId'>) {
  return `${endpoint.id}::${endpoint.apiDocId}`
}

function testCaseKey(testCase: Pick<ContextTrailTestCase, 'id' | 'apiId' | 'apiDocId'>) {
  return `${testCase.id}::${testCase.apiId}::${testCase.apiDocId}`
}

function diagnosisKey(diagnosis: Pick<ContextTrailDiagnosis, 'agentRunId' | 'runId'>) {
  return `${diagnosis.agentRunId}::${diagnosis.runId}`
}

function reportKey(report: Pick<ContextTrailReport, 'reportId' | 'agentRunId' | 'runId'>) {
  return `${report.reportId}::${report.agentRunId}::${report.runId}`
}

function appendUnique<T>(values: T[], value: T) {
  return values.includes(value) ? values : [...values, value]
}

export function ContextTrailProvider({ children }: { children: ReactNode }) {
  const { currentProject } = useProject()
  const [state, setState] = useState<ContextTrailState>(emptyState)

  useEffect(() => {
    setState({ ...emptyState })
  }, [currentProject?.projectId])

  const recordEndpoint = useCallback((endpoint: ContextTrailEndpoint) => {
    setState((current) => {
      const nextEndpoint = current.endpoints.find((item) => endpointKey(item) === endpointKey(endpoint))
      if (nextEndpoint && JSON.stringify(nextEndpoint) === JSON.stringify(endpoint)) return current
      return {
        ...current,
        endpoints: nextEndpoint
          ? current.endpoints.map((item) => endpointKey(item) === endpointKey(endpoint) ? endpoint : item)
          : [...current.endpoints, endpoint],
      }
    })
  }, [])

  const recordObservedTestCase = useCallback((testCase: ObservedTestCaseInput) => {
    setState((current) => {
      const existing = current.testCases.find((item) => testCaseKey(item) === testCaseKey(testCase))
      const runIds = [...new Set([...(existing?.runIds ?? []), testCase.runId])]
      const nextTestCase = existing
        ? { ...existing, ...testCase, runIds }
        : { ...testCase, runIds }
      return {
        ...current,
        testCases: existing
          ? current.testCases.map((item) => testCaseKey(item) === testCaseKey(testCase) ? nextTestCase : item)
          : [...current.testCases, nextTestCase],
      }
    })
  }, [])

  const recordFinalizedTestCase = useCallback((testCase: FinalizedTestCaseInput) => {
    const { status, ...finalizedTestCase } = testCase
    if (status !== 'ACCEPTED' || !finalizedTestCase.dsl?.trim()) return

    setState((current) => {
      const existing = current.testCases.find((item) => testCaseKey(item) === testCaseKey(testCase))
      const relatedRunIds = current.runs
        .filter((run) => run.caseId === testCase.id && run.apiId === testCase.apiId)
        .map((run) => run.runId)
      const runIds = [...new Set([...(existing?.runIds ?? []), ...relatedRunIds])]
      const nextTestCase = existing
        ? { ...existing, ...finalizedTestCase, runIds }
        : { ...finalizedTestCase, runIds }
      return {
        ...current,
        testCases: existing
          ? current.testCases.map((item) => testCaseKey(item) === testCaseKey(testCase) ? nextTestCase : item)
          : [...current.testCases, nextTestCase],
      }
    })
  }, [])

  const recordRun = useCallback((run: Omit<ContextTrailRun, 'id' | 'diagnosisIds'>) => {
    setState((current) => {
      const existingRun = current.runs.find((item) => item.runId === run.runId)
      const relatedTestCases = current.testCases.filter((item) => item.id === run.caseId && item.apiId === run.apiId)
      const relatedDiagnosisIds = current.diagnoses
        .filter((diagnosis) => diagnosis.runId === run.runId)
        .map((diagnosis) => diagnosis.agentRunId)
      const diagnosisIds = [...new Set([...(existingRun?.diagnosisIds ?? []), ...relatedDiagnosisIds])]
      const nextRun = existingRun
        ? { ...existingRun, ...run, diagnosisIds }
        : { ...run, id: String(run.runId), diagnosisIds }

      return {
        ...current,
        testCases: relatedTestCases.length === 1
          ? current.testCases.map((item) => item.id === run.caseId && item.apiId === run.apiId
            ? { ...item, runIds: appendUnique(item.runIds, run.runId) }
            : item)
          : current.testCases,
        runs: existingRun
          ? current.runs.map((item) => item.runId === run.runId ? nextRun : item)
          : [...current.runs, nextRun],
      }
    })
  }, [])

  const recordDiagnosis = useCallback((diagnosis: ContextTrailDiagnosis) => {
    setState((current) => {
      const existing = current.diagnoses.find((item) => diagnosisKey(item) === diagnosisKey(diagnosis))
      const nextDiagnosis = existing ? { ...existing, ...diagnosis } : diagnosis
      return {
        ...current,
        diagnoses: existing
          ? current.diagnoses.map((item) => diagnosisKey(item) === diagnosisKey(diagnosis) ? nextDiagnosis : item)
          : [...current.diagnoses, nextDiagnosis],
        runs: current.runs.map((run) => run.runId === diagnosis.runId
          ? { ...run, diagnosisIds: appendUnique(run.diagnosisIds, diagnosis.agentRunId) }
          : run),
      }
    })
  }, [])

  const recordReport = useCallback((report: ContextTrailReport) => {
    setState((current) => ({
      ...current,
      reports: current.reports.some((item) => reportKey(item) === reportKey(report))
        ? current.reports.map((item) => reportKey(item) === reportKey(report) ? report : item)
        : [...current.reports, report],
      diagnoses: current.diagnoses.map((diagnosis) => diagnosis.agentRunId === report.agentRunId && diagnosis.runId === report.runId
        ? { ...diagnosis, reportId: report.reportId }
        : diagnosis),
    }))
  }, [])

  const recordContextReadModelGap = useCallback((gap: ContextReadModelGap) => {
    setState((current) => (
      JSON.stringify(current.contextReadModelGap) === JSON.stringify(gap)
        ? current
        : { ...current, contextReadModelGap: gap }
    ))
  }, [])

  const activateContext = useCallback((target: ContextTrailTarget) => {
    setState((current) => {
      const activeContext = resolveActiveContext(target, current, current.activeContext)
      return activeContext
        ? { ...current, activeContext, activeTarget: target, contextReadModelGap: null }
        : current
    })
  }, [])

  const value = useMemo<ContextTrailContextValue>(() => ({
    ...state,
    activateContext,
    recordDiagnosis,
    recordContextReadModelGap,
    recordEndpoint,
    recordFinalizedTestCase,
    recordObservedTestCase,
    recordReport,
    recordRun,
  }), [activateContext, recordContextReadModelGap, recordDiagnosis, recordEndpoint, recordFinalizedTestCase, recordObservedTestCase, recordReport, recordRun, state])

  return <ContextTrailContext.Provider value={value}>{children}</ContextTrailContext.Provider>
}

export function useContextTrail() {
  const context = useContext(ContextTrailContext)
  if (!context) throw new Error('useContextTrail must be used within ContextTrailProvider')
  return context
}
