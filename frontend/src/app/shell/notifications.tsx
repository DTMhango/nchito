import { Bell } from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/empty-state"

/** Notifications bell. Empty in wave 0; the Action centre feeds it later. */
export function Notifications() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          aria-label="Notifications, none new"
        >
          <Bell strokeWidth={1.5} aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px] pop-surface p-0">
        <div className="flex items-center justify-between border-b border-border px-3.5 py-2.5">
          <span className="font-semibold">Notifications</span>
        </div>
        <EmptyState
          icon={Bell}
          title="Nothing new"
          description="Approvals, sign-in requests, new questions and replies from employers will show up here, newest first."
        />
      </PopoverContent>
    </Popover>
  )
}
