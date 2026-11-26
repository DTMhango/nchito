import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { CirclePause, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { useAutopilot } from "@/app/shell/autopilot-switch"
import type { PauseItem } from "@/lib/api/types"
import { RestorePanel } from "./restore-panel"
import { stamp } from "./logic"

const who = (by: string | null) =>
  !by ? null : by === "owner" ? "you" : by === "system" ? "the system" : by

/**
 * The master pause (DESIGN 8.1): one control that stops every new outward action, with the
 * state in words (when, by whom, why) and, once paused, what the pause did.
 */
export function MasterPause() {
  const { state, setPaused, pending } = useAutopilot()
  const [reason, setReason] = useState("")
  const { cancelled, already_out } = state.summary
  const by = who(state.paused_by)
  return (
    <div className="grid gap-3">
      <section
        aria-label="Master pause"
        className={
          state.paused
            ? "grid gap-3 rounded-lg border border-border bg-warn-soft p-4 text-warn"
            : "grid gap-3 rounded-lg border border-border bg-surface p-4"
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="grid min-w-0 flex-1 gap-1">
            <h3 className="text-md">
              {state.paused
                ? "All automatic sending is paused"
                : "Automatic sending is on"}
            </h3>
            <p
              className={
                state.paused ? "text-sm" : "text-sm text-muted-foreground"
              }
              aria-live="polite"
            >
              {state.paused ? (
                <>
                  Paused
                  {by && ` by ${by}`}{" "}
                  {state.paused_at
                    ? `on ${stamp(state.paused_at)}`
                    : "just now"}
                  .{" "}
                  {state.reason && (
                    <span data-testid="pause-reason">
                      Reason: {state.reason}.{" "}
                    </span>
                  )}
                  Nothing new is sent, submitted or handed to a runner until you
                  resume.{" "}
                  <Link
                    to="/settings/activity"
                    className="underline underline-offset-2"
                  >
                    Activity log
                  </Link>
                </>
              ) : (
                "Pausing stops every new send at once and cancels queued emails. Anything already handed to a provider cannot be recalled."
              )}
            </p>
          </div>
          <Chip tone={state.paused ? "warn" : "good"} icon={CirclePause}>
            {state.paused ? "Paused" : "Running"}
          </Chip>
          {state.paused ? (
            <Button disabled={pending} onClick={() => setPaused(false)}>
              <Play aria-hidden="true" />
              Resume automatic sending
            </Button>
          ) : (
            <Button
              variant="outline"
              disabled={pending}
              onClick={() => {
                setPaused(true, reason)
                setReason("")
              }}
            >
              <CirclePause aria-hidden="true" />
              Pause all automatic sending
            </Button>
          )}
        </div>
        {!state.paused && (
          <label className="grid max-w-md gap-1 text-sm font-medium">
            Reason for pausing (optional)
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="For the activity log"
            />
          </label>
        )}
        {state.paused && (
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <PausedList title="Cancelled before sending" items={cancelled} />
            <PausedList
              title="Already handed over (cannot be recalled)"
              items={already_out}
            />
          </div>
        )}
      </section>
      <RestorePanel />
    </div>
  )
}

function PausedList({ title, items }: { title: string; items: PauseItem[] }) {
  return (
    <div className="grid gap-1">
      <h4 className="eyebrow">{title}</h4>
      {items.length === 0 ? (
        <p>None.</p>
      ) : (
        <ul className="grid gap-0.5">
          {items.map((i) => (
            <li key={i.id}>
              <b className="font-semibold">{i.label}</b>
              {i.detail && <> · {i.detail}</>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
