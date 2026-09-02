import type { RunMethod } from '../types'

export function MethodBadge({ method }: { method: RunMethod }) {
  return <span className={`method-badge run-method method-${method.toLowerCase()}`}>{method}</span>
}
