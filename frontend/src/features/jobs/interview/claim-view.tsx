import { useState, type ReactNode } from "react"
import { AlertTriangle, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { cn } from "@/lib/utils"
import { traceClaim, type FactIndex } from "@/features/studio/draft"
import type { Claim } from "./shapes"

/** What is wrong with a claim's tracing, in words; empty when it is sound. */
export function claimFlags(
  key: string,
  claim: Claim,
  index: FactIndex
): string[] {
  if (!claim.text.trim()) return []
  const t = traceClaim(
    { key, text: claim.text, fact_ids: claim.fact_ids },
    index
  )
  const out: string[] = []
  if (t.state === "untraced")
    out.push("Untraced: no fact in your Kit behind this claim")
  if (t.strayFigures.length)
    out.push(
      `${t.strayFigures.map((n) => `"${n}"`).join(", ")} is not in its facts`
    )
  for (const f of t.facts.filter((x) => x.status !== "approved"))
    out.push(`${f.code} is not an approved fact`)
  for (const m of t.missing) out.push(`${m} is not in your Kit`)
  return out
}

/** The Kit facts a claim rests on, as the same chips the Studio uses. */
export function FactChips({
  factIds,
  index,
}: {
  factIds: string[]
  index: FactIndex
}) {
  const facts = factIds
    .map((id) => index.get(id))
    .filter((f, i, a) => !!f && a.indexOf(f) === i)
  if (!facts.length) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-fact-chips>
      {facts.map((f) => (
        <FactTag
          key={f!.id}
          code={f!.code}
          text={f!.text}
          status={f!.status as "approved" | "draft" | "retired"}
        />
      ))}
    </span>
  )
}

type Props = {
  /** Stable id for tests and tracing (`why_you.0`). */
  id: string
  claim: Claim
  index: FactIndex
  /** Heading above the text (a question, a requirement). */
  lead?: ReactNode
  /** Small print under the lead (why it is asked). */
  detail?: string | null
  /** Save an owner edit of the wording; absent while edits are held. */
  onSave?: (text: string) => void
  saving?: boolean
}

/** One claim about the owner: wording, its fact chips, any tracing flag, and an edit. */
export function ClaimView({
  id,
  claim,
  index,
  lead,
  detail,
  onSave,
  saving,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(claim.text)
  const flags = claimFlags(id, claim, index)
  const flagged = flags.length > 0
  const name = typeof lead === "string" ? lead : claim.text.slice(0, 40)

  return (
    <li
      data-pack-item={id}
      data-trace={flagged ? "flagged" : "ok"}
      className={cn(
        "grid gap-1.5 rounded-md border border-border bg-surface p-3",
        flagged && "border-l-4 border-l-danger"
      )}
    >
      <div className="flex items-start gap-2">
        <div className="grid min-w-0 flex-1 gap-1">
          {lead && <p className="font-semibold">{lead}</p>}
          {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
          {editing ? (
            <Textarea
              aria-label={`Edit: ${name}`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
            />
          ) : (
            <p className="whitespace-pre-wrap">{claim.text}</p>
          )}
        </div>
        {!editing && onSave && (
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label={`Edit: ${name}`}
            onClick={() => {
              setDraft(claim.text)
              setEditing(true)
            }}
          >
            <Pencil aria-hidden="true" />
          </Button>
        )}
      </div>
      {editing && onSave && (
        <div className="flex gap-1.5">
          <Button
            size="xs"
            disabled={saving || !draft.trim()}
            onClick={() => {
              onSave(draft)
              setEditing(false)
            }}
          >
            Save
          </Button>
          <Button size="xs" variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        <FactChips factIds={claim.fact_ids} index={index} />
        {flags.map((f) => (
          <Chip
            key={f}
            tone="danger"
            icon={AlertTriangle}
            data-flag={f.startsWith("Untraced") ? "untraced" : "warning"}
            className="whitespace-normal"
          >
            {f}
          </Chip>
        ))}
      </div>
    </li>
  )
}
