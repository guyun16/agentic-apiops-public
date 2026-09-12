import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { HttpSnapshotBody as SnapshotBody } from '../types'

export function HttpSnapshotBody({ snapshot }: { snapshot: SnapshotBody }) {
  const { language } = useConsoleLanguage()
  const zh = language === 'zh-CN'
  let body = snapshot.body
  if (body && !snapshot.truncated) {
    try { body = JSON.stringify(JSON.parse(body), null, 2) } catch { /* Keep sanitized text. */ }
  }
  return (
    <div>
      <p>{zh
        ? '来自实际执行。字符串、敏感字段、查询参数值及大多数请求头已隐藏；正文仅显示 JSON 结构与非敏感数值。'
        : 'Captured from execution. Strings, sensitive fields, query values and most headers are hidden; bodies show JSON structure and non-sensitive numbers.'}</p>
      <h4>{zh ? '请求／响应头' : 'Headers'}</h4>
      <pre className="runs-code-viewer">{JSON.stringify(snapshot.headers, null, 2)}</pre>
      <h4>{zh ? '正文' : 'Body'}</h4>
      <pre className="runs-code-viewer">{snapshot.bodyState === 'captured' ? body
        : snapshot.bodyState === 'empty' ? (zh ? '无正文' : 'No body')
          : (zh ? '正文已省略（非 JSON、无效 JSON 或超出大小限制）。' : 'Body omitted (non-JSON, invalid JSON or size limit exceeded).')}</pre>
      {snapshot.truncated ? <p role="note">{zh
        ? '快照已截断或省略超限内容。正文上限为 8,192 个字符，最多显示 32 个请求头。'
        : 'Snapshot truncated or oversized content omitted. Body limit: 8,192 characters; header limit: 32.'}</p> : null}
    </div>
  )
}
