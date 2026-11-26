import { useQuery } from "@tanstack/react-query"
import { Check, X } from "lucide-react"
import type { ChipTone } from "@/components/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { WhyPanel, type WhyReason } from "@/components/why-panel"
import { cn } from "@/lib/utils"
import { whyQuery } from "./api"
import { valueLabel } from "./filters"
import type { ConditionResult, WhyOut } from "./types"

function decisionTone(decision: string): ChipTone {
  const d = decision.toLowerCase()
  if (d.includes("held") || d.includes("review")) return "warn"
  if (d.includes("block") || d.includes("excluded") || d.includes("fail"))
    return "danger"
  if (
    d.includes("shortlist") ||
    d.includes("applied") ||
    d.includes("tailored")
  )
    return "good"
  return "neutral"
}

/** WhyOut from the API as the shared panel's reasons. */
export function whyReasons(why: WhyOut): {
  reasons: WhyReason[]
  toProceed: string[]
} {
  return {
    reasons: why.rules.map((r) => ({
      rule: r.rule,
      value: r.effective_value,
      source: r.source,
      version: r.version ?? undefined,
      outcome: r.outcome,
      detail: r.reason,
    })),
    toProceed: why.rules
      .filter((r) => r.would_change_if && r.outcome !== "pass")
      .map((r) => `${r.rule}: ${r.would_change_if}`),
  }
}

/** "Why?" (DESIGN 18.4): what happened, each rule's value and source, what would change it. */
export function WhySection({
  jobId,
  className,
}: {
  jobId: string
  className?: string
}) {
  const why = useQuery(whyQuery(jobId))
  if (why.isLoading) return <Skeleton className={cn("h-32", className)} />
  if (!why.data) return <WhyPanel reasons={[]} className={className} />
  const { reasons, toProceed } = whyReasons(why.data)
  return (
    <div className={cn("grid gap-3", className)}>
      <WhyPanel
        decision={why.data.decision}
        decisionTone={decisionTone(why.data.decision)}
        reasons={reasons}
        toProceed={toProceed}
      />
      {!!why.data.conditions?.length && (
        <section className="grid gap-1.5 px-1" aria-label="Conditions checked">
          <h4 className="eyebrow">Conditions checked</h4>
          <ConditionTree nodes={why.data.conditions} />
        </section>
      )}
    </div>
  )
}

function ConditionTree({ nodes }: { nodes: ConditionResult[] }) {
  return (
    <ul className="grid gap-1 text-sm">
      {nodes.map((n, i) => (
        <li key={`${n.facet ?? n.kind}-${i}`} className="grid gap-1">
          <div className="grid grid-cols-[16px_minmax(0,1fr)] gap-2">
            {n.matched ? (
              <Check className="mt-0.5 size-4 text-good" aria-label="Matched" />
            ) : (
              <X
                className="mt-0.5 size-4 text-danger"
                aria-label="Did not match"
              />
            )}
            <span>
              {n.detail ?? n.kind}
              {n.facet && (
                <span className="text-muted-foreground">
                  {" "}
                  · {n.facet.split(".").pop()?.replace(/_/g, " ")} is{" "}
                  {n.actual == null
                    ? "not stated"
                    : valueLabel(String(n.actual))}
                </span>
              )}
            </span>
          </div>
          {!!n.children?.length && (
            <div className="pl-6">
              <ConditionTree nodes={n.children} />
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
