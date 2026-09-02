import type { RunCase, RunFilter, RunRecord, RunResponse } from './types'

export const defaultRunId = 'run_0182'

export const runFilterOptions: Array<{ label: string; value: RunFilter; count: number }> = [
  { label: 'All', value: 'ALL', count: 142 },
  { label: 'Success', value: 'SUCCESS', count: 96 },
  { label: 'Failed', value: 'FAILED', count: 28 },
  { label: 'Running', value: 'RUNNING', count: 3 },
  { label: 'Pending', value: 'PENDING', count: 1 },
  { label: 'Cancelled', value: 'CANCELLED', count: 1 },
]

const orderRequestBody = JSON.stringify(
  {
    customerId: 'cust_2048',
    items: [
      {
        productId: 'prod_1001',
        quantity: 2,
        unitPrice: 49.99,
      },
    ],
    shippingAddress: {
      street: '100 Market Street',
      city: 'San Francisco',
      state: 'CA',
      postalCode: '94105',
      country: 'US',
    },
    notes: 'Leave package at reception',
  },
  null,
  2,
)

const orderResponseBody = JSON.stringify(
  {
    id: 'ord_8f31a2',
    status: 'CONFIRMED',
    customerId: 'cust_2048',
    total: 99.98,
    items: [
      {
        productId: 'prod_1001',
        quantity: 2,
      },
    ],
  },
  null,
  2,
)

const orderRequest = {
  method: 'POST' as const,
  url: 'https://demo.apiops.local/api/orders',
  headers: [
    { name: 'Content-Type', value: 'application/json' },
    { name: 'Authorization', value: 'Bearer ••••••••••••' },
    { name: 'X-Request-Id', value: 'req_7b1e90' },
  ],
  body: orderRequestBody,
}

const orderResponse = {
  status: 201,
  statusText: 'Created',
  duration: '512 ms',
  headers: [
    { name: 'Content-Type', value: 'application/json' },
    { name: 'X-Trace-Id', value: 'trace_4f8e2b9c3d5a4e1b' },
  ],
  body: orderResponseBody,
}

const noResponse: RunResponse = {
  status: '—',
  statusText: 'No response',
  duration: '—',
  headers: [],
  body: '',
}

const assertions = [
  {
    id: 'status-code',
    type: 'STATUS_CODE',
    title: 'Response status code',
    expected: '201',
    actual: '201',
    details: 'HTTP status code matches expected value',
    status: 'PASS' as const,
  },
  {
    id: 'json-schema',
    type: 'JSON_SCHEMA',
    title: 'Response matches order schema',
    expected: 'Valid against order-schema-v1.json',
    actual: 'Valid',
    details: 'Response body conforms to JSON schema',
    status: 'PASS' as const,
  },
  {
    id: 'json-path',
    type: 'JSON_PATH',
    title: '$.items is not empty',
    expected: 'Array with at least 1 item',
    actual: '[] (empty array)',
    details: 'Expected array to have at least 1 item but was empty',
    status: 'FAIL' as const,
  },
  {
    id: 'response-time',
    type: 'RESPONSE_TIME',
    title: 'Response time is less than 1000 ms',
    expected: '< 1000 ms',
    actual: '512 ms',
    details: 'Response time is within acceptable threshold',
    status: 'PASS' as const,
  },
]

const timeline = [
  { label: 'Run started', offset: '0 ms', tone: 'success' as const },
  { label: 'Request sent', offset: '+11 ms', tone: 'accent' as const },
  { label: 'Response received', offset: '+367 ms', tone: 'accent' as const },
  { label: 'Assertion failed', offset: '+379 ms', tone: 'danger' as const },
  { label: 'Run completed', offset: '+512 ms', tone: 'neutral' as const },
]

const selectedRunCases: RunCase[] = [
  {
    id: 'TC_POST_CREATE_ORDER_HAPPY_PATH_001',
    name: 'Create Order · Happy Path',
    status: 'ASSERTION_FAILED',
    failureType: 'ASSERTION_MISMATCH',
    summary: 'One response assertion did not match the contract.',
    steps: [
      {
        id: 'step-create-order-request',
        name: 'Create order request',
        status: 'SUCCESS',
        failureType: 'NONE',
        method: 'POST',
        path: '/api/orders',
        duration: '301 ms',
        responseStatus: 201,
        assertions: [],
      },
      {
        id: 'step-evaluate-response',
        name: 'Evaluate response assertions',
        status: 'ASSERTION_FAILED',
        failureType: 'ASSERTION_MISMATCH',
        duration: '211 ms',
        responseStatus: 201,
        assertions,
      },
    ],
  },
]

const selectedRun: RunRecord = {
  id: defaultRunId,
  status: 'ASSERTION_FAILED',
  failureType: 'ASSERTION_MISMATCH',
  method: 'POST',
  endpoint: '/api/orders',
  summary: 'Create Order · Happy Path',
  relativeTime: '5m ago',
  duration: '512 ms',
  httpStatus: 201,
  started: 'May 21, 2025 10:15:32 AM',
  completed: 'May 21, 2025 10:15:33 AM',
  assertionsPassed: 3,
  assertionsTotal: 4,
  environment: 'DEMO',
  executedBy: 'Java Platform',
  caseId: 'TC_POST_CREATE_ORDER_HAPPY_PATH_001',
  traceId: 'trace_4f8e2b9c3d5a4e1b',
  triggeredBy: 'scheduled-job',
  request: orderRequest,
  response: orderResponse,
  assertions,
  cases: selectedRunCases,
  timeline,
}

const successRun: RunRecord = {
  ...selectedRun,
  id: 'run_0181',
  status: 'SUCCESS',
  failureType: 'NONE',
  relativeTime: '2m ago',
  duration: '423 ms',
  assertionsPassed: 4,
  caseId: 'TC_POST_CREATE_ORDER_HAPPY_PATH_000',
  traceId: 'trace_2a7b9d1e4c6f8a0b',
  response: { ...orderResponse, duration: '423 ms' },
  assertions: assertions.map((assertion) => ({ ...assertion, status: 'PASS' as const })),
  cases: undefined,
  timeline: timeline.map((step) => (step.label === 'Assertion failed' ? { ...step, label: 'Assertions passed', tone: 'success' as const } : step)),
}

const runs: RunRecord[] = [
  selectedRun,
  successRun,
  {
    ...successRun,
    id: 'run_0180',
    method: 'GET',
    endpoint: '/api/orders/{orderId}',
    summary: 'Fetch Order · Existing ID',
    relativeTime: '7m ago',
    duration: '298 ms',
    httpStatus: 200,
    caseId: 'TC_GET_ORDER_EXISTING_014',
    traceId: 'trace_7c4d8a1f2b6e90ad',
    request: { ...orderRequest, method: 'GET', url: 'https://demo.apiops.local/api/orders/ord_8f31a2', body: '' },
    response: { ...orderResponse, status: 200, statusText: 'OK', duration: '298 ms' },
    cases: undefined,
  },
  {
    ...selectedRun,
    id: 'run_0179',
    status: 'TIMEOUT',
    failureType: 'TIMEOUT',
    relativeTime: '9m ago',
    duration: '10.0 s',
    httpStatus: '—',
    caseId: 'TC_POST_CREATE_ORDER_TIMEOUT_006',
    traceId: 'trace_1f9d6a3b8c2e7a40',
    response: { ...orderResponse, status: 504, statusText: 'Gateway Timeout', duration: '10.0 s' },
    assertionsPassed: 0,
    assertionsTotal: 0,
    assertions: [],
    cases: undefined,
    timeline: [
      { label: 'Run started', offset: '0 ms', tone: 'success' as const },
      { label: 'Request sent', offset: '+12 ms', tone: 'accent' as const },
      { label: 'Run timed out', offset: '+10.0 s', tone: 'danger' as const },
    ],
  },
  {
    ...successRun,
    id: 'run_0178',
    relativeTime: '12m ago',
    duration: '387 ms',
    caseId: 'TC_POST_CREATE_ORDER_HAPPY_PATH_009',
    traceId: 'trace_6e4c1a8b9d2f70c3',
    response: { ...orderResponse, duration: '387 ms' },
    cases: undefined,
  },
  {
    ...selectedRun,
    id: 'run_0183',
    status: 'RUNNING',
    failureType: 'NONE',
    relativeTime: 'Just now',
    duration: '—',
    httpStatus: '—',
    caseId: 'TC_POST_CREATE_ORDER_BOUNDARY_003',
    traceId: 'trace_9a2b7c4d1e6f80ab',
    completed: 'Pending',
    assertionsPassed: 0,
    assertionsTotal: 0,
    assertions: [],
    cases: undefined,
    response: noResponse,
    timeline: [
      { label: 'Run pending', offset: '0 ms', tone: 'neutral' as const },
      { label: 'Run started', offset: '+18 ms', tone: 'success' as const },
    ],
  },
  {
    ...selectedRun,
    id: 'run_0177',
    relativeTime: '18m ago',
    duration: '611 ms',
    caseId: 'TC_POST_CREATE_ORDER_MISSING_REQUIRED_002',
    traceId: 'trace_8b4d1e6f2a9c70de',
    response: { ...orderResponse, duration: '611 ms' },
    cases: undefined,
  },
  {
    ...successRun,
    id: 'run_0176',
    status: 'EXECUTION_FAILED',
    failureType: 'CONNECT_ERROR',
    method: 'DELETE',
    endpoint: '/api/orders/{orderId}',
    summary: 'Delete Order · Missing ID',
    relativeTime: '22m ago',
    duration: '86 ms',
    httpStatus: '—',
    caseId: 'TC_DELETE_ORDER_EXECUTION_003',
    traceId: 'trace_3d7a1c9e4b6f20ab',
    response: noResponse,
    assertionsPassed: 0,
    assertionsTotal: 0,
    assertions: [],
    cases: undefined,
    timeline: [
      { label: 'Run started', offset: '0 ms', tone: 'success' as const },
      { label: 'Request sent', offset: '+9 ms', tone: 'accent' as const },
      { label: 'Execution failed', offset: '+86 ms', tone: 'danger' as const },
    ],
  },
  {
    ...successRun,
    id: 'run_0184',
    status: 'PENDING',
    failureType: 'NONE',
    relativeTime: 'Just now',
    duration: '—',
    httpStatus: '—',
    started: 'Not started',
    completed: '—',
    caseId: 'TC_POST_CREATE_ORDER_PENDING_010',
    traceId: 'trace_0a1b2c3d4e5f6071',
    response: noResponse,
    assertionsPassed: 0,
    assertionsTotal: 0,
    assertions: [],
    cases: undefined,
    timeline: [{ label: 'Run pending', offset: '0 ms', tone: 'neutral' as const }],
  },
  {
    ...successRun,
    id: 'run_0175',
    status: 'CANCELLED',
    failureType: 'NONE',
    relativeTime: '31m ago',
    duration: '—',
    httpStatus: '—',
    started: 'May 21, 2025 09:58:10 AM',
    completed: 'May 21, 2025 09:58:10 AM',
    caseId: 'TC_POST_CREATE_ORDER_CANCELLED_004',
    traceId: 'trace_5c8d2a1e7f4b9063',
    response: noResponse,
    assertionsPassed: 0,
    assertionsTotal: 0,
    assertions: [],
    cases: undefined,
    timeline: [
      { label: 'Run pending', offset: '0 ms', tone: 'neutral' as const },
      { label: 'Run cancelled', offset: '+42 ms', tone: 'neutral' as const },
    ],
  },
]

export const runRecords = runs

export function getRun(id: string) {
  return runRecords.find((run) => run.id === id) ?? runRecords[0]
}
