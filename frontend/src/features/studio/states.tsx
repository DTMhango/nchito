import { Link } from "@tanstack/react-router"
import {
  AlertTriangle,
  CircleCheck,
  CircleDashed,
  LoaderCircle,
  PauseCircle,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { formatCost, microsOf } from "@/lib/cost"
import { cn } from "@/lib/utils"
import type { RunOut } from "./api"

export const runCost = (run: RunOut | undefined) =>
  run ? formatCost(microsOf(run, "cost")) : null

const STEPS = [
  {
    title: "Select",
    body: "Picking facts by track, tags and the posting's keywords.",
  },
  {
    title: "Draft",
    body: "Writing the CV, letter and requirement match, each line citing its facts.",
  },
  {
    title: "Check",
    body: "Fact tracing, guardrails, limits and keyword coverage.",
  },
]

/** Tailoring in progress: the run is polled, and the SSE stream nudges a refetch. */
export function TailoringProgress({ run }: { run: RunOut | undefined }) {
  const step = run?.status === "running" ? 1 : 0
  return (
    <section
      aria-live="polite"
      aria-labelledby="tailoring-title"
      className="grid max-w-[640px] gap-4 panel p-5"
    >
      <div className="flex items-center gap-2">
        <LoaderCircle
          aria-hidden="true"
          className="size-5 animate-spin text-primary-ink"
        />
        <h3 id="tailoring-title" className="text-md">
          Tailoring this application
        </h3>
        <Chip tone="info" className="ml-auto">
          {run?.status === "running" ? "Drafting" : "Queued"}
        </Chip>
      </div>
      <ol className="m-0 grid list-none gap-2.5 p-0">
        {STEPS.map((s, i) => {
          const Icon =
            i < step ? CircleCheck : i === step ? LoaderCircle : CircleDashed
          return (
            <li
              key={s.title}
              className="grid grid-cols-[18px_minmax(0,1fr)] gap-2.5"
            >
              <Icon
                aria-hidden="true"
                className={cn(
                  "mt-0.5 size-[18px]",
                  i < step && "text-good",
                  i === step && "animate-spin text-primary-ink",
                  i > step && "text-faint"
                )}
              />
              <div>
                <b
                  className={cn(
                    "font-semibold",
                    i > step && "text-muted-foreground"
                  )}
                >
                  {s.title}
                </b>
                <p className="text-sm text-muted-foreground">{s.body}</p>
              </div>
            </li>
          )
        })}
      </ol>
      <p className="text-sm text-faint">
        You can leave this page; the draft will be here when you come back.
        {run && ` Spent so far: ${runCost(run)}.`}
      </p>
    </section>
  )
}

/** The monthly AI budget stopped the run (CONTRACTS: a budget refusal ends it `paused`). */
export function BudgetPaused({
  run,
  onRetry,
  retrying,
}: {
  run: RunOut
  onRetry: () => void
  retrying: boolean
}) {
  return (
    <section
      role="status"
      aria-labelledby="paused-title"
      className="grid max-w-[640px] gap-3 panel border-l-4 border-l-warn p-5"
    >
      <div className="flex items-center gap-2">
        <PauseCircle aria-hidden="true" className="size-5 text-warn" />
        <h3 id="paused-title" className="text-md">
          Paused: the AI budget is used up
        </h3>
      </div>
      <p className="text-muted-foreground">
        {run.error ??
          "Tailoring stopped at the spending cap before it drafted anything."}
      </p>
      <p className="text-sm">
        Cost of this tailoring so far:{" "}
        <b className="num" data-testid="tailor-cost">
          {runCost(run)}
        </b>
      </p>
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link to="/settings/ai">Review the budget in Settings › AI</Link>
        </Button>
        <Button variant="outline" disabled={retrying} onClick={onRetry}>
          Try again
        </Button>
      </div>
    </section>
  )
}

export function TailorFailed({
  run,
  onRetry,
  retrying,
}: {
  run: RunOut
  onRetry: () => void
  retrying: boolean
}) {
  return (
    <section
      role="alert"
      className="grid max-w-[640px] gap-3 panel border-l-4 border-l-danger p-5"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle aria-hidden="true" className="size-5 text-danger" />
        <h3 className="text-md">Tailoring did not finish</h3>
      </div>
      <p className="text-muted-foreground">
        {run.error ?? "The run stopped with an error."} Nothing was sent.
      </p>
      <p className="text-sm">
        Cost of this attempt: <b className="num">{runCost(run)}</b>
      </p>
      <div>
        <Button disabled={retrying} onClick={onRetry}>
          Try again
        </Button>
      </div>
    </section>
  )
}

/** No draft yet: tailoring spends AI budget, so it starts only when asked. */
export function NotTailored({
  onTailor,
  pending,
  error,
}: {
  onTailor: () => void
  pending: boolean
  error: string | null
}) {
  return (
    <section
      aria-labelledby="untailored-title"
      className="grid max-w-[640px] gap-3 panel p-5"
    >
      <div className="flex items-center gap-2">
        <Sparkles aria-hidden="true" className="size-5 text-primary-ink" />
        <h3 id="untailored-title" className="text-md">
          Not tailored yet
        </h3>
      </div>
      <p className="text-muted-foreground">
        Tailoring drafts a CV and cover letter for this role from your approved
        facts, matches each requirement to its evidence, and runs the checks. It
        uses your AI budget.
      </p>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div>
        <Button onClick={onTailor} disabled={pending}>
          <Sparkles aria-hidden="true" />
          {pending ? "Starting..." : "Tailor this application"}
        </Button>
      </div>
    </section>
  )
}
