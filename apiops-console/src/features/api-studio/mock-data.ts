import type {
  AgentRuntimeOption,
  ApiDocumentVersion,
  ApiEndpoint,
  ApiResponse,
  ApiService,
  GenerationOutcome,
  StrategyId,
  StrategyOption,
  TestCaseAgentRuntime,
} from './types'

export const defaultEndpointId = 'create-order'
export const defaultDocumentVersionId = 'api_doc_orders_v2'
export const defaultStrategy: StrategyId = 'HAPPY_PATH'
export const defaultAgentRuntime: TestCaseAgentRuntime = 'JAVA_AGENT'

export const agentRuntimeOptions: AgentRuntimeOption[] = [
  {
    id: 'JAVA_AGENT',
    label: 'Java Agent',
    implementation: 'Spring AI',
    workflow: 'GenerateTestCaseAgent',
    generatedBy: 'Java Agent · Spring AI',
  },
  {
    id: 'PYTHON_AGENTLAB',
    label: 'Python AgentLab',
    implementation: 'LangGraph',
    workflow: 'Generator Workflow',
    generatedBy: 'Python AgentLab · LangGraph',
  },
]

export const strategyOptions: StrategyOption[] = [
  { id: 'HAPPY_PATH', label: 'Happy Path' },
  { id: 'MISSING_REQUIRED', label: 'Missing Required' },
  { id: 'BOUNDARY', label: 'Boundary' },
  { id: 'AUTH_FAILURE', label: 'Auth Failure' },
  { id: 'IDEMPOTENCY', label: 'Idempotency' },
  { id: 'BUSINESS_ERROR', label: 'Business Error' },
]

const orderRequestBody = `{
  "customerId": "string",
  "items": [
    {
      "productId": "string",
      "quantity": 1,
      "unitPrice": 0
    }
  ],
  "shippingAddress": {
    "street": "string",
    "city": "string",
    "state": "string",
    "postalCode": "string",
    "country": "string"
  },
  "notes": "string"
}`

const orderRequestSchema = `{
  "type": "object",
  "required": ["customerId", "items", "shippingAddress"],
  "properties": {
    "customerId": { "type": "string" },
    "items": { "type": "array", "minItems": 1 },
    "shippingAddress": { "$ref": "#/components/schemas/Address" }
  }
}`

const orderResponseSchema = `{
  "type": "object",
  "required": ["id", "status", "items"],
  "properties": {
    "id": { "type": "string" },
    "status": { "type": "string" },
    "items": { "type": "array" }
  }
}`

const orderResponseExample = `{
  "id": "ord_1024",
  "status": "CREATED",
  "items": [{ "productId": "sku_001", "quantity": 1 }]
}`

const orderResponses: ApiResponse[] = [
  { status: '201', title: 'Created', description: 'Order created successfully', tone: 'success', schema: orderResponseSchema, example: orderResponseExample },
  { status: '400', title: 'Invalid Request', description: 'Validation failed for request payload', tone: 'warning', schema: '{ "type": "object", "properties": { "message": { "type": "string" } } }', example: '{ "message": "items must not be empty" }' },
  { status: '401', title: 'Unauthorized', description: 'Missing or invalid authentication', tone: 'danger', schema: '{ "type": "object", "properties": { "error": { "type": "string" } } }', example: '{ "error": "unauthorized" }' },
  { status: '409', title: 'Insufficient Stock', description: 'One or more items are out of stock', tone: 'warning', schema: '{ "type": "object", "properties": { "message": { "type": "string" } } }', example: '{ "message": "insufficient stock" }' },
  { status: '500', title: 'Internal Server Error', description: 'Unexpected server error', tone: 'danger', schema: '{ "type": "object", "properties": { "error": { "type": "string" } } }', example: '{ "error": "internal_error" }' },
]

export const apiDocumentVersions: ApiDocumentVersion[] = [
  {
    apiDocId: 'api_doc_orders_v2',
    sourceKey: 'orders-api',
    documentName: 'orders-openapi.yaml',
    openapiVersion: '3.0.3',
    title: 'Orders API',
    apiVersion: '1.2.0',
    documentFormat: 'YAML',
    versionNo: 2,
    status: 'ACTIVE',
    importedAt: '2025-05-22 14:18:04',
    updatedAt: '2025-05-22 14:18:04',
    endpointIds: ['list-orders', 'create-order', 'get-order', 'delete-order'],
  },
  {
    apiDocId: 'api_doc_orders_v1',
    sourceKey: 'orders-api',
    documentName: 'orders-openapi.yaml',
    openapiVersion: '3.0.3',
    title: 'Orders API',
    apiVersion: '1.0.0',
    documentFormat: 'YAML',
    versionNo: 1,
    status: 'ACTIVE',
    importedAt: '2025-05-08 09:42:18',
    updatedAt: '2025-05-08 09:42:18',
    endpointIds: ['list-orders', 'create-order', 'get-order', 'delete-order'],
  },
]

export const importedOrdersDocumentVersion: ApiDocumentVersion = {
  apiDocId: 'api_doc_orders_v3',
  sourceKey: 'orders-api',
  documentName: 'orders-openapi-v3.yaml',
  openapiVersion: '3.0.3',
  title: 'Orders API',
  apiVersion: '1.3.0',
  documentFormat: 'YAML',
  versionNo: 3,
  status: 'ACTIVE',
  importedAt: '2025-05-22 14:32:11',
  updatedAt: '2025-05-22 14:32:11',
  endpointIds: ['list-orders', 'create-order', 'get-order', 'delete-order'],
}

export const apiServices: ApiService[] = [
  {
    id: 'order-service',
    name: 'order-service',
    endpointIds: ['list-orders', 'create-order', 'get-order', 'delete-order'],
  },
  {
    id: 'inventory-service',
    name: 'inventory-service',
    endpointIds: [],
  },
]

export const apiEndpoints: ApiEndpoint[] = [
  {
    id: 'list-orders',
    apiDocId: defaultDocumentVersionId,
    service: 'order-service',
    method: 'GET',
    path: '/api/orders',
    title: 'List Orders',
    description: 'Returns orders for the authenticated user.',
    operationId: 'listOrders',
    version: 'v1',
    documentVersionNo: 2,
    openapiVersion: '3.0.3',
    security: 'Bearer JWT',
    securityRequirements: ['BearerAuth'],
    servers: ['https://api.demo.apio.ps'],
    tags: ['orders'],
    deprecated: false,
    parameters: [
      { name: 'page', location: 'query', required: false, description: 'Page number', schema: '{ "type": "integer", "minimum": 1 }', example: '1' },
      { name: 'pageSize', location: 'query', required: false, description: 'Items per page', schema: '{ "type": "integer", "minimum": 1, "maximum": 100 }', example: '20' },
    ],
    examples: [
      { name: 'list-orders-request', owner: 'request', summary: 'Default list request', value: '{\n  "page": 1,\n  "pageSize": 20\n}' },
    ],
    requestBodyExample: '{\n  "page": 1,\n  "pageSize": 20\n}',
    responses: [
      { status: '200', title: 'OK', description: 'Orders returned successfully', tone: 'success', schema: orderResponseSchema, example: '{"items": [], "total": 0}' },
      { status: '401', title: 'Unauthorized', description: 'Missing or invalid authentication', tone: 'danger', schema: '{ "type": "object" }', example: '{ "error": "unauthorized" }' },
      { status: '500', title: 'Internal Server Error', description: 'Unexpected server error', tone: 'danger', schema: '{ "type": "object" }', example: '{ "error": "internal_error" }' },
    ],
  },
  {
    id: 'create-order',
    apiDocId: defaultDocumentVersionId,
    service: 'order-service',
    method: 'POST',
    path: '/api/orders',
    title: 'Create Order',
    description: 'Creates a new order for the authenticated user.',
    operationId: 'createOrder',
    version: 'v1',
    documentVersionNo: 2,
    openapiVersion: '3.0.3',
    security: 'Bearer JWT',
    securityRequirements: ['BearerAuth'],
    servers: ['https://api.demo.apio.ps'],
    tags: ['orders'],
    deprecated: false,
    parameters: [
      { name: 'Idempotency-Key', location: 'header', required: false, description: 'Prevents duplicate order creation', schema: '{ "type": "string" }', example: 'idem_7f01' },
    ],
    requestSchema: orderRequestSchema,
    examples: [
      { name: 'create-order-request', owner: 'request', summary: 'Create order example', value: orderRequestBody },
      { name: 'created-order-response', owner: 'response · 201', summary: 'Created order example', value: orderResponseExample },
    ],
    requestBodyExample: orderRequestBody,
    responses: orderResponses,
  },
  {
    id: 'get-order',
    apiDocId: defaultDocumentVersionId,
    service: 'order-service',
    method: 'GET',
    path: '/api/orders/{orderId}',
    title: 'Get Order',
    description: 'Returns a single order by identifier.',
    operationId: 'getOrder',
    version: 'v1',
    documentVersionNo: 2,
    openapiVersion: '3.0.3',
    security: 'Bearer JWT',
    securityRequirements: ['BearerAuth'],
    servers: ['https://api.demo.apio.ps'],
    tags: ['orders'],
    deprecated: false,
    parameters: [
      { name: 'orderId', location: 'path', required: true, description: 'Order identifier', schema: '{ "type": "string" }', example: 'ord_1024' },
    ],
    requestSchema: '{ "type": "object", "properties": {} }',
    examples: [
      { name: 'get-order-path', owner: 'path parameter · orderId', summary: 'Order identifier', value: 'ord_1024' },
    ],
    requestBodyExample: '{}',
    responses: [
      { status: '200', title: 'OK', description: 'Order returned successfully', tone: 'success', schema: orderResponseSchema, example: orderResponseExample },
      { status: '401', title: 'Unauthorized', description: 'Missing or invalid authentication', tone: 'danger', schema: '{ "type": "object" }', example: '{ "error": "unauthorized" }' },
      { status: '404', title: 'Not Found', description: 'Order could not be found', tone: 'warning', schema: '{ "type": "object", "properties": { "message": { "type": "string" } } }', example: '{ "message": "order not found" }' },
    ],
  },
  {
    id: 'delete-order',
    apiDocId: defaultDocumentVersionId,
    service: 'order-service',
    method: 'DELETE',
    path: '/api/orders/{orderId}',
    title: 'Cancel Order',
    description: 'Cancels an order that is still eligible for cancellation.',
    operationId: 'deleteOrder',
    version: 'v1',
    documentVersionNo: 2,
    openapiVersion: '3.0.3',
    security: 'Bearer JWT',
    securityRequirements: ['BearerAuth'],
    servers: ['https://api.demo.apio.ps'],
    tags: ['orders'],
    deprecated: false,
    parameters: [
      { name: 'orderId', location: 'path', required: true, description: 'Order identifier', schema: '{ "type": "string" }', example: 'ord_1024' },
    ],
    requestSchema: '{ "type": "object", "properties": {} }',
    examples: [
      { name: 'cancel-order-path', owner: 'path parameter · orderId', summary: 'Order identifier', value: 'ord_1024' },
    ],
    requestBodyExample: '{}',
    responses: [
      { status: '204', title: 'No Content', description: 'Order cancelled successfully', tone: 'success', schema: '{}', example: '' },
      { status: '401', title: 'Unauthorized', description: 'Missing or invalid authentication', tone: 'danger', schema: '{ "type": "object" }', example: '{ "error": "unauthorized" }' },
      { status: '409', title: 'Conflict', description: 'Order cannot be cancelled in its current state', tone: 'warning', schema: '{ "type": "object" }', example: '{ "message": "order already shipped" }' },
    ],
  },
]

export function getEndpoint(endpointId: string) {
  return apiEndpoints.find((endpoint) => endpoint.id === endpointId) ?? apiEndpoints[0]
}

export function buildGeneratedDsl(endpoint: ApiEndpoint, strategy: StrategyId) {
  const expectedStatus = endpoint.method === 'POST' ? 201 : endpoint.method === 'DELETE' ? 204 : 200
  const strategyLabel = strategyOptions.find((option) => option.id === strategy)?.label ?? 'Happy Path'
  const idSuffix = strategy.split('_').join('-')

  return JSON.stringify({
    testCaseId: `TC_${endpoint.method}_${endpoint.id.split('-').join('_').toUpperCase()}_${idSuffix}_001`,
    description: `${endpoint.title} - ${strategyLabel} scenario`,
    strategy,
    method: endpoint.method,
    endpoint: endpoint.path,
    auth: {
      type: 'Bearer',
      useToken: strategy !== 'AUTH_FAILURE',
      source: 'Static',
    },
    request: {
      headers: {
        'Content-Type': 'application/json',
      },
      bodySchemaSource: endpoint.method === 'POST' ? 'OrderRequest' : 'None',
    },
    assertions: [
      {
        type: 'StatusCode',
        expected: strategy === 'AUTH_FAILURE' ? 401 : expectedStatus,
      },
      {
        type: 'JsonSchema',
        schemaSource: endpoint.method === 'DELETE' ? 'EmptyResponse' : 'OrderResponse',
      },
    ],
  }, null, 2)
}

export function getGenerationOutcome(strategy: StrategyId): GenerationOutcome {
  if (strategy === 'BUSINESS_ERROR') {
    return { requiresRepair: true, finalStatus: 'REJECTED', repairAttempts: 1 }
  }

  if (strategy === 'MISSING_REQUIRED' || strategy === 'BOUNDARY') {
    return { requiresRepair: true, finalStatus: 'ACCEPTED', repairAttempts: 1 }
  }

  return { requiresRepair: false, finalStatus: 'ACCEPTED', repairAttempts: 0 }
}
