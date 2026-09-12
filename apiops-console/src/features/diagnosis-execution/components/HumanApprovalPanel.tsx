import { CheckCircle2, Edit3, ShieldAlert, XCircle } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { DiagnosisExecutionResponse } from '../../diagnosis/types'
import type { DiagnosisRuntime } from './DiagnosisRuntimeSelector'

type HumanApprovalPanelProps = {
  execution: DiagnosisExecutionResponse | null
  runtime: DiagnosisRuntime
  editedArguments: string
  isEditing: boolean
  notice: string
  busy?: boolean
  onArgumentsChange: (value: string) => void
  onApprove: () => void
  onEdit: () => void
  onReject: () => void
  onViewResult: () => void
}

function statusDescription(execution: DiagnosisExecutionResponse | null) {
  if (!execution) return 'Ready to start.'
  if (execution.status === 'APPROVAL_REQUIRED') return 'Waiting for human approval.'
  if (execution.status === 'COMPLETED') return 'DiagnosisReport is ready.'
  if (execution.status === 'REJECTED') return 'Diagnosis execution stopped by the approval decision.'
  if (execution.status === 'FAILED') return execution.failure?.message ?? 'Diagnosis execution failed.'
  return 'Diagnosis workflow is running.'
}

export function HumanApprovalPanel({
  busy = false,
  editedArguments,
  execution,
  isEditing,
  notice,
  onArgumentsChange,
  onApprove,
  onEdit,
  onReject,
  onViewResult,
  runtime,
}: HumanApprovalPanelProps) {
  const { ui } = useConsoleLanguage()

  if (runtime === 'JAVA_PLATFORM') {
    return (
      <section className="diagnosis-execution-panel diagnosis-approval-panel diagnosis-availability-panel panel is-unavailable" aria-disabled="true" aria-labelledby="approval-panel-title">
        <header className="diagnosis-execution-panel-header">
          <span className="diagnosis-execution-eyebrow">4. {ui('Human Approval')}</span>
          <h2 id="approval-panel-title">{ui('Human Approval')}</h2>
          <small className="diagnosis-control-runtime">{ui('Python AgentLab only')}</small>
        </header>
        <div className="diagnosis-execution-status-row">
          <ShieldAlert size={18} strokeWidth={1.8} />
          <span>{ui('Availability')}</span>
          <strong className="diagnosis-execution-status diagnosis-execution-status-unavailable">{ui('Unavailable')}</strong>
        </div>
        <div className="diagnosis-execution-unavailable">
          <strong>{ui('Unavailable for Java Platform')}</strong>
          <span>{ui('Python AgentLab only')}</span>
        </div>
      </section>
    )
  }

  const status = execution?.status ?? 'READY'
  const approval = execution?.approvalRequest
  const approvalRequired = status === 'APPROVAL_REQUIRED' && approval !== null && approval !== undefined

  return (
    <section className={`diagnosis-execution-panel diagnosis-approval-panel panel is-${status.toLowerCase()}`} aria-labelledby="approval-panel-title">
      <header className="diagnosis-execution-panel-header">
        <span className="diagnosis-execution-eyebrow">4. {ui('Human Approval')}</span>
        <h2 id="approval-panel-title">{ui('Human Approval')}</h2>
        <small className="diagnosis-control-runtime">{ui('Python AgentLab only')}</small>
      </header>

      <div className="diagnosis-execution-status-row">
        <ShieldAlert size={18} strokeWidth={1.8} />
        <span>{ui('Status')}</span>
        <strong className={`diagnosis-execution-status diagnosis-execution-status-${status.toLowerCase()}`}>{ui(status)}</strong>
      </div>

      {approvalRequired && approval ? (
        <div className="diagnosis-approval-content">
          <div className="diagnosis-approval-field"><span>{ui('Tool')}</span><strong>{approval.toolName}</strong></div>
          <div className="diagnosis-approval-field"><span>{ui('Risk')}</span><strong className="diagnosis-risk-badge">{ui(approval.risk)}</strong></div>
          <div className="diagnosis-approval-field diagnosis-approval-reason"><span>{ui('Reason')}</span><p>{ui(approval.reason)}</p></div>
          <div className="diagnosis-approval-arguments">
            <div className="diagnosis-approval-subheading"><strong>{ui('Proposed Arguments')}</strong><span>{ui('Real workflow intent')}</span></div>
            {isEditing ? (
              <textarea aria-label={ui('Proposed tool arguments')} disabled={busy} onChange={(event) => onArgumentsChange(event.target.value)} value={editedArguments} />
            ) : (
              <pre><code>{editedArguments}</code></pre>
            )}
          </div>
          <div className="diagnosis-approval-scope">
            <div className="diagnosis-approval-subheading"><strong>{ui('Approval Scope')}</strong><span>{ui('Exact intent binding')}</span></div>
            {Object.entries(approval.scope).map(([label, value]) => <div key={label}><span>{ui(label)}</span><code>{value}</code></div>)}
          </div>
          <div className="diagnosis-approval-warning">
            <ShieldAlert size={16} strokeWidth={1.8} />
            <span>{ui('Approval applies only to this exact intent and argument snapshot. It does not grant permanent permission.')}</span>
          </div>
          <div className="diagnosis-approval-actions">
            <button className="diagnosis-execution-danger-button" disabled={busy} onClick={onReject} type="button"><XCircle size={16} strokeWidth={1.9} /> {ui('Reject')}</button>
            <button className="diagnosis-execution-secondary-button" disabled={busy} onClick={isEditing ? onApprove : onEdit} type="button">
              {isEditing ? <CheckCircle2 size={16} strokeWidth={1.9} /> : <Edit3 size={16} strokeWidth={1.9} />}
              {ui(isEditing ? 'Apply & Approve' : 'Edit & Approve')}
            </button>
            {!isEditing ? <button className="diagnosis-execution-primary-button" disabled={busy} onClick={onApprove} type="button"><CheckCircle2 size={16} strokeWidth={1.9} /> {ui('Approve')}</button> : null}
          </div>
        </div>
      ) : (
        <div className="diagnosis-execution-status-content">
          <p>{ui(statusDescription(execution))}</p>
          {execution?.failure ? <p className="diagnosis-execution-rejected">{execution.failure.code}: {ui(execution.failure.message)}</p> : null}
          {status === 'COMPLETED' ? (
            <div className="diagnosis-execution-status-actions">
              <button className="diagnosis-execution-primary-button" onClick={onViewResult} type="button"><CheckCircle2 size={16} strokeWidth={1.9} /> {ui('View Diagnosis Result')}</button>
            </div>
          ) : null}
        </div>
      )}
      {notice ? <div className="diagnosis-execution-notice">{ui(notice)}</div> : null}
    </section>
  )
}
