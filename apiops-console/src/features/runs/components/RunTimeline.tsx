import { Ban, CheckCircle2, CircleDot, CirclePlay, Clock3, TriangleAlert } from 'lucide-react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import type { TimelineStep } from '../types'

function TimelineIcon({ step }: { step: TimelineStep }) {
  if (step.tone === 'success') return <CirclePlay size={16} strokeWidth={1.8} />
  if (step.tone === 'danger') return <TriangleAlert size={16} strokeWidth={1.8} />
  if (step.label === 'Run created') return <CircleDot size={16} strokeWidth={1.8} />
  if (step.label === 'Run pending') return <Clock3 size={16} strokeWidth={1.8} />
  if (step.label === 'Run cancelled') return <Ban size={16} strokeWidth={1.8} />
  if (step.label === 'Run completed') return <CheckCircle2 size={16} strokeWidth={1.8} />
  return <CircleDot size={16} strokeWidth={1.8} />
}

export function RunTimeline({ timeline }: { timeline: TimelineStep[] }) {
  const { ui } = useConsoleLanguage()

  return (
    <div className="run-timeline-list">
      {timeline.map((step) => (
        <div className={`timeline-item timeline-${step.tone}`} key={`${step.label}-${step.offset}`}>
          <span className="timeline-marker-wrap">
            <span className="timeline-marker">
              <TimelineIcon step={step} />
            </span>
          </span>
          <span className="timeline-copy">{ui(step.label)}</span>
          <time>{step.offset}</time>
        </div>
      ))}
    </div>
  )
}
