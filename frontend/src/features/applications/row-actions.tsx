import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { AlarmClock, Pin, PinOff } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { appKeys, patchApplication, type ApplicationSummary } from "./api"
import { shortDate, todayIn } from "./format"

function usePatch(app: ApplicationSummary, message: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof patchApplication>[1]) =>
      patchApplication(app.id, body),
    onSuccess: () => {
      toast.success(message)
      void qc.invalidateQueries({ queryKey: appKeys.list })
    },
    onError: (e) => toast.error(e.message),
  })
}

export function PinButton({ app }: { app: ApplicationSummary }) {
  const patch = usePatch(app, app.pinned ? "Unpinned." : "Pinned.")
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-pressed={app.pinned}
      disabled={patch.isPending}
      onClick={(e) => {
        e.stopPropagation()
        patch.mutate({ pinned: !app.pinned })
      }}
    >
      {app.pinned ? <PinOff aria-hidden="true" /> : <Pin aria-hidden="true" />}
      {app.pinned ? "Unpin" : "Pin"}
    </Button>
  )
}

/** Snooze until a return date: it leaves the "needs a step" lists until then. */
export function SnoozeButton({
  app,
  timeZone,
}: {
  app: ApplicationSummary
  timeZone?: string
}) {
  const [open, setOpen] = useState(false)
  const [min] = useState(() =>
    todayIn(timeZone, new Date(Date.now() + 86_400_000))
  )
  const [date, setDate] = useState(() =>
    todayIn(timeZone, new Date(Date.now() + 3 * 86_400_000))
  )
  const patch = usePatch(app, `Snoozed until ${shortDate(date)}.`)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={(e) => e.stopPropagation()}
        >
          <AlarmClock aria-hidden="true" />
          Snooze
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-64 pop-surface"
        onClick={(e) => e.stopPropagation()}
      >
        <form
          className="grid gap-2.5"
          onSubmit={(e) => {
            e.preventDefault()
            patch.mutate(
              { snoozed_until: new Date(`${date}T08:00:00`).toISOString() },
              { onSuccess: () => setOpen(false) }
            )
          }}
        >
          <Label htmlFor={`snooze-${app.id}`}>Bring it back on</Label>
          <Input
            id={`snooze-${app.id}`}
            type="date"
            min={min}
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          <Button type="submit" size="sm" disabled={patch.isPending}>
            Snooze until {date ? shortDate(date) : "…"}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  )
}
