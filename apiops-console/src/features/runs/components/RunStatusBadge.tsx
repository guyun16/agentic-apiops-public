import { Ban, CircleCheck, CircleDot, CircleX, Clock3, TriangleAlert } from 'lucide-react'
import type { RunStatus } from '../types'

const statusIcons = {
  PENDING: Clock3,
  RUNNING: CircleDot,
  SUCCESS: CircleCheck,
  ASSERTION_FAILED: TriangleAlert,
  EXECUTION_FAILED: CircleX,
  TIMEOUT: TriangleAlert,
  CANCELLED: Ban,
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const Icon = statusIcons[status]

  return (
    <span className={`run-status-badge run-status-${status.toLowerCase()}`}>
      <Icon size={14} strokeWidth={1.9} />
      {status}
    </span>
  )
}
