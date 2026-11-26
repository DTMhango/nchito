import { ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { PendingItem } from "./automation"

/**
 * "Needs your confirmation" (imported campaigns): each item with Confirm and Edit.
 * An item with no value cannot be confirmed: pay floors, countries and seniority have
 * no defaults, so the owner must set them first.
 */
export function ConfirmationBanner({
  items,
  busy,
  onConfirm,
  onEdit,
}: {
  /** The items still to confirm (the server's `unconfirmed` list). */
  items: PendingItem[]
  busy?: boolean
  onConfirm: (id: PendingItem["id"]) => void
  onEdit: (item: PendingItem) => void
}) {
  const waiting = items
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
          const empty = i.needsValue && i.value === "Not set"
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
              {
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={empty || busy}
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
              }
            </li>
          )
        })}
      </ul>
    </section>
  )
}
