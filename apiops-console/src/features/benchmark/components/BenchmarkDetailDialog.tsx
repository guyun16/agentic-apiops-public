import { useConsoleLanguage } from '../../../app/ConsoleLanguage'
import { X } from 'lucide-react'
import { type ReactNode, useEffect, useRef } from 'react'

type Props = {
  children: ReactNode
  eyebrow?: string
  onClose: () => void
  open: boolean
  title: string
}

export function BenchmarkDetailDialog({ children, eyebrow, onClose, open, title }: Props) {
  const { ui } = useConsoleLanguage()
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return <dialog className="benchmark-detail-dialog" onCancel={onClose} onClose={onClose} ref={ref}>
    <div className="benchmark-dialog-shell">
      <header className="benchmark-dialog-header">
        <div>{eyebrow ? <span>{eyebrow}</span> : null}<h2>{title}</h2></div>
        <button aria-label={ui('Close')} className="benchmark-dialog-close" onClick={onClose} type="button"><X size={18} /></button>
      </header>
      <div className="benchmark-dialog-body">{children}</div>
    </div>
  </dialog>
}
