import type {
  TraceApprovalFacts,
  TraceAttribute,
  TraceContextEvidenceFacts,
  TraceModelCallFacts,
  TraceObservationFacts,
  TraceRecord,
  TraceSource,
  TraceStatus,
  TraceStep,
  TraceStepDetail,
  TraceStepKind,
  TraceStepStatus,
  TraceToolActivityFacts,
} from './types'

export type TraceApiRecord = {
  record_type: string
  event: string
  trace_id: string
  agent_run_id: string
  agent_step_id?: string | null
  sequence?: number | null
  timestamp: string
  workflow_id?: string | null
  thread_id?: string | null
  project_id?: string | number | null
  status: string
  failure?: {
    failure_category?: string
    failure_code?: string | null
    message?: string
    error_type?: string | null
  } | null
  [key: string]: unknown
}

type ValueMap = Record<string, unknown>

function asMap(value: unknown): ValueMap | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as ValueMap
    : null
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function number(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function boolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function valueText(value: unknown) {
  return text(value) ?? (typeof value === 'number' ? String(value) : undefined)
}

function status(value: unknown): TraceStatus {
  if (value === 'SUCCESS' || value === 'FAILED' || value === 'REJECTED'
    || value === 'DENIED' || value === 'RUNNING' || value === 'INTERRUPTED') {
    return value
  }
  return 'RUNNING'
}

function stepStatus(value: unknown): TraceStepStatus {
  return status(value)
}

function timestampMs(value: string) {
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatTimestamp(value: string) {
  return timestampMs(value) === null ? 'UNKNOWN' : new Date(value).toISOString()
}

function formatDuration(durationMs: number | undefined) {
  if (durationMs === undefined) return 'UNKNOWN'
  return durationMs >= 1000 ? `${(durationMs / 1000).toFixed(2)} s` : `${Math.round(durationMs)} ms`
}

function digestText(value: unknown) {
  const digest = asMap(value)
  if (!digest) return 'UNKNOWN'
  return JSON.stringify({
    sha256: text(digest.sha256) ?? 'UNKNOWN',
    summary: text(digest.summary) ?? 'UNKNOWN',
    truncated: boolean(digest.truncated) ?? false,
  }, null, 2)
}

function sortRecords(records: TraceApiRecord[]) {
  return [...records].sort((left, right) => {
    const leftSequence = left.sequence ?? Number.MAX_SAFE_INTEGER
    const rightSequence = right.sequence ?? Number.MAX_SAFE_INTEGER
    return leftSequence - rightSequence || (timestampMs(left.timestamp) ?? 0) - (timestampMs(right.timestamp) ?? 0)
  })
}

function groupBy(records: TraceApiRecord[], key: (record: TraceApiRecord) => string | undefined) {
  const groups = new Map<string, TraceApiRecord[]>()
  records.forEach((record) => {
    const groupKey = key(record)
    if (!groupKey) return
    const group = groups.get(groupKey) ?? []
    group.push(record)
    groups.set(groupKey, group)
  })
  return groups
}

function firstOf(records: TraceApiRecord[], event: string) {
  return records.find((record) => record.event === event)
}

function lastOf(records: TraceApiRecord[], event: string) {
  return [...records].reverse().find((record) => record.event === event)
}

function timeRange(records: TraceApiRecord[], fallback: TraceApiRecord) {
  const valid = records
    .map((record) => timestampMs(record.timestamp))
    .filter((value): value is number => value !== null)
  const start = valid.length ? Math.min(...valid) : timestampMs(fallback.timestamp) ?? 0
  const end = valid.length ? Math.max(...valid) : start
  return { start, end, durationMs: Math.max(0, end - start) }
}

function attributes(records: TraceApiRecord[]): TraceAttribute[] {
  const recordTypes = [...new Set(records.map((record) => record.record_type))]
  const events = [...new Set(records.map((record) => record.event))]
  const sequences = records
    .map((record) => record.sequence)
    .filter((value): value is number => typeof value === 'number')
  const result: TraceAttribute[] = [
    { label: 'recordType', value: recordTypes.join(' / ') || 'UNKNOWN' },
    { label: 'event', value: events.join(' → ') || 'UNKNOWN' },
  ]
  if (sequences.length) {
    result.push({ label: 'sequence', value: sequences.length === 1 ? String(sequences[0]) : `${Math.min(...sequences)}–${Math.max(...sequences)}` })
  }
  const projectId = records.map((record) => valueText(record.project_id)).find(Boolean)
  if (projectId) result.push({ label: 'projectId', value: projectId })
  const workflowId = records.map((record) => text(record.workflow_id)).find(Boolean)
  if (workflowId) result.push({ label: 'workflowId', value: workflowId })
  const failureCode = records.map((record) => text(record.failure?.failure_code)).find(Boolean)
  if (failureCode) result.push({ label: 'failureCode', value: failureCode })
  return result
}

function detailBase(
  records: TraceApiRecord[],
  fallback: TraceApiRecord,
  source: TraceSource,
  parentStep: string,
  input = 'UNKNOWN',
  output = 'UNKNOWN',
  overrideStatus?: TraceApiRecord,
): TraceStepDetail {
  const range = timeRange(records, fallback)
  return {
    status: stepStatus((overrideStatus ?? records[records.length - 1] ?? fallback).status),
    durationLabel: formatDuration(range.durationMs),
    traceId: fallback.trace_id,
    parentStep,
    source,
    startTime: formatTimestamp(records[0]?.timestamp ?? fallback.timestamp),
    endTime: formatTimestamp(records[records.length - 1]?.timestamp ?? fallback.timestamp),
    input,
    output,
    attributes: attributes(records),
  }
}

function modelFacts(records: TraceApiRecord[], start: TraceApiRecord, terminal: TraceApiRecord | undefined): TraceModelCallFacts {
  const source = terminal ?? start
  const identity = asMap(source.model_identity)
  const prompt = asMap(source.prompt)
  const usage = asMap(source.token_usage)
  const latency = asMap(source.latency)
  const range = timeRange(records, start)
  const measuredDuration = number(latency?.duration_ms)
  return {
    modelCallId: text(source.model_call_id) ?? 'UNKNOWN',
    provider: text(identity?.provider) ?? 'UNKNOWN',
    model: text(identity?.model) ?? 'UNKNOWN',
    runtime: 'Python AgentLab',
    implementation: 'Existing workflow instrumentation',
    promptName: text(prompt?.name) ?? 'UNKNOWN',
    promptVersion: text(prompt?.version) ?? 'UNKNOWN',
    startedAt: formatTimestamp(start.timestamp),
    durationLabel: formatDuration(measuredDuration ?? range.durationMs),
    status: stepStatus(source.status),
    inputTokens: number(usage?.prompt_tokens),
    outputTokens: number(usage?.completion_tokens),
    totalTokens: number(usage?.total_tokens),
    errorType: text(source.failure?.error_type),
  }
}

function toolIntentFacts(records: TraceApiRecord[]): TraceToolActivityFacts {
  const source = records[records.length - 1] ?? records[0]
  const decision = valueText(source?.python_decision)
  return {
    phase: 'INTENT',
    toolName: text(source?.tool_name) ?? 'UNKNOWN',
    toolIntentId: text(source?.tool_intent_id),
    risk: valueText(source?.risk),
    preflightDecision: decision,
    guardDecision: decision === 'DENY' ? 'DENY' : undefined,
    status: source ? status(source.status) : 'RUNNING',
  }
}

function toolResultFacts(record: TraceApiRecord): TraceToolActivityFacts {
  const resultStatus = valueText(record.tool_result_status) ?? status(record.status)
  return {
    phase: 'RESULT',
    toolName: text(record.tool_name) ?? 'UNKNOWN',
    toolIntentId: text(record.tool_intent_id),
    toolCallId: text(record.java_tool_call_id),
    status: resultStatus,
    toolResultStatus: resultStatus,
    hasData: boolean(record.has_data),
    sanitized: boolean(record.sanitized),
    truncated: boolean(record.truncated),
    violationCode: text(record.java_error_code),
    resultSummary: text(record.result_summary),
  }
}

function approvalFacts(record: TraceApiRecord, decision?: TraceApiRecord): TraceApprovalFacts {
  return {
    toolIntentId: text(record.intent_id) ?? text(decision?.intent_id) ?? 'UNKNOWN',
    decision: valueText(decision?.decision) ?? valueText(record.decision),
    reason: text(record.reason),
  }
}

function evidenceFacts(record: TraceApiRecord): TraceContextEvidenceFacts {
  const reference = asMap(record.reference)
  const evidence = Array.isArray(reference?.evidence_references)
    ? reference.evidence_references.map((item): TraceContextEvidenceFacts['evidence'][number] | null => {
      const evidenceReference = asMap(item)
      if (!evidenceReference) return null
      const sourceType = text(evidenceReference.source_type)
      const sourceId = valueText(evidenceReference.source_id)
      if (!sourceType || !sourceId) return null
      return {
        sourceType,
        sourceId,
        documentId: text(evidenceReference.document_id),
        chunkId: text(evidenceReference.chunk_id),
        location: text(evidenceReference.location),
      }
    }).filter((item): item is TraceContextEvidenceFacts['evidence'][number] => item !== null)
    : []
  return {
    ragQueryId: text(reference?.rag_query_id),
    query: text(asMap(record.query_digest)?.summary),
    contextSources: [text(record.retrieval_kind) ?? 'UNKNOWN'],
    evidence,
    memoryId: text(reference?.memory_id),
  }
}

function makeStep(
  id: string,
  index: number,
  name: string,
  source: TraceSource,
  kind: TraceStepKind,
  records: TraceApiRecord[],
  fallback: TraceApiRecord,
  parentId: string | undefined,
  parentStep: string,
  detail: TraceStepDetail,
  expandable = false,
): TraceStep {
  const range = timeRange(records, fallback)
  return {
    id,
    index: String(index),
    name,
    source,
    status: detail.status,
    kind,
    startMs: range.start,
    durationMs: range.durationMs,
    depth: parentId ? 1 : 0,
    parentId,
    expandable,
    detail: { ...detail, parentStep },
  }
}

function relativeTimes(steps: TraceStep[], traceStart: number) {
  return steps.map((step) => ({
    ...step,
    startMs: Math.max(0, step.startMs - traceStart),
  }))
}

function finalResult(records: TraceApiRecord[]) {
  for (const record of records) {
    if (record.record_type !== 'retrieval') continue
    const reportId = text(asMap(record.reference)?.report_id)
    if (reportId) return `Report reference: ${reportId}`
  }
  return 'UNKNOWN'
}

function observationFacts(records: TraceApiRecord[], finalStatus: TraceStatus): TraceObservationFacts {
  const toolIntents = new Set(
    records
      .filter((record) => record.record_type === 'tool_intent')
      .map((record) => text(record.tool_intent_id))
      .filter((value): value is string => Boolean(value)),
  )
  const evidenceReferenceCount = records
    .filter((record) => record.record_type === 'retrieval')
    .reduce((count, record) => {
      const references = asMap(record.reference)?.evidence_references
      return count + (Array.isArray(references) ? references.length : 0)
    }, 0)
  const guardCount = new Set(
    records
      .filter((record) => record.record_type === 'safety_violation' || (record.record_type === 'tool_intent' && record.python_decision !== null && record.python_decision !== undefined))
      .map((record) => `${record.record_type}:${record.sequence ?? record.timestamp}`),
  ).size
  return {
    contextEvidenceCount: records.filter((record) => record.record_type === 'retrieval').length,
    evidenceReferenceCount,
    toolIntentCount: toolIntents.size,
    guardCount,
    hitlCount: records.filter((record) => record.record_type === 'approval' || record.record_type === 'interrupt' || record.record_type === 'resume').length,
    javaToolResultCount: records.filter((record) => record.record_type === 'tool_result').length,
    finalStatus,
    finalResult: finalResult(records),
  }
}

export function toTraceRecord(input: TraceApiRecord[]): TraceRecord | null {
  const records = sortRecords(input)
  const first = records[0]
  if (!first) return null
  const traceId = first.trace_id
  const runRecords = records.filter((record) => record.record_type === 'agent_run')
  const terminalRun = lastOf(runRecords, 'TERMINAL')
  const lifecycleRecords = records.filter((record) => record.event === 'TERMINAL' || record.event === 'INTERRUPT')
  const finalStatus = status(lifecycleRecords[lifecycleRecords.length - 1]?.status ?? records[records.length - 1]?.status)
  const agentRunId = records.map((record) => record.agent_run_id).find(Boolean) ?? 'UNKNOWN'
  const traceRange = timeRange(records, first)
  const traceStart = traceRange.start
  const consumed = new Set<TraceApiRecord>()
  const steps: TraceStep[] = []
  const root = terminalRun ?? firstOf(runRecords, 'START') ?? runRecords[0]
  let rootId: string | undefined
  if (root) {
    rootId = 'agent-run'
    const rootRecords = runRecords.length ? runRecords : [root]
    rootRecords.forEach((record) => consumed.add(record))
    const rootDetail = detailBase(rootRecords, root, 'PYTHON', 'Trace', 'UNKNOWN', 'UNKNOWN', terminalRun ?? root)
    steps.push(makeStep(rootId, 1, 'Agent Run', 'PYTHON', 'AGENT', rootRecords, root, undefined, 'Trace', rootDetail, true))
  }

  const agentStepGroups = groupBy(records.filter((record) => record.record_type === 'agent_step'), (record) => text(record.agent_step_id))
  const agentStepNames = new Map<string, string>()
  agentStepGroups.forEach((group, agentStepId) => {
    group.forEach((record) => consumed.add(record))
    const start = firstOf(group, 'START') ?? group[0]
    const terminal = lastOf(group, 'TERMINAL')
    const id = `agent-step:${agentStepId}`
    const name = text((terminal ?? start).step_type) ?? 'Agent Step'
    agentStepNames.set(agentStepId, name)
    const detail = detailBase(group, start, 'PYTHON', root ? 'Agent Run' : 'Trace', 'UNKNOWN', 'UNKNOWN', terminal ?? start)
    detail.agentRunId = agentRunId
    detail.agentStepId = agentStepId
    steps.push(makeStep(id, 0, name, 'PYTHON', 'TASK', group, start, rootId, root ? 'Agent Run' : 'Trace', detail, true))
  })

  const parentFor = (record: TraceApiRecord) => {
    const agentStepId = text(record.agent_step_id)
    return agentStepId ? `agent-step:${agentStepId}` : rootId
  }
  const parentNameFor = (record: TraceApiRecord) => {
    const agentStepId = text(record.agent_step_id)
    return agentStepId ? agentStepNames.get(agentStepId) ?? 'Agent Step' : root ? 'Agent Run' : 'Trace'
  }

  const modelGroups = groupBy(records.filter((record) => record.record_type === 'model_call'), (record) => text(record.model_call_id))
  modelGroups.forEach((group, modelCallId) => {
    group.forEach((record) => consumed.add(record))
    const start = firstOf(group, 'START') ?? group[0]
    const terminal = lastOf(group, 'TERMINAL')
    const facts = modelFacts(group, start, terminal)
    const detail = detailBase(group, start, 'PYTHON', parentNameFor(start), digestText(start.model_input), digestText(terminal?.model_output), terminal ?? start)
    detail.agentRunId = agentRunId
    detail.agentStepId = text(start.agent_step_id)
    detail.modelCallId = modelCallId
    detail.modelCall = facts
    steps.push(makeStep(`model-call:${modelCallId}`, 0, 'ModelCall', 'PYTHON', 'MODEL', group, start, parentFor(start), parentNameFor(start), detail))
  })

  const intentGroups = groupBy(records.filter((record) => record.record_type === 'tool_intent'), (record) => text(record.tool_intent_id))
  intentGroups.forEach((group, toolIntentId) => {
    group.forEach((record) => consumed.add(record))
    const start = group[0]
    const toolName = text(start.tool_name) ?? 'ToolIntent'
    const detail = detailBase(group, start, 'PYTHON', parentNameFor(start), digestText(start.arguments_digest), 'UNKNOWN')
    detail.agentRunId = agentRunId
    detail.agentStepId = text(start.agent_step_id)
    detail.toolIntentId = toolIntentId
    detail.toolActivity = toolIntentFacts(group)
    detail.decision = valueText(group[group.length - 1]?.python_decision)
    steps.push(makeStep(`tool-intent:${toolIntentId}`, 0, `ToolIntent · ${toolName}`, 'PYTHON', 'TOOL', group, start, parentFor(start), parentNameFor(start), detail))
  })

  records.filter((record) => !consumed.has(record)).forEach((record) => {
    consumed.add(record)
    const sequence = record.sequence ?? steps.length + 1
    const parentId = parentFor(record)
    const parentStep = parentNameFor(record)
    let source: TraceSource = 'PYTHON'
    let kind: TraceStepKind = 'TASK'
    let name = record.record_type
    let input = 'UNKNOWN'
    let output = 'UNKNOWN'
    let detail = detailBase([record], record, source, parentStep, input, output)
    detail.agentRunId = agentRunId
    detail.agentStepId = text(record.agent_step_id)

    if (record.record_type === 'tool_result') {
      source = 'JAVA'
      kind = 'TOOL'
      name = 'Java ToolResult'
      output = text(record.result_summary) ? JSON.stringify({ summary: record.result_summary }, null, 2) : 'UNKNOWN'
      detail = detailBase([record], record, source, parentStep, input, output)
      detail.agentRunId = agentRunId
      detail.agentStepId = text(record.agent_step_id)
      detail.toolIntentId = text(record.tool_intent_id)
      detail.toolCallId = text(record.java_tool_call_id)
      detail.toolActivity = toolResultFacts(record)
    } else if (record.record_type === 'retrieval') {
      source = 'JAVA'
      kind = 'TASK'
      name = text(record.retrieval_kind) ?? 'Context / Evidence'
      detail = detailBase([record], record, source, parentStep, digestText(record.query_digest), 'UNKNOWN')
      detail.agentRunId = agentRunId
      detail.agentStepId = text(record.agent_step_id)
      detail.ragQueryId = text(asMap(record.reference)?.rag_query_id)
      detail.contextEvidence = evidenceFacts(record)
    } else if (record.record_type === 'approval' || record.record_type === 'interrupt' || record.record_type === 'resume') {
      name = record.record_type === 'approval' ? 'HITL Approval' : record.record_type === 'interrupt' ? 'HITL Interrupt' : 'HITL Resume'
      const decision = record.record_type === 'approval' && record.event === 'DECISION' ? record : undefined
      detail = detailBase([record], record, source, parentStep, input, output)
      detail.agentRunId = agentRunId
      detail.agentStepId = text(record.agent_step_id)
      detail.toolIntentId = text(record.intent_id)
      detail.decision = valueText(record.decision) ?? (record.record_type === 'interrupt' ? 'INTERRUPTED' : record.record_type === 'resume' ? 'RESUMED' : undefined)
      detail.approval = approvalFacts(record, decision)
    } else if (record.record_type === 'safety_violation') {
      name = 'Guard / Safety'
      detail.toolIntentId = undefined
      detail.toolActivity = {
        phase: 'INTENT',
        toolName: text(record.tool_name) ?? 'UNKNOWN',
        guardDecision: 'DENY',
        status: status(record.status),
        violationCode: text(record.code),
      }
    }

    if (record.record_type === 'tool_result' || record.record_type === 'retrieval') kind = record.record_type === 'tool_result' ? 'TOOL' : 'TASK'
    steps.push(makeStep(`${record.record_type}:${sequence}`, 0, name, source, kind, [record], record, parentId, parentStep, detail))
  })

  const orderedSteps = relativeTimes(steps.sort((left, right) => left.startMs - right.startMs), traceStart)
  orderedSteps.forEach((step, index) => { step.index = index === 0 ? '1' : `1.${index}`; step.depth = step.parentId ? 1 : 0 })
  const modelCalls = new Set(records.filter((record) => record.record_type === 'model_call').map((record) => text(record.model_call_id)).filter((value): value is string => Boolean(value))).size
  const toolResults = records.filter((record) => record.record_type === 'tool_result')
  const runId = records
    .map((record) => record.record_type === 'java_run_reference' ? record.java_run_id : record.record_type === 'retrieval' ? asMap(record.reference)?.run_id : undefined)
    .map(valueText)
    .find(Boolean) ?? 'UNKNOWN'
  const tags: Array<'TOOL' | 'MODEL'> = []
  if (modelCalls) tags.push('MODEL')
  if (records.some((record) => record.record_type === 'tool_intent' || record.record_type === 'tool_result' || record.record_type === 'safety_violation' || record.record_type === 'approval')) tags.push('TOOL')
  const finalFacts = observationFacts(records, finalStatus)
  const stepTypes = records.map((record) => text(record.step_type)).filter((value): value is string => Boolean(value))
  const isDiagnosis = stepTypes.some((stepType) => stepType.startsWith('diagnosis'))
  const isGeneration = stepTypes.some((stepType) => ['context_enrichment', 'generate', 'validate', 'repair', 'accept', 'reject'].includes(stepType))
  return {
    id: traceId,
    status: finalStatus,
    name: isDiagnosis ? 'Diagnosis Workflow' : isGeneration ? 'TestCase Generation' : 'Agent Workflow',
    agentRunId,
    traceId,
    runId,
    startedAt: formatTimestamp(first.timestamp),
    steps: orderedSteps,
    stepCount: orderedSteps.length,
    durationLabel: formatDuration(traceRange.durationMs),
    durationMs: traceRange.durationMs,
    relativeTime: relativeTime(records[records.length - 1]?.timestamp),
    tags,
    modelCalls,
    toolCalls: toolResults.length,
    environment: 'UNKNOWN',
    agentRuntime: 'Python AgentLab',
    correlatedSystems: records.some((record) => record.record_type === 'tool_result' || record.record_type === 'retrieval' || record.record_type === 'java_run_reference')
      ? 'Python AgentLab + Java Platform'
      : 'Python AgentLab only',
    identities: [
      { label: 'traceId', value: traceId },
      { label: 'agentRunId', value: agentRunId },
      { label: 'runId', value: runId },
    ],
    observationFacts: finalFacts,
  }
}

function relativeTime(value: string | undefined) {
  if (!value || timestampMs(value) === null) return 'UNKNOWN'
  const ageMs = Math.max(0, Date.now() - (timestampMs(value) ?? Date.now()))
  if (ageMs < 60_000) return 'just now'
  const minutes = Math.floor(ageMs / 60_000)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  return `${Math.floor(hours / 24)} days ago`
}

export function groupTraceRecords(records: TraceApiRecord[]) {
  const groups = new Map<string, TraceApiRecord[]>()
  records.forEach((record) => {
    const group = groups.get(record.trace_id) ?? []
    group.push(record)
    groups.set(record.trace_id, group)
  })
  return [...groups.values()]
    .map(toTraceRecord)
    .filter((trace): trace is TraceRecord => trace !== null)
    .sort((left, right) => (right.steps[0]?.startMs ?? 0) - (left.steps[0]?.startMs ?? 0))
}
