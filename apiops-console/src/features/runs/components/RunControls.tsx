import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../../../app/AuthContext'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { useProject } from '../../../app/ProjectContext'
import { ApiError, apiFetch } from '../../../lib/api-client'
import type { RunSummary } from '../types'

type Controls = {
  batchId: string | null
  batchSize: number
  cancelRequested: boolean
  canCancel: boolean
  canRerun: boolean
  sourceRunId: number | null
}

export function RunControls({ run, onRefresh }: {
  run: RunSummary
  onRefresh: (runId: number, signal: AbortSignal) => Promise<void>
}) {
  const { currentProject, refreshProjects } = useProject()
  const { expireSession } = useAuth()
  const { language } = useConsoleLanguage()
  const zh = language === 'zh-CN'
  const projectId = currentProject!.projectId
  const [controls, setControls] = useState<Controls | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [acceptedRunId, setAcceptedRunId] = useState<number | null>(null)
  const busyRef = useRef(false)
  const lifetime = useRef(new AbortController())
  const refreshRef = useRef(onRefresh)
  refreshRef.current = onRefresh
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/test-runs/${run.runId}`
  const editable = currentProject?.projectRole !== 'VIEWER'

  function handleError(reason: unknown) {
    if (lifetime.current.signal.aborted) return
    setError(reason instanceof Error ? reason.message : String(reason))
    if (reason instanceof ApiError && reason.status === 401) expireSession()
    if (reason instanceof ApiError && reason.status === 403) void refreshProjects()
  }

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    setBusy(false)
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      try {
        const next = await apiFetch<Controls>(`${base}/controls`, { signal: controller.signal })
        if (controller.signal.aborted) return
        setControls(next)
        if (run.status === 'PENDING' || run.status === 'RUNNING') {
          await refreshRef.current(run.runId, controller.signal)
          if (!controller.signal.aborted) timer = setTimeout(() => void load(), 3000)
        }
        if (!controller.signal.aborted) setError('')
      } catch (reason) {
        if (controller.signal.aborted) return
        handleError(reason)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [base, run.status, loadAttempt])

  async function act(action: 'cancel' | 'rerun') {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError('')
    setMessage('')
    const signal = lifetime.current.signal
    try {
      const result = await apiFetch<string | { runIds: number[] }>(`${base}/${action}`, { method: 'POST', signal })
      if (signal.aborted) return
      if (action === 'cancel') {
        setMessage(zh ? '已请求取消待执行任务；已开始的任务可能继续完成，最终状态以服务器为准。' : 'Cancellation requested for pending tasks; tasks already started may finish. Final status comes from the server.')
        setControls(await apiFetch<Controls>(`${base}/controls`, { signal }))
      }
      const target = typeof result === 'object' ? result.runIds[0] : run.runId
      if (action === 'rerun') setAcceptedRunId(target)
      await refreshRef.current(target, signal)
    } catch (reason) {
      if (!signal.aborted) handleError(reason)
    } finally {
      busyRef.current = false
      if (!signal.aborted) setBusy(false)
    }
  }

  async function navigate(runId: number) {
    const signal = lifetime.current.signal
    try {
      await onRefresh(runId, signal)
    } catch (reason) {
      if (!signal.aborted) handleError(reason)
    }
  }

  return <div className="run-inline-state" aria-live="polite">
    {controls?.sourceRunId ? <button className="panel-action" type="button"
      onClick={() => void navigate(controls.sourceRunId!)}>
      {zh ? '来源运行' : 'Source run'} #{controls.sourceRunId}
    </button> : null}
    {controls?.canCancel ? <button className="panel-action" type="button"
      disabled={!editable || busy || controls.cancelRequested} onClick={() => void act('cancel')}>
      {controls.cancelRequested ? (zh ? '已请求取消待执行任务' : 'Pending-task cancellation requested')
        : controls.batchSize > 1 ? (zh ? `取消批次待执行任务（共 ${controls.batchSize} 个运行）` : `Cancel pending tasks in batch (${controls.batchSize} runs total)`)
          : (zh ? '请求取消待执行任务' : 'Request pending-task cancellation')}
    </button> : null}
    {controls?.canCancel ? <span>{zh ? '已开始的任务可能继续完成。' : 'Tasks already started may finish.'}</span> : null}
    {controls?.canRerun ? <button className="panel-action" type="button" disabled={!editable || busy || acceptedRunId !== null}
      onClick={() => void act('rerun')}>{zh ? '重新运行' : 'Run again'}</button> : null}
    {acceptedRunId ? <button className="panel-action" type="button" onClick={() => void navigate(acceptedRunId)}>
      {zh ? '已创建运行' : 'Created run'} #{acceptedRunId}
    </button> : null}
    {busy ? <span>{zh ? '正在提交…' : 'Submitting…'}</span> : null}
    {message ? <span>{message}</span> : null}
    {error ? <span role="alert">{zh ? '运行控制不可用：' : 'Run controls unavailable: '}{error}</span> : null}
    {error ? <button className="panel-action" type="button" disabled={busy}
      onClick={() => setLoadAttempt((attempt) => attempt + 1)}>
      {zh ? '刷新运行控制' : 'Refresh run controls'}
    </button> : null}
  </div>
}
