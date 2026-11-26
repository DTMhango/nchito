import { useState } from "react"
import { ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/chip"
import {
  useReview,
  useReviewDecision,
  type ReviewItem,
} from "@/features/kit/api"

/**
 * Groups whose answers decide what is sent in your name or what is ruled in or out. Each item
 * is confirmed on its own. There is no way to confirm these as a batch.
 */
const PROTECTED = /pay|salary|countr|senior|visa|work_right|relocat/i
export const isProtectedGroup = (group: string) => PROTECTED.test(group)

const plain = (g: string) => g.replaceAll("_", " ")

export function groupReview(items: ReviewItem[]) {
  const by = new Map<string, ReviewItem[]>()
  for (const i of items) by.set(i.group, [...(by.get(i.group) ?? []), i])
  return [...by.entries()]
    .map(([group, rows]) => ({
      group,
      protected: isProtectedGroup(group),
      rows: [...rows].sort((a, b) => a.stale_first_rank - b.stale_first_rank),
    }))
    .sort(
      (a, b) =>
        Number(b.protected) - Number(a.protected) ||
        a.rows[0].stale_first_rank - b.rows[0].stale_first_rank
    )
}

/** The guided pass over everything marked "needs review", stale and decisive items first. */
export function ReviewGroups({ stale }: { stale: boolean }) {
  const q = useReview()
  if (q.isPending) return <p>Loading what needs review.</p>
  if (q.isError)
    return (
      <p role="alert" className="text-danger">
        Could not load the review list.
      </p>
    )
  const groups = groupReview(q.data)
  if (groups.length === 0)
    return (
      <p role="status" className="text-good">
        Nothing is waiting for review.
      </p>
    )
  return (
    <div className="grid gap-4">
      {groups.map((g) => (
        <GroupBlock key={g.group} {...g} stale={stale} />
      ))}
    </div>
  )
}

function GroupBlock({
  group,
  rows,
  protected: locked,
  stale,
}: {
  group: string
  rows: ReviewItem[]
  protected: boolean
  stale: boolean
}) {
  const decide = useReviewDecision()
  const [read, setRead] = useState(false)
  const [busy, setBusy] = useState(false)

  const confirmGroup = async () => {
    setBusy(true)
    try {
      for (const r of rows)
        await decide.mutateAsync({
          entity: r.entity,
          id: r.id,
          decision: "confirm",
        })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-label={`Review: ${plain(group)}`}
      className="grid gap-2 rounded-md border border-border bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-md capitalize">{plain(group)}</h3>
        <Chip tone="line">{rows.length}</Chip>
        {locked && (
          <Chip tone="warn" icon={ShieldCheck}>
            One by one
          </Chip>
        )}
      </div>
      {locked && (
        <p className="text-sm text-muted-foreground">
          These decide where you apply and what is said for you, so each one
          needs your own yes. They cannot be confirmed together.
        </p>
      )}
      <ul className="divide-y divide-border">
        {rows.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 py-2">
            <span className="min-w-0 flex-1">{r.title}</span>
            {stale && <Chip tone="warn">May be stale</Chip>}
            {r.conflicts_with.length > 0 && (
              <Chip tone="danger">
                Conflicts with {r.conflicts_with.length} other
              </Chip>
            )}
            <Button
              size="sm"
              variant="outline"
              aria-label={`Confirm ${r.title}`}
              disabled={decide.isPending}
              onClick={() =>
                decide.mutate({
                  entity: r.entity,
                  id: r.id,
                  decision: "confirm",
                })
              }
            >
              Confirm
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Drop ${r.title}`}
              disabled={decide.isPending}
              onClick={() =>
                decide.mutate({ entity: r.entity, id: r.id, decision: "drop" })
              }
            >
              Drop
            </Button>
          </li>
        ))}
      </ul>
      {!locked && rows.length > 1 && (
        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-2">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={read}
              onCheckedChange={(v) => setRead(v === true)}
              aria-label={`I have read every item in ${plain(group)}`}
            />
            I have read every item above
          </label>
          <Button
            size="sm"
            disabled={!read || busy}
            onClick={() => void confirmGroup()}
          >
            Confirm these {rows.length}
          </Button>
        </div>
      )}
      {decide.isError && (
        <p role="alert" className="text-sm text-danger">
          {decide.error.message}
        </p>
      )}
    </section>
  )
}
