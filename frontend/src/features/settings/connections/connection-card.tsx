import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Chip } from "@/components/chip"
import { Button } from "@/components/ui/button"
import {
  connectionKeys,
  deleteConnection,
  testConnection,
  type Connection,
  type ConnectionTest,
} from "./api"
import { ConnectForm } from "./connect-form"
import { FORMS } from "./forms"

/** What each permission means, in plain words. Unknown scopes are shown as the server sent them. */
const SCOPE_WORDS: [RegExp, string][] = [
  [/gmail\.send/, "Send email as you"],
  [
    /gmail\.readonly|mail\.google\.com/,
    "Read your whole mailbox (Gmail cannot limit this to one label)",
  ],
  [/gmail\.metadata/, "See who wrote and when, not the message text"],
  [
    /drive\.file|drive\.appdata/,
    "See and change only the files this app puts in your Drive",
  ],
  [/drive\.readonly/, "Read the files in your Drive"],
]
export const scopeInWords = (scope: string) =>
  SCOPE_WORDS.find(([re]) => re.test(scope))?.[1] ?? scope

const HEALTH = {
  ok: { tone: "good", label: "Working" },
  failing: { tone: "danger", label: "Failing" },
  unknown: { tone: "neutral", label: "Not checked yet" },
} as const

const checked = (iso: string | null) =>
  iso
    ? `Checked ${new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`
    : "Never checked"

/**
 * One saved connection. Secrets are never shown: the server only says which ones are saved,
 * and this card shows that they exist, not what they are.
 */
export function ConnectionCard({ c }: { c: Connection }) {
  const qc = useQueryClient()
  const [result, setResult] = useState<ConnectionTest | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [editing, setEditing] = useState(false)
  const editable = c.provider in FORMS
  const refresh = () => qc.invalidateQueries({ queryKey: connectionKeys.all })
  const test = useMutation({
    mutationFn: () => testConnection(c.id),
    onSuccess: (r) => {
      setResult(r)
      void refresh()
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteConnection(c.id),
    onSuccess: refresh,
  })
  const h = HEALTH[c.health]
  const saved = Object.keys(c.secrets_masked)
  return (
    <li
      aria-label={c.label}
      className="grid gap-2 rounded-md border border-border bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{c.label}</span>
        <Chip tone={h.tone}>{h.label}</Chip>
        {!c.enabled && <Chip tone="line">Paused</Chip>}
        <span className="text-sm text-muted-foreground">
          {checked(c.last_checked_at)}
        </span>
      </div>
      {c.scopes_granted.length > 0 && (
        <div>
          <div className="eyebrow">Permissions you gave</div>
          <ul className="list-disc pl-5">
            {c.scopes_granted.map((s) => (
              <li key={s}>{scopeInWords(s)}</li>
            ))}
          </ul>
        </div>
      )}
      {c.reads_description && (
        <div>
          <div className="eyebrow">What the app actually reads</div>
          <p>{c.reads_description}</p>
        </div>
      )}
      {saved.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Saved and hidden:{" "}
          {saved.map((k) => k.replaceAll("_", " ")).join(", ")}.
        </p>
      )}
      {result && (
        <p role="status" className={result.ok ? "text-good" : "text-danger"}>
          {result.ok ? "Test passed. " : "Test failed. "}
          {result.detail}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => test.mutate()}
          disabled={test.isPending}
          aria-label={`Test ${c.label}`}
        >
          Test
        </Button>
        {editable && (
          <Button
            size="sm"
            variant="outline"
            aria-expanded={editing}
            onClick={() => setEditing((v) => !v)}
            aria-label={`Change ${c.label}`}
          >
            Change
          </Button>
        )}
        {!confirming ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setConfirming(true)}
            aria-label={`Disconnect ${c.label}`}
          >
            Disconnect
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              variant="destructive"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
            >
              Yes, disconnect {c.label}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConfirming(false)}
            >
              Keep it
            </Button>
          </>
        )}
      </div>
      {editing && editable && (
        <ConnectForm
          provider={c.provider as keyof typeof FORMS}
          label={c.label}
          existing={c}
          onDone={() => setEditing(false)}
        />
      )}
      {(test.isError || remove.isError) && (
        <p role="alert" className="text-sm text-danger">
          {(test.error ?? remove.error)?.message}
        </p>
      )}
    </li>
  )
}
