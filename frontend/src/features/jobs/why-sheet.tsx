import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { HelpCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { WhyPanel, type WhyReason } from "@/components/why-panel"
import { Skeleton } from "@/components/ui/skeleton"
import { whyQuery, type WhyOut } from "./api"

/** Map the endpoint's rules onto the shared panel. "info" rules did not decide anything, so they read as passed. */
export function whyToPanel(why: WhyOut): {
  reasons: WhyReason[]
  toProceed: string[]
} {
  return {
    reasons: why.rules.map((r) => ({
      rule: r.rule,
      value: r.effective_value,
      source: r.source,
      version: r.version ?? undefined,
      outcome: r.outcome === "info" ? "pass" : r.outcome,
      detail: r.reason,
    })),
    toProceed: why.rules.flatMap((r) =>
      r.would_change_if ? [r.would_change_if] : []
    ),
  }
}

/** The persistent "Why?" button and the panel it opens, built from the why endpoint. */
export function WhyButton({ jobId }: { jobId: string }) {
  const [open, setOpen] = useState(false)
  const q = useQuery(whyQuery(jobId, open))
  const panel = q.data ? whyToPanel(q.data) : null
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <HelpCircle aria-hidden="true" />
        Why?
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-[min(480px,100vw)] overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Why this role is where it is</SheetTitle>
            <SheetDescription>
              Each rule involved, its value, where it came from and what would
              have to change.
            </SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-4">
            {q.isPending && <Skeleton className="h-32 w-full bg-sunken" />}
            {q.isError && (
              <p className="text-sm text-danger">Could not load the reasons.</p>
            )}
            {panel && q.data && (
              <WhyPanel
                decision={q.data.decision}
                reasons={panel.reasons}
                toProceed={panel.toProceed}
              />
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
