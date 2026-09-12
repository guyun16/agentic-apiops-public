import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { benchmarkAuthority as authority, finalPercent } from '../finalResultAdapter'

export function Full105History() {
  const { language, ui } = useConsoleLanguage()
  const zh = language === 'zh-CN'
  const latest = authority.latestFull105
  return <section className="panel benchmark-final-card">
    <h2>{zh ? 'Full-105 正式运行历史' : 'Full-105 Benchmark History'}</h2>
    <p className="benchmark-caption">{zh ? 'Portfolio 主展示：Final Closure v5。最新完整运行采用独立 Diagnosis 契约：' : 'Portfolio result: Final Closure v5. Latest full run uses a separate Diagnosis contract: '}{latest.result.PASS} PASS / {latest.result.FAIL} FAIL / {latest.result.UNKNOWN} UNKNOWN · {latest.finalAcceptance}</p>
    <p className="benchmark-caption">{zh ? `${authority.full105RunCount} 次完整正式执行：${authority.realModelFull105RunCount} 次 real-model adapter，${authority.formalMixedFixtureRunCount} 次早期混合 fixture 基线。不同契约的分数不可直接归因为模型能力变化。` : `${authority.full105RunCount} complete formal executions: ${authority.realModelFull105RunCount} real-model adapter runs and ${authority.formalMixedFixtureRunCount} early mixed-fixture baselines. Score changes across contracts do not isolate model capability.`}</p>
    <details><summary>{zh ? '查看已核验的完整历史（105 / 105 / 105）' : 'View verified full history (105 / 105 / 105)'}</summary>
      <div className="benchmark-table-wrap" tabIndex={0} role="region" aria-label={ui('Full-105 Benchmark History')}>
        <table className="benchmark-data-table"><thead><tr>{['Run / Revision', 'Contract', 'PASS / FAIL / UNKNOWN', 'Pass Rate', 'Outcome Accuracy'].map(label => <th key={label}>{ui(label)}</th>)}</tr></thead>
          <tbody>{authority.history.map(run => <tr key={run.evaluationRunId}>
            <td><strong>#{run.number} {run.label}</strong><small>{run.revisionIdentity}</small><small>{run.evaluationRunId}</small><small>{run.officialRoot}</small></td>
            <td>{run.contract}</td>
            <td>{run.result.PASS == null ? 'UNAVAILABLE' : `${run.result.PASS} / ${run.result.FAIL ?? 0} / ${run.result.UNKNOWN ?? 0}`}</td>
            <td>{finalPercent(run.passRate)}</td><td>{finalPercent(run.outcomeAccuracy)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="benchmark-caption">{zh ? 'Pass Rate = PASS / 105；Outcome Accuracy = PASS / (PASS + FAIL)。早期 V1 行仅计算原严格 Task Success 的决定性结果比例；未按新契约重新评分。' : 'Pass Rate = PASS / 105; Outcome Accuracy = PASS / (PASS + FAIL). Early V1 rows use original strict Task Success counts, without rescoring under a newer contract.'}</p>
      <p className="benchmark-caption">{zh ? '排除：中断、residual、targeted、smoke、live acceptance、offline reprojection、preflight、estimate、contract matrix。' : 'Excluded: interrupted, residual, targeted, smoke, live acceptance, offline reprojection, preflight, estimates and contract matrices.'}</p>
    </details>
  </section>
}
