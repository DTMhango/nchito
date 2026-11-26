import { Link } from "@tanstack/react-router"
import { CirclePause, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { useAutopilot } from "@/app/shell/autopilot-switch"
import type { PauseItem } from "@/lib/api/types"

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null

/**
 * The master pause (DESIGN 8.1): one control that stops every new outward action, with the
 * state in words and, once paused, what the pause did. The contract records when it was
 * paused; who paused it is in the activity log.
 */
export function MasterPause() {
  const { state, setPaused, pending } = useAutopilot()
  const { cancelled, already_out } = state.summary
  return (
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
                Paused {when(state.paused_at) ?? "just now"}.{" "}
                <Link
                  to="/settings/activity"
                  className="underline underline-offset-2"
                >
                  See who paused it in the activity log
                </Link>
                . Nothing new is sent, submitted or handed to a runner until you
                resume.
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
            onClick={() => setPaused(true)}
          >
            <CirclePause aria-hidden="true" />
            Pause all automatic sending
          </Button>
        )}
      </div>
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
