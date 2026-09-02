import { AlertTriangle, FileLock2, FolderOpen, LoaderCircle, type LucideIcon } from 'lucide-react'

export type PageStateKind = 'loading' | 'forbidden' | 'error' | 'empty'

type PageStateProps = {
  kind: PageStateKind
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
  projectLabel?: string
  projectName?: string
}

const icons: Record<PageStateKind, LucideIcon> = {
  loading: LoaderCircle,
  forbidden: FileLock2,
  error: AlertTriangle,
  empty: FolderOpen,
}

export function PageState({ actionLabel, description, kind, onAction, projectLabel, projectName, title }: PageStateProps) {
  const Icon = icons[kind]

  return (
    <section className={`page-state page-state-${kind}`} aria-live={kind === 'loading' ? 'polite' : 'assertive'}>
      <div className="page-state-icon" aria-hidden="true"><Icon size={22} strokeWidth={1.8} /></div>
      <h1>{title}</h1>
      <p>{description}</p>
      {projectName ? (
        <div className="page-state-project">
          <span>{projectLabel ?? 'Project'}</span>
          <strong>{projectName}</strong>
        </div>
      ) : null}
      {actionLabel && onAction ? (
        <button className="panel-action page-state-action" onClick={onAction} type="button">
          {actionLabel}
        </button>
      ) : null}
    </section>
  )
}
