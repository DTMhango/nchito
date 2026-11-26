import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import {
  createMessage,
  editMessage,
  followupKeys,
  KIND_LABEL,
  messageAction,
  messagesQuery,
  sendMessage,
  type MessageKind,
  type MessageOut,
} from "./api"
import { MessageChecks } from "./message-checks"

const KINDS = Object.keys(KIND_LABEL) as MessageKind[]

const SEND_TEXT: Record<
  MessageOut["send_state"],
  { label: string; tone: "good" | "warn" | "danger" | "info" | "neutral" }
> = {
  none: { label: "Not sent", tone: "neutral" },
  queued: { label: "Queued: can be cancelled", tone: "info" },
  sending: { label: "Sending", tone: "info" },
  sent: { label: "Sent", tone: "good" },
  uncertain: { label: "Uncertain: being reconciled", tone: "warn" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
}

/**
 * Messages about this application, drafted for the owner's approval and sent in the same mail
 * thread. Nothing goes without an approval; a blocking check disables approval and sending.
 */
export function MessagesPanel({ applicationId }: { applicationId: string }) {
  const qc = useQueryClient()
  const q = useQuery(messagesQuery(applicationId))
  const [kind, setKind] = useState<MessageKind>("follow_up")
  const [note, setNote] = useState("")
  const [slot, setSlot] = useState("")
  const refresh = () =>
    qc.invalidateQueries({ queryKey: followupKeys.messages(applicationId) })
  const draft = useMutation({
    mutationFn: () =>
      createMessage(applicationId, {
        kind,
        note: note || null,
        slot: slot || null,
      }),
    onSuccess: refresh,
  })

  if (q.isPending) return <p className="text-muted-foreground">Loading...</p>
  if (q.isError) return <p role="alert">{q.error.message}</p>
  const { thread, messages } = q.data
  const needsSlot = kind === "slot_accept" || kind === "slot_decline"

  return (
    <section aria-label="Messages" className="grid gap-3">
      <SectionHeader title="Messages you send" />
      <p className="text-sm text-muted-foreground">
        {thread.employer_replied
          ? "The employer has replied: drafts answer in that thread."
          : "No reply yet: drafts go to the address the application went to."}{" "}
        Nothing is sent until you approve it.
      </p>
      <form
        aria-label="Draft a message"
        className="flex flex-wrap items-end gap-2 panel p-3"
        onSubmit={(e) => {
          e.preventDefault()
          draft.mutate()
        }}
      >
        <label className="grid gap-1 text-sm">
          Kind
          <select
            aria-label="Message kind"
            className="rounded border border-border bg-background px-2 py-1"
            value={kind}
            onChange={(e) => setKind(e.target.value as MessageKind)}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        {needsSlot && (
          <label className="grid gap-1 text-sm">
            Slot, exactly as written
            <Input
              aria-label="Slot"
              value={slot}
              onChange={(e) => setSlot(e.target.value)}
            />
          </label>
        )}
        <label className="grid min-w-48 flex-1 gap-1 text-sm">
          Your note (optional)
          <Input
            aria-label="Note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <Button
          type="submit"
          disabled={draft.isPending || (needsSlot && !slot.trim())}
        >
          {draft.isPending ? "Drafting..." : "Draft"}
        </Button>
        {draft.isError && (
          <p role="alert" className="w-full text-sm text-danger">
            {draft.error.message}
          </p>
        )}
      </form>
      {messages.length === 0 ? (
        <p className="text-sm text-muted-foreground">No messages yet.</p>
      ) : (
        <ul className="grid gap-3" aria-label="Drafts and sent messages">
          {[...messages].reverse().map((m) => (
            <MessageCard key={m.id} message={m} onChanged={refresh} />
          ))}
        </ul>
      )}
    </section>
  )
}

function MessageCard({
  message: m,
  onChanged,
}: {
  message: MessageOut
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(m.body)
  const [to, setTo] = useState(m.to.join(", "))
  const [notice, setNotice] = useState<string | null>(null)
  const act = useMutation({
    mutationFn: (a: "approve" | "cancel" | "discard" | "regenerate") =>
      messageAction(m.id, a),
    onSuccess: () => {
      setNotice(null)
      onChanged()
    },
    onError: (e) => setNotice(e.message),
  })
  const send = useMutation({
    mutationFn: () => sendMessage(m.id),
    onSuccess: (r) => {
      setNotice(r.status === "queued" ? "Queued." : `Not sent: ${r.reason}`)
      onChanged()
    },
    onError: (e) => setNotice(e.message),
  })
  const save = useMutation({
    mutationFn: (confirm: boolean) =>
      editMessage(m.id, {
        body,
        to: to
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
        confirm_recipients: confirm,
      }),
    onSuccess: () => {
      setEditing(false)
      onChanged()
    },
    onError: (e) => setNotice(e.message),
  })
  const blocked = m.check_status === "block"
  const open =
    m.send_state === "none" ||
    m.send_state === "failed" ||
    m.send_state === "cancelled"
  const editable = open && m.status !== "discarded"
  const s = SEND_TEXT[m.send_state]

  return (
    <li
      className="grid gap-2 panel p-3"
      aria-label={`${KIND_LABEL[m.kind]} message`}
      data-status={m.status}
    >
      <div className="flex flex-wrap items-center gap-2">
        <b className="font-semibold">{KIND_LABEL[m.kind]}</b>
        <Chip tone={m.status === "approved" ? "good" : "neutral"}>
          {m.status === "budget_paused" ? "Paused: budget" : m.status}
        </Chip>
        <Chip tone={s.tone}>{s.label}</Chip>
        {m.automatic && <Chip tone="info">Automatic follow-up</Chip>}
      </div>
      <p className="text-sm break-words text-muted-foreground">
        To {m.to.join(", ") || "nobody yet"} · {m.subject}
        {m.thread_ref ? " · in the same thread" : ""}
      </p>
      {m.unconfirmed_recipients.length > 0 && (
        <p className="text-sm text-warn" role="note">
          Not an address this application has used:{" "}
          {m.unconfirmed_recipients.join(", ")}. Confirm it to send.
        </p>
      )}
      {m.error && <p className="text-sm text-danger">{m.error}</p>}
      {editing ? (
        <div className="grid gap-2">
          <Input
            aria-label="Recipients"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          <Textarea
            aria-label="Message body"
            rows={8}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => save.mutate(false)}>
              Save and check
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => save.mutate(true)}
            >
              Save and confirm recipients
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <pre className="font-sans text-sm break-words whitespace-pre-wrap">
          {m.body || "(no text yet)"}
        </pre>
      )}
      <MessageChecks message={m} />
      <div className="flex flex-wrap gap-2">
        {editable && !editing && (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            Edit
          </Button>
        )}
        {editable && m.status !== "approved" && (
          <Button
            size="sm"
            disabled={blocked || act.isPending}
            onClick={() => act.mutate("approve")}
          >
            Approve
          </Button>
        )}
        {m.status === "approved" && open && (
          <Button
            size="sm"
            disabled={blocked || send.isPending}
            onClick={() => send.mutate()}
          >
            Send email
          </Button>
        )}
        {m.send_state === "queued" && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => act.mutate("cancel")}
          >
            Cancel send
          </Button>
        )}
        {editable && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => act.mutate("regenerate")}
          >
            Draft again
          </Button>
        )}
        {editable && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => act.mutate("discard")}
          >
            Discard
          </Button>
        )}
      </div>
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
    </li>
  )
}
