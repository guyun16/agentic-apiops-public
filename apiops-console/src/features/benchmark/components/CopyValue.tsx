import { useState } from 'react'
import { useConsoleLanguage } from '../../../app/ConsoleLanguage'

export function CopyValue({ value }: { value: string }) {
  const { ui } = useConsoleLanguage()
  const [message, setMessage] = useState('')
  return <span className="benchmark-copy"><code title={value}>{value}</code><button type="button" aria-label={ui('Copy') + ' ' + value} onClick={() => {
    void navigator.clipboard.writeText(value).then(() => setMessage(ui('Copied')), () => setMessage(ui('Copy failed; select the text to copy.')))
  }}>{ui('Copy')}</button><span role="status">{message}</span></span>
}
