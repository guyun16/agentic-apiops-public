import { Ban, CircleCheck, CircleDot, CircleX, Clock3, TriangleAlert } from 'lucide-react'
import type { RunStatus } from '../types'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'

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
  const { ui } = useConsoleLanguage()
  const Icon = statusIcons[status]

  return (
    <span className={`run-status-badge run-status-${status.toLowerCase()}`} title={status}>
      <Icon size={14} strokeWidth={1.9} />
      {ui(status)}
    </span>
  )
}
