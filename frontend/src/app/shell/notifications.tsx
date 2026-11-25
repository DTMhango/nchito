import { useState } from "react"
import { Bell } from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { PendingList, usePendingActions } from "@/features/today/pending-list"
import { useLiveUpdates } from "@/features/today/use-live-updates"

/** Notifications bell: lists the open pending actions, the same ones "Needs you" shows. */
export function Notifications() {
  const [open, setOpen] = useState(false)
  const { items } = usePendingActions()
  useLiveUpdates()
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          className="relative"
          aria-label={
            items.length === 0
              ? "Notifications, none new"
              : `Notifications, ${items.length} waiting`
          }
        >
          <Bell strokeWidth={1.5} aria-hidden="true" />
          {items.length > 0 && (
            <span
              aria-hidden="true"
              className="absolute top-1 right-1 size-2 rounded-full bg-highlight"
            />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px] pop-surface p-0">
        <div className="flex items-center justify-between border-b border-border px-3.5 py-2.5">
          <span className="font-semibold">Notifications</span>
        </div>
        <PendingList items={items} onNavigate={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}
