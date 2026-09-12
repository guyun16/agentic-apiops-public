import { ArrowUpRight, CheckCircle2, ShieldCheck } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { categories } from '../benchmarkViewModel'
import { benchmarkAuthority, finalPercent, type FinalResultReport } from '../finalResultAdapter'

type Props = { onCategory: (type: string) => void; onFailures: () => void; onHistory: () => void; onReproducibility: () => void; report: FinalResultReport }

export function FinalBenchmarkOverview({ report: r, onCategory, onFailures, onHistory, onReproducibility }: Props) {
  const { ui } = useConsoleLanguage()
  return <div className="benchmark-final-dashboard">
    <section className="panel benchmark-final-hero" aria-label={ui('Final Benchmark Result')}>
      <div className="benchmark-final-title-row">
        <div><span className="benchmark-final-eyebrow">{ui('OFFICIAL V5 RESULT')} · DEV{r.splits.DEV.taskCount} / HELD_OUT{r.splits.HELD_OUT.taskCount}</span><h2>{ui('Final Benchmark Result')}</h2></div>
        <div className="benchmark-final-verdict"><span className="benchmark-acceptance"><CheckCircle2 size={14} /> {r.acceptance}</span><button type="button" className="benchmark-text-button" onClick={onFailures}>{r.outcomes.FAIL} FAIL · {r.outcomes.UNKNOWN} UNKNOWN <ArrowUpRight size={13} /></button></div>
      </div>
      <div className="benchmark-final-headline">
        <div><span>{ui('Tasks passed')}</span><strong>{r.outcomes.PASS}<small> / {r.execution.selected}</small></strong><span>{ui('Formal outcome')}</span></div>
        <div><span>{ui('Pass Rate')}</span><strong>{finalPercent(r.passRate)}</strong><span>{ui('PASS / selected')}</span></div>
        <div><span>{ui('Outcome Accuracy')}</span><strong>{finalPercent(r.outcomeAccuracy)}</strong><span>{ui('PASS / (PASS + FAIL)')}</span></div>
        <div><span>{ui('Provider Provenance')}</span><strong>{r.provider.provenCalls}<small> / {r.provider.totalCalls}</small></strong><span>{r.provider.status}</span></div>
      </div>
      <div className="benchmark-target-gates">{r.gates.map(gate => <div key={gate.metric}><span>{ui(gate.metric)}</span><strong>{finalPercent(gate.actual)}</strong><span className={gate.passed ? 'benchmark-count-pass' : 'benchmark-count-fail'}>{gate.passed ? 'PASS' : 'FAIL'}</span></div>)}</div>
    </section>
    <section className="panel benchmark-final-card benchmark-capability-overview">
      <div className="benchmark-section-heading"><div><h2>{ui('Capability Breakdown')}</h2><p className="benchmark-caption">{ui('Click a capability to inspect task-level evidence.')}</p></div><span className="benchmark-integrity-pill"><ShieldCheck size={14} /> {r.integrity.artifact}</span></div>
      <div className="benchmark-category-rows">{Object.entries(r.categories).map(([type, category]) => <button className="benchmark-category-row" key={type} onClick={() => onCategory(type)} type="button"><span className="benchmark-category-label"><strong>{ui(categories[type] ?? type)}</strong><small>{category.taskCount} {ui('Tasks')}</small></span><span><span className="benchmark-distribution" aria-hidden="true">{(['PASS', 'FAIL', 'UNKNOWN'] as const).map(status => <i key={status} className={'benchmark-segment is-' + status.toLowerCase()} style={{ width: (category.taskCount ? category[status] / category.taskCount * 100 : 0) + '%' }} />)}</span><span className="benchmark-distribution-labels">{(['PASS', 'FAIL', 'UNKNOWN'] as const).map(status => <em className={'benchmark-count-' + status.toLowerCase()} key={status}>{category[status]} {ui(status)}</em>)}</span></span><ArrowUpRight size={14} /></button>)}</div>
    </section>
    <div className="benchmark-quick-grid">
      <button className="panel benchmark-quick-card" onClick={onFailures} type="button"><span>{ui('Remaining Limitations')}</span><strong>{r.outcomes.FAIL + r.outcomes.UNKNOWN}</strong><small>{r.categories.FAILURE_DIAGNOSIS.FAIL} Diagnosis FAIL · {r.outcomes.UNKNOWN} UNKNOWN</small><ArrowUpRight size={15} /></button>
      <button className="panel benchmark-quick-card" onClick={onReproducibility} type="button"><span>{ui('Execution Integrity')}</span><strong>{r.execution.persisted} / {r.execution.selected}</strong><small>{ui('Persisted')} · {ui('Reproducibility')}: {r.reproducibility.status}</small><ArrowUpRight size={15} /></button>
      <button className="panel benchmark-quick-card" onClick={onHistory} type="button"><span>{ui('Full-105 Benchmark History')}</span><strong>105 × {benchmarkAuthority.full105RunCount}</strong><small>{ui('Verified complete runs')}</small><ArrowUpRight size={15} /></button>
    </div>
  </div>
}
