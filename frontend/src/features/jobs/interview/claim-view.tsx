import { useState } from "react"
import { AlertTriangle, Pencil, Star } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { cn } from "@/lib/utils"
import { traceClaim, type FactIndex } from "@/features/studio/draft"
import type { PackItem } from "../w3-pending-types"

/** What is wrong with a claim's tracing, in words; empty when it is sound. */
export function claimFlags(item: PackItem, index: FactIndex): string[] {
  if (!item.owner_claim || !item.text.trim()) return []
  const t = traceClaim(
    { key: item.id, text: item.text, fact_ids: item.fact_ids },
    index
  )
  const out: string[] = []
  if (t.state === "untraced" || item.flag === "untraced")
    out.push("Untraced: no fact in your Kit behind this claim")
  if (item.flag === "stray_figure" || t.strayFigures.length)
    out.push(
      t.strayFigures.length
        ? `${t.strayFigures.map((n) => `"${n}"`).join(", ")} is not in its facts`
        : "A figure here is not in its facts"
    )
  for (const f of t.facts.filter((x) => x.status !== "approved"))
    out.push(`${f.code} is not an approved fact`)
  for (const m of t.missing) out.push(`${m} is not in your Kit`)
  return out
}

/** The Kit facts a claim rests on, as the same chips the Studio uses. */
export function FactChips({
  item,
  index,
}: {
  item: PackItem
  index: FactIndex
}) {
  const t = traceClaim(
    { key: item.id, text: item.text, fact_ids: item.fact_ids },
    index
  )
  if (!t.facts.length) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-fact-chips>
      {t.facts.map((f) => (
        <FactTag
          key={f.id}
          code={f.code}
          text={f.text}
          status={f.status as "approved" | "draft" | "retired"}
        />
      ))}
    </span>
  )
}

type Props = {
  item: PackItem
  index: FactIndex
  /** Heading above the text (a question, a requirement). */
  lead?: string | null
  onSave: (text: string) => void
  saving?: boolean
  onFavourite?: (favourite: boolean) => void
}

/** One line of the pack: wording, its fact chips, any tracing flag, edit and favourite. */
export function ClaimView({
  item,
  index,
  lead,
  onSave,
  saving,
  onFavourite,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.text)
  const flags = claimFlags(item, index)
  const flagged = flags.length > 0
  const star = item.star

  return (
    <li
      data-pack-item={item.id}
      data-trace={flagged ? "flagged" : "ok"}
      className={cn(
        "grid gap-1.5 rounded-md border border-border bg-surface p-3",
        flagged && "border-l-4 border-l-danger"
      )}
    >
      <div className="flex items-start gap-2">
        <div className="grid min-w-0 flex-1 gap-1">
          {lead && <p className="font-semibold">{lead}</p>}
          {item.category && (
            <span className="eyebrow">{item.category.replace(/_/g, " ")}</span>
          )}
          {editing ? (
            <Textarea
              aria-label={`Edit: ${lead ?? item.text.slice(0, 40)}`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
            />
          ) : star ? (
            <dl className="grid gap-1 text-sm">
              {(["situation", "action", "result"] as const).map((k) => (
                <div key={k} className="grid grid-cols-[5.5rem_1fr] gap-2">
                  <dt className="font-semibold text-muted-foreground capitalize">
                    {k}
                  </dt>
                  <dd>{star[k]}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="whitespace-pre-wrap">{item.text}</p>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-0.5">
          {onFavourite && (
            <Button
              size="icon-xs"
              variant="ghost"
              aria-pressed={!!item.favourite}
              aria-label={
                item.favourite
                  ? `Remove from favourites: ${lead ?? item.text.slice(0, 40)}`
                  : `Favourite: ${lead ?? item.text.slice(0, 40)}`
              }
              onClick={() => onFavourite(!item.favourite)}
            >
              <Star
                aria-hidden="true"
                className={cn(item.favourite && "fill-current text-warn")}
              />
            </Button>
          )}
          {!editing && !star && (
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label={`Edit: ${lead ?? item.text.slice(0, 40)}`}
              onClick={() => {
                setDraft(item.text)
                setEditing(true)
              }}
            >
              <Pencil aria-hidden="true" />
            </Button>
          )}
        </span>
      </div>
      {editing && (
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
      {item.owner_claim && (
        <div className="flex flex-wrap items-center gap-1.5">
          <FactChips item={item} index={index} />
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
      )}
    </li>
  )
}
