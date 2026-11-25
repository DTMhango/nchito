import { Check, ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { PendingItem } from "./automation"

const NOT_SET = "Not set"

/**
 * "Needs your confirmation" (imported campaigns): each item with Confirm and Edit.
 * An item with no value cannot be confirmed: pay floors, countries and seniority have
 * no defaults, so the owner must set them first.
 */
export function ConfirmationBanner({
  items,
  confirmed,
  onConfirm,
  onEdit,
}: {
  items: PendingItem[]
  confirmed: string[]
  onConfirm: (id: PendingItem["id"]) => void
  onEdit: (item: PendingItem) => void
}) {
  const waiting = items.filter((i) => !confirmed.includes(i.id))
  return (
    <section
      aria-labelledby="needs-confirmation"
      className="mb-6 rounded-lg border border-warn bg-warn-soft p-4"
    >
      <h3
        id="needs-confirmation"
        className="flex items-center gap-2 text-md text-warn"
      >
        <ShieldAlert className="size-4" aria-hidden="true" />
        Needs your confirmation
      </h3>
      <p className="mt-1 mb-3 max-w-[68ch] text-sm">
        This campaign was imported. Nothing is sent for you beyond preparing
        documents until you confirm these{" "}
        {waiting.length > 0 ? `${waiting.length} items` : "items"}.
      </p>
      <ul className="grid gap-2">
        {items.map((i) => {
          const done = confirmed.includes(i.id)
          const empty = i.value === NOT_SET
          return (
            <li
              key={i.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md bg-surface px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{i.label}</div>
                <div className="text-sm text-muted-foreground">
                  {empty ? "Not set yet: choose a value first." : i.value}
                </div>
              </div>
              {done ? (
                <span className="inline-flex items-center gap-1 text-sm text-good">
                  <Check className="size-4" aria-hidden="true" /> Confirmed
                </span>
              ) : (
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={empty}
                    aria-label={`Confirm ${i.label.toLowerCase()}`}
                    onClick={() => onConfirm(i.id)}
                  >
                    Confirm
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Edit ${i.label.toLowerCase()}`}
                    onClick={() => onEdit(i)}
                  >
                    Edit
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
