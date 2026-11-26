import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Ban, CirclePause, Send } from "lucide-react"
import { toast } from "sonner"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/empty-state"
import { autopilotQuery, keys } from "@/lib/api/endpoints"
import type { AutopilotState, PauseItem } from "@/lib/api/types"
import { cn } from "@/lib/utils"
import { apKeys, refusalOf, writeAutopilot } from "@/features/autopilot/api"

const EMPTY: AutopilotState = {
  paused: false,
  paused_at: null,
  paused_by: null,
  reason: null,
  summary: { cancelled: [], paused: [], already_out: [] },
}

/**
 * The global pause (DESIGN 8.1): one tap stops every new outward action, cancels queued
 * sends, then shows three lists: cancelled, paused, and already handed over. Only
 * `PUT /api/autopilot` changes it (the generic settings write refuses `automation.paused`).
 * While paused for a restore, resume is refused (409 `restore_paused`): the owner resumes from
 * the restore panel once every uncertain send is settled.
 */
export function useAutopilot() {
  const qc = useQueryClient()
  const q = useQuery(autopilotQuery())
  const state = q.data ?? EMPTY

  const m = useMutation({
    mutationFn: (v: { paused: boolean; reason?: string | null }) =>
      writeAutopilot(v.paused, v.reason),
    onSuccess: (data, v) => {
      qc.setQueryData(keys.autopilot, data)
      void qc.invalidateQueries({ queryKey: apKeys.restore })
      if (!v.paused)
        toast.success("Autopilot resumed. Scheduled work picks up from here.")
    },
    onError: (e, v) => {
      const r = refusalOf(e)
      if (r?.code === "restore_paused") {
        toast.error(
          "Paused for a restore. Settle the uncertain sends, then resume from the Autopilot page."
        )
        void qc.invalidateQueries({ queryKey: apKeys.restore })
        return
      }
      toast.error(
        v.paused ? "Couldn't pause. Try again." : "Couldn't resume. Try again."
      )
    },
  })
  return {
    state,
    setPaused: (paused: boolean, reason?: string | null) =>
      m.mutate({ paused, reason }),
    pending: m.isPending,
  }
}

export function AutopilotSwitch() {
  const { state, setPaused, pending } = useAutopilot()
  const [sheetOpen, setSheetOpen] = useState(false)
  const running = !state.paused

  const onClick = () => {
    if (running) {
      setPaused(true)
      setSheetOpen(true)
    } else {
      setPaused(false)
    }
  }

  return (
    <>
      <button
        type="button"
        role="switch"
        aria-checked={running}
        aria-label={
          running
            ? "Autopilot running. Pause it"
            : "Autopilot paused. Resume it"
        }
        title="Pause or resume Autopilot"
        disabled={pending}
        onClick={onClick}
        className={cn(
          "inline-flex h-8 items-center gap-2 rounded-full border border-transparent pr-3 pl-2.5 text-[0.86rem] font-semibold whitespace-nowrap transition-colors disabled:opacity-70",
          running
            ? "border-good-soft bg-good-soft text-good"
            : "bg-warn-soft text-warn"
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "size-2 rounded-full bg-current",
            running && "animate-pulse-soft"
          )}
        />
        <span className="font-medium text-muted-foreground max-md:hidden">
          Autopilot
        </span>
        <span>{running ? "Running" : "Paused"}</span>
      </button>
      <PauseSummarySheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        state={state}
        onResume={() => {
          setPaused(false)
          setSheetOpen(false)
        }}
      />
    </>
  )
}

function PauseSummarySheet({
  open,
  onOpenChange,
  state,
  onResume,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  state: AutopilotState
  onResume: () => void
}) {
  const { cancelled, paused, already_out } = state.summary
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-[420px]">
        <SheetHeader className="border-b border-border">
          <SheetTitle className="heading text-lg">
            Autopilot is paused
          </SheetTitle>
          <SheetDescription>
            Nothing new will be sent, submitted or handed to a runner until you
            resume. Here is what the pause did.
          </SheetDescription>
        </SheetHeader>
        <div className="grid flex-1 content-start gap-5 overflow-auto p-4">
          <PauseList
            icon={Ban}
            title="Cancelled"
            hint="Queued sends that had not left yet."
            items={cancelled}
            empty="Nothing was queued, so nothing needed cancelling."
          />
          <PauseList
            icon={CirclePause}
            title="Paused"
            hint="Tailoring, agent tasks and follow-ups waiting for you."
            items={paused}
            empty="No work was in progress."
          />
          <PauseList
            icon={Send}
            title="Already handed over"
            hint="Sent to a mail provider or submitted. These can't be recalled."
            items={already_out}
            empty="Nothing had left. You're fully stopped."
          />
        </div>
        <SheetFooter className="border-t border-border">
          <Button onClick={onResume}>Resume Autopilot</Button>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Stay paused
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function PauseList({
  icon: Icon,
  title,
  hint,
  items,
  empty,
}: {
  icon: typeof Ban
  title: string
  hint: string
  items: PauseItem[]
  empty: string
}) {
  return (
    <section className="grid gap-2">
      <div className="flex items-baseline gap-2">
        <Icon
          className="size-4 self-center text-muted-foreground"
          aria-hidden="true"
        />
        <h3 className="text-base">{title}</h3>
        <span className="num text-sm text-faint">{items.length}</span>
      </div>
      <p className="text-sm text-muted-foreground">{hint}</p>
      {items.length === 0 ? (
        <div className="rounded-sm border border-dashed border-border-strong">
          <EmptyState title={empty} className="py-4" />
        </div>
      ) : (
        <ul className="grid border-t border-border">
          {items.map((it) => (
            <li key={it.id} className="border-b border-border row-pad">
              <div className="font-semibold">{it.label}</div>
              <div className="text-sm text-muted-foreground">{it.detail}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
