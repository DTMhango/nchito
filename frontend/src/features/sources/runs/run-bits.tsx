import { useEffect, useState } from "react"
import { FlaskConical } from "lucide-react"
import { Chip } from "@/components/chip"
import { FunnelStrip, type FunnelStep } from "@/components/funnel-strip"
import type { Run } from "../api"
import { isActive } from "../api"
import { duration, STATUS_LABEL, STATUS_TONE } from "../words"

const SWEEP_STEPS: [string, string][] = [
  ["found", "Found"],
  ["new", "New"],
  ["passed_filters", "Passed filters"],
  ["above_threshold", "Above threshold"],
  ["tailored", "Tailored"],
  ["applied", "Applied"],
]

/** Counts as a funnel strip. Non-sweep runs show their own counts in plain pairs. */
export function RunFunnel({ run }: { run: Run }) {
  const c = run.counts as Record<string, number>
  if (run.kind === "sweep" || run.kind === "rescore") {
    const steps: FunnelStep[] = SWEEP_STEPS.map(([k, label]) => ({
      label,
      value: c[k] ?? 0,
    }))
    return <FunnelStrip steps={steps} label={`${run.kind} funnel`} />
  }
  const entries = Object.entries(c)
  if (!entries.length) return null
  return (
    <FunnelStrip
      label="Run counts"
      steps={entries.map(([k, v]) => ({
        label: k.replace(/_/g, " "),
        value: v,
      }))}
    />
  )
}

export function StatusChip({ run }: { run: Run }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Chip tone={STATUS_TONE[run.status]}>{STATUS_LABEL[run.status]}</Chip>
      {run.dry_run && (
        <Chip tone="info" icon={FlaskConical}>
          Dry run
        </Chip>
      )}
    </span>
  )
}

/** Elapsed time that ticks while a run is active. */
export function Elapsed({ run }: { run: Run }) {
  const active = isActive(run.status)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  return (
    <span className="num">
      {duration(run.started_at, run.finished_at, now)}
    </span>
  )
}

const ACTION_LABEL: Record<string, string> = {
  apply: "Apply",
  ask_owner: "Ask you",
  prepare: "Prepare",
  add_to_matches: "Add to Matches",
  review: "Review",
  skip: "Skip",
  parked: "Park",
}

/** Shown on every dry run: the one thing the owner must be sure of. */
export function DryRunBanner({ run }: { run: Run }) {
  const actions = run.proposed_actions ?? []
  const running = isActive(run.status)
  return (
    <section
      aria-label="Dry run"
      className="mb-5 grid gap-2 rounded-lg border border-info bg-info-soft p-4"
    >
      <h2 className="flex items-center gap-2 text-md font-semibold text-info">
        <FlaskConical className="size-4" aria-hidden="true" />
        Dry run: nothing was changed
      </h2>
      <p className="text-sm">
        This run only worked out what would happen at your current settings. No
        roles were saved, no documents were prepared and nothing was sent.
      </p>
      {actions.length > 0 ? (
        <>
          <h3 className="mt-1 eyebrow">What it would have done</h3>
          <ul className="grid gap-1.5 text-sm">
            {actions.map((a, i) => (
              <li key={`${a.job_id ?? a.title}-${i}`} className="flex gap-2">
                <Chip tone="line" className="shrink-0">
                  {ACTION_LABEL[a.action] ?? a.action.replace(/_/g, " ")}
                </Chip>
                <span>
                  {a.title} at {a.employer}
                  {a.score != null && (
                    <span className="num text-faint"> · {a.score}</span>
                  )}
                  <span className="text-muted-foreground"> ({a.reason})</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          {running
            ? "Proposed actions appear here when the run finishes."
            : "It would not have done anything."}
        </p>
      )}
    </section>
  )
}
