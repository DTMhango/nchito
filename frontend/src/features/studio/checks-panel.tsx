import { useState, type FormEvent, type ReactNode } from "react"
import { useMutation } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Lock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { modKey } from "@/components/key-hint"
import { cn } from "@/lib/utils"
import { waiveOnce, type CheckResult, type GuardrailOut } from "./api"
import {
  checkLabel,
  groupChecks,
  waivability,
  type ClaimRef,
  type FactIndex,
  traceClaim,
} from "./draft"
import type { CheckState } from "./use-draft"

type Props = {
  applicationId: string
  results: CheckResult[]
  guardrails: GuardrailOut[]
  checkState: CheckState
  /** Why the server says the last check no longer holds (`SpecStateOut.stale_reasons`). */
  staleReasons: string[]
  rechecking: boolean
  onRecheck: () => void
  /** Claims in the draft, for the live fact-tracing list. */
  claims: ClaimRef[]
  index: FactIndex
  onFocusClaim: (c: ClaimRef) => void
  /** After a waiver: run the checks again so the result shows as waived. */
  onWaived: () => void
}

const STATE_TEXT: Record<
  CheckState,
  { chip: string; tone: "good" | "warn" | "neutral" }
> = {
  current: { chip: "Up to date", tone: "good" },
  stale: { chip: "Edited since last check", tone: "warn" },
  unchecked: { chip: "Not checked yet", tone: "neutral" },
}

/**
 * The checks for this application (DESIGN 5.3, 9.3): blocking results first, then warnings,
 * then what passed. Fact tracing of the draft on screen is shown live; whether the server's
 * results still hold comes from the spec state (unsaved edits count as stale too).
 */
export function ChecksPanel({
  applicationId,
  results,
  guardrails,
  checkState,
  staleReasons,
  rechecking,
  onRecheck,
  claims,
  index,
  onFocusClaim,
  onWaived,
}: Props) {
  const [waiving, setWaiving] = useState<{
    result: CheckResult
    guardrail: GuardrailOut
  } | null>(null)
  const [showPassed, setShowPassed] = useState(false)
  const groups = groupChecks(results)
  const flagged = claims.filter((c) => {
    if (!c.item.text.trim()) return false
    const t = traceClaim(c.item, index)
    return t.state !== "traced" || t.strayFigures.length > 0
  })
  const state =
    checkState === "stale" && staleReasons.length > 0
      ? { chip: "Out of date", tone: "warn" as const }
      : STATE_TEXT[checkState]

  return (
    <section aria-labelledby="checks-title" className="grid gap-3 panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="checks-title" className="text-md">
          Checks
        </h3>
        <Chip tone={state.tone} data-check-state={checkState}>
          {state.chip}
        </Chip>
        <Button
          size="sm"
          variant={checkState === "current" ? "ghost" : "outline"}
          className="ml-auto"
          disabled={rechecking}
          onClick={onRecheck}
          aria-keyshortcuts="Control+Enter Meta+Enter"
          title={`Re-check (${modKey()} Enter)`}
        >
          <RefreshCw
            aria-hidden="true"
            className={cn(rechecking && "animate-spin")}
          />
          {rechecking ? "Checking..." : "Re-check"}
        </Button>
      </div>

      {checkState === "stale" && (
        <div className="grid gap-1 rounded-sm bg-warn-soft px-2.5 py-1.5 text-sm text-warn">
          <p>
            {staleReasons.length > 0
              ? "The results below no longer describe this draft; re-check before sending."
              : "You edited the draft after the last check. The results below are for the earlier version; re-check before sending."}
          </p>
          {staleReasons.length > 0 && (
            <ul
              className="m-0 list-disc pl-5"
              aria-label="Why the check is out of date"
            >
              {staleReasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid gap-1.5">
        <div className="flex items-baseline gap-2">
          <h4 className="eyebrow">Fact tracing, live</h4>
          <span className="ml-auto num text-sm">
            {claims.filter((c) => c.item.text.trim()).length - flagged.length}/
            {claims.filter((c) => c.item.text.trim()).length} traced
          </span>
        </div>
        {flagged.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Every claim rests on an approved fact.
          </p>
        ) : (
          <ul
            className="m-0 grid list-none gap-1 p-0"
            aria-label="Claims to fix"
          >
            {flagged.map((c) => (
              <li key={c.item.key}>
                <button
                  type="button"
                  onClick={() => onFocusClaim(c)}
                  className="grid w-full grid-cols-[16px_minmax(0,1fr)] gap-2 rounded-sm px-1.5 py-1 text-left text-sm hover:bg-sunken focus-visible:outline-2 focus-visible:outline-primary-ink"
                >
                  <AlertTriangle
                    aria-hidden="true"
                    className="mt-0.5 size-4 text-danger"
                  />
                  <span className="min-w-0">
                    <span className="block truncate">{c.item.text}</span>
                    <span className="text-xs text-faint">{c.where}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {results.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No check results yet. Re-check to run fact tracing, guardrails and
          limits over the whole packet.
        </p>
      ) : (
        <div
          className={cn("grid gap-3", checkState === "stale" && "opacity-70")}
        >
          <Group
            title="Blocking"
            tone="danger"
            empty="Nothing blocks this application."
            items={groups.block}
            render={(r) => {
              const w = waivability(r, guardrails)
              return (
                <ResultRow
                  key={key(r)}
                  result={r}
                  label={checkLabel(r, guardrails)}
                  icon={ShieldAlert}
                  tone="danger"
                >
                  {w.kind === "waivable" ? (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() =>
                        setWaiving({ result: r, guardrail: w.guardrail })
                      }
                    >
                      Waive once…
                    </Button>
                  ) : w.kind === "always_block" ? (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <Lock aria-hidden="true" className="size-3" />
                      {w.reason}
                    </span>
                  ) : null}
                </ResultRow>
              )
            }}
          />
          <Group
            title="Warnings"
            tone="warn"
            empty="No warnings."
            items={groups.warn}
            render={(r) => (
              <ResultRow
                key={key(r)}
                result={r}
                label={checkLabel(r, guardrails)}
                icon={AlertTriangle}
                tone="warn"
              />
            )}
          />
          {groups.waived.length > 0 && (
            <Group
              title="Waived for this application"
              tone="info"
              items={groups.waived}
              render={(r) => (
                <ResultRow
                  key={key(r)}
                  result={r}
                  label={checkLabel(r, guardrails)}
                  icon={ShieldCheck}
                  tone="info"
                />
              )}
            />
          )}
          <div>
            <button
              type="button"
              aria-expanded={showPassed}
              onClick={() => setShowPassed((v) => !v)}
              className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              <ChevronDown
                aria-hidden="true"
                className={cn(
                  "size-4 transition-transform",
                  showPassed && "rotate-180"
                )}
              />
              Passed ({groups.pass.length})
            </button>
            {showPassed && (
              <ul className="m-0 mt-1 grid list-none p-0">
                {groups.pass.map((r) => (
                  <ResultRow
                    key={key(r)}
                    result={r}
                    label={checkLabel(r, guardrails)}
                    icon={Check}
                    tone="good"
                  />
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {waiving && (
        <WaiverDialog
          applicationId={applicationId}
          guardrail={waiving.guardrail}
          result={waiving.result}
          onClose={() => setWaiving(null)}
          onWaived={() => {
            setWaiving(null)
            onWaived()
          }}
        />
      )}
    </section>
  )
}

const key = (r: CheckResult) =>
  `${r.check}-${r.guardrail_id ?? ""}-${r.detail ?? ""}`

function Group({
  title,
  tone,
  empty,
  items,
  render,
}: {
  title: string
  tone: "danger" | "warn" | "info"
  empty?: string
  items: CheckResult[]
  render: (r: CheckResult) => ReactNode
}) {
  return (
    <div className="grid gap-1" role="group" aria-label={title}>
      <h4 className="flex items-center gap-2 eyebrow">
        {title}
        <span
          className={cn(
            "num",
            items.length &&
              (tone === "danger"
                ? "text-danger"
                : tone === "warn"
                  ? "text-warn"
                  : "text-info")
          )}
        >
          {items.length}
        </span>
      </h4>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="m-0 grid list-none p-0">{items.map(render)}</ul>
      )}
    </div>
  )
}

function ResultRow({
  result,
  label,
  icon: Icon,
  tone,
  children,
}: {
  result: CheckResult
  label: string
  icon: typeof Check
  tone: "danger" | "warn" | "good" | "info"
  children?: ReactNode
}) {
  return (
    <li
      data-check={result.check}
      className="grid grid-cols-[16px_minmax(0,1fr)] gap-2 border-t border-border py-2 first:border-t-0"
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "mt-0.5 size-4",
          tone === "danger" && "text-danger",
          tone === "warn" && "text-warn",
          tone === "good" && "text-good",
          tone === "info" && "text-info"
        )}
      />
      <div className="grid min-w-0 gap-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <b className="text-sm font-semibold">{label}</b>
          {result.waived && <Chip tone="info">Waived once</Chip>}
        </div>
        {result.detail && (
          <p className="text-sm text-muted-foreground">{result.detail}</p>
        )}
        {children && <div>{children}</div>}
      </div>
    </li>
  )
}

/** "Block, waivable once": one application, with a reason, audited. */
function WaiverDialog({
  applicationId,
  guardrail,
  result,
  onClose,
  onWaived,
}: {
  applicationId: string
  guardrail: GuardrailOut
  result: CheckResult
  onClose: () => void
  onWaived: () => void
}) {
  const [reason, setReason] = useState("")
  const waive = useMutation({
    mutationFn: () => waiveOnce(guardrail.id, applicationId, reason.trim()),
    onSuccess: () => {
      toast.success(`"${guardrail.name}" waived for this application only.`)
      onWaived()
    },
    onError: (e) => toast.error(e.message),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (reason.trim()) waive.mutate()
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Waive “{guardrail.name}” once</DialogTitle>
            <DialogDescription>
              Lets this one application through this rule. The rule still
              applies to every other application. Your reason is kept in the
              audit trail.
            </DialogDescription>
          </DialogHeader>
          {result.detail && (
            <p className="rounded-sm bg-sunken px-2.5 py-1.5 text-sm">
              {result.detail}
            </p>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="waive-reason">Reason (required)</Label>
            <Textarea
              id="waive-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={2000}
              placeholder="Why this application may break the rule"
              required
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!reason.trim() || waive.isPending}>
              Waive for this application
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
