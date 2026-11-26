import { useQuery } from "@tanstack/react-query"
import { connectionsQuery } from "./connections/api"

/** Mail connections that can send (the same list the Connections screen's "Use as default" uses). */
export const MAIL_PROVIDERS = ["gmail", "imap_smtp", "msgraph"]

type PickerProps = {
  id: string
  className: string
  value: string
  nullable: boolean
  onChange: (v: string) => void
  "aria-invalid"?: boolean
  "aria-describedby"?: string
}

/**
 * A setting whose value points at a record (a connection id) picks from those records instead of
 * a raw text box. Keyed by setting key: the registry says `uuid`, this says what the id is of.
 */
export const REFERENCE_PICKERS: Record<
  string,
  (p: PickerProps) => React.JSX.Element
> = {
  "mail.default_mailbox": MailboxPicker,
}

function MailboxPicker({ value, nullable, onChange, ...rest }: PickerProps) {
  const q = useQuery(connectionsQuery())
  const boxes = (q.data ?? []).filter(
    (c) => c.enabled && MAIL_PROVIDERS.includes(c.provider)
  )
  const unknown = value && !boxes.some((c) => c.id === value)
  return (
    <select {...rest} value={value} onChange={(e) => onChange(e.target.value)}>
      {nullable && <option value="">The first mailbox connected</option>}
      {q.isSuccess && boxes.length === 0 && (
        <option value="none" disabled>
          No mailbox connected yet (Settings, Connections)
        </option>
      )}
      {unknown && (
        <option value={value}>
          {q.isPending ? "Loading mailboxes…" : "A mailbox no longer connected"}
        </option>
      )}
      {boxes.map((c) => (
        <option key={c.id} value={c.id}>
          {c.label}
        </option>
      ))}
    </select>
  )
}
