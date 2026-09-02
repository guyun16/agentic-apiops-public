import type { TraceRecord, TraceSource, TraceStep, TraceStepDetail, TraceStepKind } from './types'

export const defaultTraceId = 'trace-diagnosis-001'

const ragInput = JSON.stringify(
  {
    query: 'failure stack trace root cause',
    top_k: 5,
    filters: {
      type: 'document',
      tags: ['test-report', 'error'],
    },
  },
  null,
  2,
)

const ragOutput = JSON.stringify(
  {
    results: [
      {
        docId: 'doc_8a1f2c',
        score: 0.892,
        title: 'NullPointerException in OrderService',
        snippet: '... at OrderService.process ...',
        source: 'confluence://kb/12345',
      },
    ],
    retrieved: 5,
  },
  null,
  2,
)

const emptyInput = JSON.stringify({ context: 'inherited from parent step' }, null, 2)
const emptyOutput = JSON.stringify({ status: 'completed' }, null, 2)

function formatDuration(durationMs: number) {
  return durationMs >= 1000 ? `${(durationMs / 1000).toFixed(2)} s` : `${durationMs} ms`
}

function formatTime(durationMs: number) {
  return `${(durationMs / 1000).toFixed(2)} s (${durationMs} ms)`
}

function createDetail(
  name: string,
  source: TraceSource,
  startMs: number,
  durationMs: number,
  parentStep: string,
  traceId: string,
  overrides: Partial<TraceStepDetail> = {},
): TraceStepDetail {
  return {
    status: 'SUCCESS',
    durationLabel: formatDuration(durationMs),
    traceId,
    parentStep,
    source,
    startTime: formatTime(startMs),
    endTime: formatTime(startMs + durationMs),
    input: emptyInput,
    output: emptyOutput,
    attributes: [
      { label: 'language', value: source === 'JAVA' ? 'Java' : 'Python' },
      { label: 'environment', value: 'DEMO' },
      { label: 'schemaVersion', value: 'v1' },
    ],
    ...overrides,
  }
}

function createStep(
  id: string,
  index: string,
  name: string,
  source: TraceSource,
  kind: TraceStepKind,
  startMs: number,
  durationMs: number,
  depth: number,
  traceId: string,
  parentId?: string,
  overrides: Partial<TraceStepDetail> = {},
): TraceStep {
  const detail = createDetail(name, source, startMs, durationMs, parentId ?? 'Agent Run', traceId, overrides)

  return {
    id,
    index,
    name,
    source,
    status: detail.status,
    kind,
    startMs,
    durationMs,
    depth,
    parentId,
    expandable: kind === 'AGENT' || kind === 'TASK',
    detail,
  }
}

const primaryTraceId = 'tr_8f2a7d91c3b4e6f8a9d0b5c7d2e1f123'
const primaryAgentRunId = 'ar_6f3c9b12'

const primarySteps: TraceStep[] = [
  createStep('agent-run', '1', 'Agent Run', 'PYTHON', 'AGENT', 0, 2840, 0, primaryTraceId),
  createStep('load-test-report', '1.1', 'load_test_report', 'PYTHON', 'TASK', 0, 312, 1, primaryTraceId, 'agent-run'),
  createStep('build-context', '1.2', 'build_context', 'PYTHON', 'TASK', 312, 276, 1, primaryTraceId, 'agent-run', {
    agentRunId: primaryAgentRunId,
    contextEvidence: {
      contextSources: ['TEST_REPORT', 'OPENAPI_METADATA'],
      totalChars: 1180,
      maxTotalChars: 4096,
      truncated: false,
      evidence: [
        {
          sourceType: 'TEST_REPORT',
          sourceId: 'report_0182',
          citation: 'HTTP 500 response and assertion snapshot',
        },
        {
          sourceType: 'OPENAPI_METADATA',
          sourceId: 'orders-api-v3',
          citation: 'POST /api/orders contract metadata',
        },
      ],
    },
  }),
  createStep('analyze-failure', '1.3', 'analyze_failure', 'PYTHON', 'TASK', 588, 412, 1, primaryTraceId, 'agent-run'),
  createStep('model-call-01', '1.4', 'model_call_01', 'PYTHON', 'MODEL', 1000, 712, 1, primaryTraceId, 'agent-run', {
    agentRunId: primaryAgentRunId,
    modelCall: {
      modelCallId: 'model_call_029_01',
      provider: 'OpenAI-compatible',
      model: 'gpt-5-mini',
      runtime: 'Python AgentLab',
      implementation: 'LangGraph Diagnosis Workflow',
      promptName: 'diagnosis',
      promptVersion: 'v2',
      startedAt: formatTime(1000),
      durationLabel: formatDuration(712),
      status: 'SUCCESS',
      inputTokens: 1284,
      outputTokens: 326,
      totalTokens: 1610,
      attempt: 1,
    },
    attributes: [
      { label: 'language', value: 'Python' },
      { label: 'modelName', value: 'gpt-5-mini' },
      { label: 'promptVersion', value: 'diagnosis-v2' },
      { label: 'environment', value: 'DEMO' },
    ],
  }),
  createStep('tool-intent', '1.5', 'tool_intent', 'PYTHON', 'TASK', 1712, 128, 1, primaryTraceId, 'agent-run', {
    agentRunId: primaryAgentRunId,
    agentStepId: 'step_004',
    toolIntentId: 'intent_041',
    toolActivity: {
      phase: 'INTENT',
      toolName: 'rag.search',
      toolIntentId: 'intent_041',
      risk: 'SENSITIVE_READ',
      preflightDecision: 'REQUIRE_APPROVAL',
      status: 'INTENT',
    },
  }),
  createStep('approval-required', '1.6', 'Approval Required', 'PYTHON', 'TASK', 1840, 60, 2, primaryTraceId, 'tool-intent', {
    agentRunId: primaryAgentRunId,
    toolIntentId: 'intent_041',
    decision: 'WAITING',
    status: 'WAITING',
    approval: {
      toolIntentId: 'intent_041',
      decision: 'WAITING',
      reason: 'Additional diagnostic evidence is needed to determine the root cause.',
    },
  }),
  createStep('workflow-paused', '1.7', 'Workflow Paused', 'PYTHON', 'TASK', 1900, 40, 2, primaryTraceId, 'tool-intent', {
    agentRunId: primaryAgentRunId,
    toolIntentId: 'intent_041',
    decision: 'PAUSED',
    status: 'WAITING',
    approval: {
      toolIntentId: 'intent_041',
      decision: 'PAUSED',
    },
  }),
  createStep('approved', '1.8', 'Approved', 'PYTHON', 'TASK', 1940, 40, 2, primaryTraceId, 'tool-intent', {
    agentRunId: primaryAgentRunId,
    toolIntentId: 'intent_041',
    decision: 'APPROVED',
    approval: {
      toolIntentId: 'intent_041',
      decision: 'APPROVED',
    },
  }),
  createStep('workflow-resumed', '1.9', 'Workflow Resumed', 'PYTHON', 'TASK', 1980, 82, 2, primaryTraceId, 'tool-intent', {
    agentRunId: primaryAgentRunId,
    toolIntentId: 'intent_041',
    decision: 'RESUMED',
    approval: {
      toolIntentId: 'intent_041',
      decision: 'RESUMED',
    },
  }),
  createStep('java-tool-gateway', '1.10', 'Java Tool Gateway', 'JAVA', 'TOOL', 2062, 90, 3, primaryTraceId, 'workflow-resumed', {
    toolIntentId: 'intent_041',
    toolCallId: 'java_tool_041',
    requestId: 'req_8821',
    traceId: primaryTraceId,
    toolActivity: {
      phase: 'GATEWAY',
      toolName: 'rag.search',
      toolIntentId: 'intent_041',
      toolCallId: 'java_tool_041',
      requestId: 'req_8821',
      authorizationResult: 'ALLOW',
      guardDecision: 'ALLOW',
      status: 'SUCCESS',
      latencyLabel: '90 ms',
    },
  }),
  createStep('rag-search', '1.11', 'rag.search', 'JAVA', 'TOOL', 2152, 138, 3, primaryTraceId, 'workflow-resumed', {
    toolIntentId: 'intent_041',
    toolCallId: 'java_tool_041',
    requestId: 'req_8821',
    traceId: primaryTraceId,
    parentStep: 'Java Tool Gateway (1.10)',
    input: ragInput,
    output: ragOutput,
    toolActivity: {
      phase: 'GATEWAY',
      toolName: 'rag.search',
      toolIntentId: 'intent_041',
      toolCallId: 'java_tool_041',
      requestId: 'req_8821',
      authorizationResult: 'ALLOW',
      guardDecision: 'ALLOW',
      status: 'SUCCESS',
      latencyLabel: '138 ms',
      sanitized: true,
      truncated: false,
      resultSummary: '1 cited project-scoped evidence item returned',
    },
    contextEvidence: {
      ragQueryId: 'rag_query_041',
      query: 'failure stack trace root cause',
      contextSources: ['RAG_DOCUMENT'],
      totalChars: 860,
      maxTotalChars: 4096,
      truncated: false,
      evidence: [
        {
          sourceType: 'RAG_DOCUMENT',
          sourceId: 'doc_8a1f2c',
          documentId: 'doc_8a1f2c',
          chunkId: 'chunk_03',
          location: 'confluence://kb/12345#L42',
          relevanceScore: 0.892,
          citation: '... at OrderService.process ...',
        },
      ],
    },
    attributes: [
      { label: 'retryCount', value: '0' },
      { label: 'timeoutMs', value: '5000' },
      { label: 'language', value: 'Java' },
      { label: 'modelName', value: '—' },
      { label: 'promptVersion', value: 'rag-search-v1' },
      { label: 'environment', value: 'DEMO' },
      { label: 'schemaVersion', value: 'v1' },
    ],
  }),
  createStep('java-tool-result', '1.12', 'Java Tool Result', 'JAVA', 'TOOL', 2290, 186, 3, primaryTraceId, 'workflow-resumed', {
    toolIntentId: 'intent_041',
    toolCallId: 'java_tool_041',
    requestId: 'req_8821',
    traceId: primaryTraceId,
    parentStep: 'Java Tool Gateway (1.10)',
    toolActivity: {
      phase: 'RESULT',
      toolName: 'rag.search',
      toolIntentId: 'intent_041',
      toolCallId: 'java_tool_041',
      requestId: 'req_8821',
      status: 'SUCCESS',
      latencyLabel: '186 ms',
      sanitized: true,
      truncated: false,
      resultSummary: 'Sanitized RAG result referenced by Python workflow',
    },
  }),
  createStep('model-call-02', '1.13', 'model_call_02', 'PYTHON', 'MODEL', 2476, 40, 1, primaryTraceId, 'agent-run', {
    agentRunId: primaryAgentRunId,
    modelCall: {
      modelCallId: 'model_call_029_02',
      provider: 'OpenAI-compatible',
      model: 'gpt-5-mini',
      runtime: 'Python AgentLab',
      implementation: 'LangGraph Diagnosis Workflow',
      promptName: 'diagnosis',
      promptVersion: 'v2',
      startedAt: formatTime(2476),
      durationLabel: formatDuration(40),
      status: 'SUCCESS',
      inputTokens: 416,
      outputTokens: 142,
      totalTokens: 558,
      attempt: 1,
    },
    attributes: [
      { label: 'language', value: 'Python' },
      { label: 'modelName', value: 'gpt-5-mini' },
      { label: 'promptVersion', value: 'diagnosis-v2' },
      { label: 'environment', value: 'DEMO' },
    ],
  }),
  createStep('finalize-diagnosis', '1.14', 'finalize_diagnosis', 'PYTHON', 'TASK', 2516, 324, 1, primaryTraceId, 'agent-run'),
]

const rejectedTraceId = 'tr_rejected_0176'
const rejectedAgentRunId = 'ar_rejected_0176'

const rejectedSteps: TraceStep[] = [
  createStep('rejected-agent-run', '1', 'Agent Run', 'PYTHON', 'AGENT', 0, 1280, 0, rejectedTraceId),
  createStep('rejected-load-report', '1.1', 'load_test_report', 'PYTHON', 'TASK', 0, 280, 1, rejectedTraceId, 'rejected-agent-run'),
  createStep('rejected-build-context', '1.2', 'build_context', 'PYTHON', 'TASK', 280, 240, 1, rejectedTraceId, 'rejected-agent-run'),
  createStep('rejected-analyze-failure', '1.3', 'analyze_failure', 'PYTHON', 'TASK', 520, 360, 1, rejectedTraceId, 'rejected-agent-run'),
  createStep('rejected-tool-intent', '1.4', 'Tool Intent', 'PYTHON', 'TASK', 880, 120, 1, rejectedTraceId, 'rejected-agent-run', {
    agentRunId: rejectedAgentRunId,
    agentStepId: 'step_004',
    toolIntentId: 'intent_042',
    toolActivity: {
      phase: 'INTENT',
      toolName: 'rag.search',
      toolIntentId: 'intent_042',
      risk: 'SENSITIVE_READ',
      preflightDecision: 'REQUIRE_APPROVAL',
      status: 'INTENT',
    },
  }),
  createStep('rejected-approval-required', '1.5', 'Approval Required', 'PYTHON', 'TASK', 1000, 80, 2, rejectedTraceId, 'rejected-tool-intent', {
    agentRunId: rejectedAgentRunId,
    toolIntentId: 'intent_042',
    decision: 'WAITING',
    status: 'WAITING',
    approval: {
      toolIntentId: 'intent_042',
      decision: 'WAITING',
      reason: 'Additional diagnostic evidence is needed to determine the root cause.',
    },
  }),
  createStep('rejected-decision', '1.6', 'Rejected', 'PYTHON', 'TASK', 1080, 80, 2, rejectedTraceId, 'rejected-tool-intent', {
    agentRunId: rejectedAgentRunId,
    toolIntentId: 'intent_042',
    decision: 'REJECTED',
    status: 'REJECTED',
    approval: {
      toolIntentId: 'intent_042',
      decision: 'REJECTED',
      reason: 'The requested tool action was rejected by the human approver.',
    },
  }),
  createStep('rejected-terminal', '1.7', 'Workflow Terminated', 'PYTHON', 'TASK', 1160, 120, 1, rejectedTraceId, 'rejected-agent-run', {
    agentRunId: rejectedAgentRunId,
    toolIntentId: 'intent_042',
    decision: 'TERMINAL',
    status: 'FAILED',
  }),
]

const deniedTraceId = 'tr_gateway_denied_003'

const deniedSteps: TraceStep[] = [
  createStep('denied-agent-run', '1', 'Agent Run', 'JAVA', 'AGENT', 0, 1720, 0, deniedTraceId),
  createStep('denied-load-report', '1.1', 'load_report', 'JAVA', 'TASK', 0, 420, 1, deniedTraceId, 'denied-agent-run'),
  createStep('denied-gateway', '1.2', 'Java Tool Gateway', 'JAVA', 'TOOL', 420, 110, 1, deniedTraceId, 'denied-agent-run', {
    toolActivity: {
      phase: 'GATEWAY',
      toolName: 'sql.read',
      toolCallId: 'java_tool_003',
      authorizationResult: 'ALLOW',
      guardDecision: 'DENY',
      status: 'SAFETY_VIOLATION',
      latencyLabel: '110 ms',
      violationCode: 'RESOURCE_GUARD_REJECTED',
    },
  }),
  createStep('denied-tool-result', '1.3', 'Tool Result', 'JAVA', 'TOOL', 530, 80, 1, deniedTraceId, 'denied-agent-run', {
    status: 'FAILED',
    toolCallId: 'java_tool_003',
    toolActivity: {
      phase: 'RESULT',
      toolName: 'sql.read',
      toolCallId: 'java_tool_003',
      status: 'DENIED',
      resultSummary: 'Tool execution was denied by the Java resource guard',
      violationCode: 'RESOURCE_GUARD_REJECTED',
    },
  }),
  createStep('denied-finalize', '1.4', 'finalize_diagnosis', 'JAVA', 'TASK', 610, 140, 1, deniedTraceId, 'denied-agent-run', {
    status: 'FAILED',
  }),
]

function createCompactSteps(traceId: string, durationMs: number, source: TraceSource, names: string[]) {
  const slice = Math.max(140, Math.floor(durationMs / names.length))
  return names.map((name, index) => {
    const startMs = Math.min(index * slice, Math.max(0, durationMs - slice))
    return createStep(
      `${traceId}-${index}`,
      `${index + 1}`,
      name,
      source,
      name.includes('model') ? 'MODEL' : name.includes('search') || name.includes('tool') ? 'TOOL' : 'TASK',
      startMs,
      Math.min(slice - 12, durationMs - startMs),
      0,
      traceId,
    )
  })
}

function createTrace(
  id: string,
  name: string,
  status: 'SUCCESS' | 'FAILED',
  agentRunId: string,
  traceId: string,
  runId: string,
  stepCount: number,
  durationMs: number,
  relativeTime: string,
  steps: TraceStep[],
  tags: Array<'TOOL' | 'MODEL'>,
  modelCalls: number,
  toolCalls: number,
  agentRuntime = 'Python AgentLab · LangGraph',
  correlatedSystems = 'Python AgentLab only',
): TraceRecord {
  return {
    id,
    name,
    status,
    agentRunId,
    traceId,
    runId,
    steps,
    stepCount,
    durationLabel: formatDuration(durationMs),
    durationMs,
    relativeTime,
    tags,
    modelCalls,
    toolCalls,
    environment: 'DEMO',
    agentRuntime,
    correlatedSystems,
    identities: [
      { label: 'traceId', value: traceId },
      { label: 'agentRunId', value: agentRunId },
      { label: 'runId', value: runId },
    ],
  }
}

export const traceRecords: TraceRecord[] = [
  createTrace(
    defaultTraceId,
    'Diagnosis Workflow',
    'SUCCESS',
    'ar_6f3c9b12',
    'tr_8f2a7d91',
    'run_0182',
    15,
    2840,
    '2 min ago',
    primarySteps,
    ['TOOL', 'MODEL'],
    2,
    1,
    'Python AgentLab · LangGraph',
    'Python AgentLab + Java Platform',
  ),
  createTrace(
    'trace-diagnosis-rejected-005',
    'Diagnosis Workflow · Rejected',
    'FAILED',
    rejectedAgentRunId,
    rejectedTraceId,
    'run_0176',
    8,
    1280,
    '29 min ago',
    rejectedSteps,
    ['TOOL'],
    1,
    0,
    'Python AgentLab · LangGraph',
    'Python AgentLab (Java Gateway not reached)',
  ),
  createTrace(
    'trace-testcase-002',
    'TestCase Generation',
    'SUCCESS',
    'ar_3cd49d21',
    'tr_1b7e2f44',
    'run_0178',
    9,
    4310,
    '8 min ago',
    createCompactSteps('tr_1b7e2f44', 4310, 'PYTHON', ['Agent Run', 'load_metadata', 'build_strategy', 'model_call_01', 'model_call_02', 'validate_dsl']),
    ['MODEL'],
    3,
    0,
  ),
  createTrace(
    'trace-tool-use-003',
    'Tool-use Diagnosis',
    'FAILED',
    'ar_9e7d2c11',
    deniedTraceId,
    'run_0174',
    5,
    1720,
    '15 min ago',
    deniedSteps,
    ['TOOL'],
    1,
    1,
    'Java Agent · Spring AI',
    'Java Platform only',
  ),
  createTrace(
    'trace-diagnosis-004',
    'Diagnosis Workflow',
    'SUCCESS',
    'ar_7b5e1a88',
    'tr_6a4d2c18',
    'run_0172',
    7,
    2170,
    '21 min ago',
    createCompactSteps('tr_6a4d2c18', 2170, 'PYTHON', ['Agent Run', 'load_report', 'build_context', 'model_call_01', 'finalize_diagnosis']),
    ['MODEL'],
    2,
    0,
  ),
]

export const defaultStepId = 'rag-search'

export function getTrace(traceId: string) {
  return traceRecords.find((trace) => trace.id === traceId) ?? traceRecords[0]
}
