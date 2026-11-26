import {
  CircleCheck,
  CircleHelp,
  CircleX,
  HelpCircle,
  Info,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Chip, type ChipTone } from "./chip"
import { EmptyState } from "./empty-state"

/** "info" marks a rule that applied without deciding anything (e.g. quiet hours). */
export type WhyOutcome = "pass" | "fail" | "unknown" | "info"

export type WhyReason = {
  /** The rule or gate, e.g. "Auto-apply threshold" or "One role per employer". */
  rule: string
  /** The effective value, e.g. "85" or "Same department". */
  value: string
  /** Where the value came from: "Campaign: Data leadership", "Settings default". */
  source: string
  /** Config version, e.g. "rubric v4". */
  version?: string
  outcome: WhyOutcome
  /** What the gate said, e.g. "Score 74 is below 85". */
  detail?: string
}

type WhyPanelProps = {
  /** The decision being explained: "Held", "Not applied", "Tailored", "Skipped". */
  decision?: string
  decisionTone?: ChipTone
  reasons: WhyReason[]
  /** What would have to change for the role to go ahead. */
  toProceed?: string[]
  className?: string
}

const OUTCOME = {
  pass: { icon: CircleCheck, cls: "text-good", text: "Passed" },
  fail: { icon: CircleX, cls: "text-danger", text: "Stopped it" },
  unknown: { icon: CircleHelp, cls: "text-warn", text: "Unknown" },
  info: { icon: Info, cls: "text-info", text: "For information" },
} as const

/**
 * "Why?" panel (DESIGN 18.4): why a role was held, skipped, tailored or not applied, each
 * rule's effective value, where it came from and its version, and what would need to change.
 * Built from the reasons the gates return. Shell for wave 0; data arrives with the pipeline.
 */
export function WhyPanel({
  decision,
  decisionTone = "neutral",
  reasons,
  toProceed = [],
  className,
}: WhyPanelProps) {
  return (
    <section
      aria-labelledby="why-title"
      className={cn("grid gap-3 panel p-4", className)}
    >
      <div className="flex items-center gap-2">
        <HelpCircle
          className="size-[18px] text-primary-ink"
          strokeWidth={1.5}
          aria-hidden="true"
        />
        <h3 id="why-title" className="text-md">
          Why?
        </h3>
        {decision && (
          <Chip tone={decisionTone} className="ml-auto">
            {decision}
          </Chip>
        )}
      </div>

      {reasons.length === 0 ? (
        <EmptyState
          title="No decision yet"
          description="When a rule holds, skips, tailors or applies this role, each rule involved shows here with its value, where that value came from, and its version."
          className="py-4"
        />
      ) : (
        <ul className="grid">
          {reasons.map((r, i) => {
            const o = OUTCOME[r.outcome]
            return (
              <li
                key={`${r.rule}-${i}`}
                className="grid grid-cols-[18px_minmax(0,1fr)] gap-2.5 border-t border-border row-pad first:border-t-0"
              >
                <o.icon
                  className={cn("mt-0.5 size-[18px]", o.cls)}
                  strokeWidth={1.5}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-semibold">{r.rule}</span>
                    <span className="num text-sm">{r.value}</span>
                    <span className="sr-only">{o.text}.</span>
                  </div>
                  {r.detail && (
                    <div className="text-sm text-muted-foreground">
                      {r.detail}
                    </div>
                  )}
                  <div className="text-xs text-faint">
                    {r.source}
                    {r.version && <span className="num"> · {r.version}</span>}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {toProceed.length > 0 && (
        <div className="grid gap-1.5 rounded-sm bg-sunken p-3">
          <div className="eyebrow">For it to go ahead</div>
          <ul className="grid list-disc gap-1 pl-5 text-sm">
            {toProceed.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
