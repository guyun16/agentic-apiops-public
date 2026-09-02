export const ACCESS_TOKEN_STORAGE_KEY = 'apiops-console-access-token'

type ApiEnvelope<T> = {
  success: boolean
  code: string
  message: string
  data: T
}

type AgentErrorEnvelope = {
  error?: {
    code?: string
    message?: string
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(message: string, status: number, code = 'UNKNOWN') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

type ApiRequestInit = RequestInit & {
  authenticated?: boolean
}

type RawApiRequestInit = RequestInit & {
  authenticated?: boolean
  allowHttpStatuses?: number[]
}

function apiUrl(path: string) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? ''
  return `${baseUrl.replace(/\/$/, '')}${path}`
}

function agentApiUrl(path: string) {
  const baseUrl = import.meta.env.VITE_PYTHON_API_BASE_URL ?? '/agent-api'
  return `${baseUrl.replace(/\/$/, '')}${path}`
}

export function getAccessToken() {
  if (typeof window === 'undefined') return null

  try {
    return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function saveAccessToken(token: string) {
  window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token)
}

export function clearAccessToken() {
  try {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
    window.localStorage.removeItem('apiops-console-auth-status')
  } catch {
    // Session state remains in memory when storage is unavailable.
  }
}

export async function apiFetch<T>(path: string, { authenticated = true, ...init }: ApiRequestInit = {}) {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body
    && !(typeof FormData !== 'undefined' && init.body instanceof FormData)
    && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (authenticated) {
    const token = getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  let response: Response
  try {
    response = await fetch(apiUrl(path), { ...init, headers })
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : 'Network request failed', 0, 'NETWORK_ERROR')
  }

  let envelope: ApiEnvelope<T> | null = null
  try {
    envelope = await response.json() as ApiEnvelope<T>
  } catch {
    // Non-JSON responses are reported through the same typed error boundary.
  }

  if (!response.ok || !envelope?.success) {
    throw new ApiError(
      envelope?.message || response.statusText || 'Request failed',
      response.status,
      envelope?.code ?? 'HTTP_ERROR',
    )
  }

  return envelope.data
}

/** Fetch the Python AgentLab contract through its independent proxy/base URL. */
export async function agentApiFetch<T>(path: string, { authenticated = true, ...init }: ApiRequestInit = {}) {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body
    && !(typeof FormData !== 'undefined' && init.body instanceof FormData)
    && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (authenticated) {
    const token = getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  let response: Response
  try {
    response = await fetch(agentApiUrl(path), { ...init, headers })
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : 'Network request failed', 0, 'NETWORK_ERROR')
  }

  let payload: T | AgentErrorEnvelope | null = null
  try {
    payload = await response.json() as T | AgentErrorEnvelope
  } catch {
    // Preserve the HTTP status when the Python boundary does not return JSON.
  }

  if (!response.ok) {
    const errorPayload = payload as AgentErrorEnvelope | null
    throw new ApiError(
      errorPayload?.error?.message || response.statusText || 'Request failed',
      response.status,
      errorPayload?.error?.code ?? 'HTTP_ERROR',
    )
  }

  return payload as T
}

function rawErrorMessage(payload: unknown, fallback: string) {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return fallback

  const record = payload as Record<string, unknown>
  const nested = record.error
  if (typeof nested === 'object' && nested !== null && !Array.isArray(nested)) {
    const message = (nested as Record<string, unknown>).message
    if (typeof message === 'string' && message) return message
  }

  return typeof record.message === 'string' && record.message ? record.message : fallback
}

async function rawFetchJson<T>(url: string, {
  allowHttpStatuses = [],
  authenticated = true,
  ...init
}: RawApiRequestInit = {}) {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body
    && !(typeof FormData !== 'undefined' && init.body instanceof FormData)
    && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (authenticated) {
    const token = getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  let response: Response
  try {
    response = await fetch(url, { ...init, cache: init.cache ?? 'no-store', headers })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(error instanceof Error ? error.message : 'Network request failed', 0, 'NETWORK_ERROR')
  }

  let payload: T | unknown | null = null
  try {
    payload = await response.json() as T
  } catch {
    // The typed error below preserves the HTTP status for non-JSON responses.
  }

  if (!response.ok && !allowHttpStatuses.includes(response.status)) {
    throw new ApiError(
      rawErrorMessage(payload, response.statusText || 'Request failed'),
      response.status,
      'HTTP_ERROR',
    )
  }

  if (payload === null) {
    throw new ApiError('Response did not contain a JSON payload', response.status, 'INVALID_JSON')
  }

  return payload as T
}

/** Fetch a raw JSON response from Java, such as Spring Boot Actuator. */
export function rawApiFetch<T>(path: string, init?: RawApiRequestInit) {
  return rawFetchJson<T>(apiUrl(path), init)
}

/** Fetch a raw JSON response from Python AgentLab. */
export function rawAgentApiFetch<T>(path: string, init?: RawApiRequestInit) {
  return rawFetchJson<T>(agentApiUrl(path), init)
}

export type ProgressEvent<T> = {
  event: string
  data: T
}

export async function streamSse<T>(
  path: string,
  onEvent: (event: ProgressEvent<T>) => void,
  signal: AbortSignal,
) {
  const headers = new Headers({ Accept: 'text/event-stream' })
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(apiUrl(path), { headers, signal, cache: 'no-store' })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(error instanceof Error ? error.message : 'Network request failed', 0, 'NETWORK_ERROR')
  }

  if (!response.ok) {
    let message = response.statusText || 'Progress stream failed'
    let code = 'HTTP_ERROR'
    try {
      const envelope = await response.json() as Partial<ApiEnvelope<unknown>>
      message = envelope.message || message
      code = envelope.code || code
    } catch {
      // Keep the HTTP status when the error response is not JSON.
    }
    throw new ApiError(message, response.status, code)
  }

  if (!response.body) throw new ApiError('Progress stream has no response body', response.status, 'SSE_BODY_MISSING')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = 'message'
  let dataLines: string[] = []

  const dispatch = () => {
    if (!dataLines.length) {
      eventName = 'message'
      return
    }

    const data = dataLines.join('\n')
    dataLines = []
    const currentEvent = eventName
    eventName = 'message'
    try {
      onEvent({ event: currentEvent, data: JSON.parse(data) as T })
    } catch {
      throw new ApiError('Invalid progress event payload', response.status, 'SSE_PAYLOAD_INVALID')
    }
  }

  const consumeLines = (chunk: string) => {
    buffer += chunk
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line) {
        dispatch()
      } else if (line.startsWith('event:')) {
        eventName = line.slice(6).trim() || 'message'
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    consumeLines(decoder.decode(value, { stream: true }))
  }

  consumeLines(decoder.decode())
  if (buffer === '') dispatch()
}
