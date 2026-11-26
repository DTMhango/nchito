import { useEffect, useId, useMemo, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { Download, Undo2 } from "lucide-react"
import { toast } from "sonner"
import { STAGE_META } from "@/components/stage-pill"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { campaignsQuery } from "@/features/applications/api"
import {
  ACTION_LABEL,
  POLL_MS,
  bulkKeys,
  bulkOptionsQuery,
  bulkPreview,
  bulkRun,
  csvUrl,
  getOperation,
  isRunning,
  listItems,
  undoOperation,
  type BulkAction,
  type BulkParams,
  type BulkSubject,
  type ItemOut,
  type OperationOut,
  type PreviewOut,
  type ReasonGroup,
  type ViewSelection,
} from "./api"
import { useBulkEvents } from "./use-bulk-events"

const plural = (n: number, one: string, many = `${one}s`) =>
  `${n} ${n === 1 ? one : many}`

/** Everything a bulk run can change is cached under these keys; refetch them when it ends. */
export function refreshAfterBulk(qc: QueryClient) {
  for (const key of ["matches", "jobs", "applications", "employers", "today"])
    void qc.invalidateQueries({ queryKey: [key] })
}

/** Stages an owner can move an application to by hand (runner-owned ones are left out). */
const MOVE_TARGETS = [
  "shortlisted",
  "tailoring",
  "ready",
  "screening",
  "interview",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
  "closed",
] as const

export type BulkScope = {
  /** The ticked rows. */
  ids: string[]
  /** "Everything matching this view": the server resolves it; `count` is what the list shows. */
  view?: { selection: ViewSelection; count: number | null }
}

type Props = {
  open: boolean
  subject: BulkSubject
  scope: BulkScope
  /** The action to start on; the owner can change it. */
  initialAction?: BulkAction
  onOpenChange: (open: boolean) => void
  /** A run happened: clear the selection. */
  onDone?: () => void
}

type Phase = "setup" | "preview" | "run"

/**
 * One dialog for bulk actions on Matches and Applications: pick the action, preview (what will
 * change and what cannot, grouped by reason), run with live progress, then see every result.
 * Nothing changes until the owner confirms the previewed count. There is no bulk "approve and
 * send": `send_for_approval` only builds each packet and lets the approval policy act.
 */
export function BulkDialog({
  open,
  subject,
  scope,
  initialAction,
  onOpenChange,
  onDone,
}: Props) {
  const qc = useQueryClient()
  const uid = useId()
  const options = useQuery({ ...bulkOptionsQuery(), enabled: open })
  const campaigns = useQuery({ ...campaignsQuery(), enabled: open })

  const actions = useMemo(() => {
    const list = options.data?.actions?.[subject] ?? []
    return list.filter(
      (a) => a !== "approve_reviewed" || options.data?.approve_reviewed_enabled
    )
  }, [options.data, subject])

  const [action, setAction] = useState<BulkAction | "">(initialAction ?? "")
  const [useView, setUseView] = useState(false)
  const [tag, setTag] = useState("")
  const [reason, setReason] = useState("")
  const [until, setUntil] = useState("")
  const [stage, setStage] = useState<string>("")
  const [campaignId, setCampaignId] = useState("")
  const [phase, setPhase] = useState<Phase>("setup")
  const [preview, setPreview] = useState<PreviewOut | null>(null)
  const [opId, setOpId] = useState<string | null>(null)

  const viewCount = scope.view?.count ?? null
  const chosenAction: BulkAction | "" = action || actions[0] || ""
  const chosenCampaign = campaignId || campaigns.data?.items[0]?.id || ""
  const chosenStage = stage || MOVE_TARGETS[0]

  const params: BulkParams = {
    tag: tag.trim().toLowerCase() || null,
    reason: reason.trim() || null,
    until: until || null,
    stage: chosenAction === "move_stage" ? chosenStage : null,
    campaign_id: chosenAction === "assign_campaign" ? chosenCampaign : null,
  }
  const missing =
    ((chosenAction === "tag" || chosenAction === "untag") && !params.tag) ||
    (chosenAction === "skip" && !params.reason) ||
    (chosenAction === "snooze" && !params.until) ||
    (chosenAction === "assign_campaign" && !chosenCampaign)
  const nothingSelected = !useView && scope.ids.length === 0

  const previewM = useMutation({
    mutationFn: () =>
      bulkPreview({
        subject,
        action: chosenAction as BulkAction,
        params,
        selection:
          useView && scope.view
            ? { view: scope.view.selection }
            : { ids: scope.ids },
      }),
    onSuccess: (p) => {
      setPreview(p)
      setPhase("preview")
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "The preview failed."),
  })

  const runM = useMutation({
    mutationFn: (v: { id: string; count: number }) => bulkRun(v.id, v.count),
    onSuccess: (_r, v) => {
      setOpId(v.id)
      setPhase("run")
      void qc.invalidateQueries({ queryKey: bulkKeys.operation(v.id) })
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "It did not start."),
  })

  useBulkEvents(opId)
  const op = useQuery({
    queryKey: bulkKeys.operation(opId ?? "none"),
    queryFn: () => getOperation(opId as string),
    enabled: !!opId,
    refetchInterval: (q) =>
      q.state.data && !isRunning(q.state.data.status) ? false : POLL_MS,
  })
  const finished = !!op.data && !isRunning(op.data.status)
  const items = useQuery({
    queryKey: bulkKeys.items(opId ?? "none", `${op.data?.status}`),
    queryFn: () => listItems(opId as string),
    enabled: !!opId && finished,
  })

  useEffect(() => {
    if (finished) refreshAfterBulk(qc)
  }, [finished, qc])

  const undoM = useMutation({
    mutationFn: () => undoOperation(opId as string),
    onSuccess: (o) => {
      qc.setQueryData(bulkKeys.operation(o.id), o)
      void qc.invalidateQueries({ queryKey: ["bulk", "items", o.id] })
      refreshAfterBulk(qc)
      toast.success("Undone.")
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "That could not be undone."),
  })

  const close = (o: boolean) => {
    if (!o && phase === "run") onDone?.()
    onOpenChange(o)
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[88vh] gap-4 overflow-y-auto pop-surface p-5 sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            {phase === "run" && op.data
              ? `${ACTION_LABEL[op.data.action]}: ${statusWords(op.data)}`
              : chosenAction
                ? ACTION_LABEL[chosenAction]
                : "Bulk action"}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {phase === "setup"
              ? "Pick what to do. You see what would change before anything does."
              : phase === "preview"
                ? "Nothing has changed yet. Check the counts, then run it."
                : "Each item goes through the same checks as doing it by hand."}
          </DialogDescription>
        </DialogHeader>

        {phase === "setup" && (
          <div className="grid gap-3">
            {scope.view && (
              <fieldset className="grid gap-1.5">
                <legend className="eyebrow">Apply to</legend>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name={`${uid}-scope`}
                    checked={!useView}
                    onChange={() => setUseView(false)}
                  />
                  {plural(scope.ids.length, "selected item")}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name={`${uid}-scope`}
                    checked={useView}
                    onChange={() => setUseView(true)}
                  />
                  Everything matching this view
                  {viewCount !== null ? ` (${viewCount})` : ""}
                </label>
                {useView && (
                  <p className="text-sm text-muted-foreground">
                    The server works out the exact list when you preview, and
                    shows the count to confirm.
                  </p>
                )}
              </fieldset>
            )}
            <Field id={`${uid}-a`} label="Action">
              <select
                id={`${uid}-a`}
                className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
                value={chosenAction}
                onChange={(e) => setAction(e.target.value as BulkAction)}
              >
                {actions.map((a) => (
                  <option key={a} value={a}>
                    {ACTION_LABEL[a]}
                  </option>
                ))}
              </select>
            </Field>
            {(chosenAction === "tag" || chosenAction === "untag") && (
              <Field id={`${uid}-tag`} label="Tag">
                <Input
                  id={`${uid}-tag`}
                  value={tag}
                  onChange={(e) => setTag(e.target.value)}
                />
              </Field>
            )}
            {chosenAction === "skip" && (
              <Field id={`${uid}-r`} label="Reason (required)">
                <Textarea
                  id={`${uid}-r`}
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </Field>
            )}
            {chosenAction === "snooze" && (
              <Field id={`${uid}-u`} label="Snooze until">
                <Input
                  id={`${uid}-u`}
                  type="date"
                  className="w-44"
                  value={until}
                  onChange={(e) => setUntil(e.target.value)}
                />
              </Field>
            )}
            {chosenAction === "move_stage" && (
              <Field id={`${uid}-s`} label="Move to stage">
                <select
                  id={`${uid}-s`}
                  className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
                  value={chosenStage}
                  onChange={(e) => setStage(e.target.value)}
                >
                  {MOVE_TARGETS.map((s) => (
                    <option key={s} value={s}>
                      {STAGE_META[s]?.label ?? s}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            {chosenAction === "assign_campaign" && (
              <Field id={`${uid}-c`} label="Campaign">
                <select
                  id={`${uid}-c`}
                  className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
                  value={chosenCampaign}
                  onChange={(e) => setCampaignId(e.target.value)}
                >
                  {(campaigns.data?.items ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            {chosenAction === "send_for_approval" && (
              <p className="text-sm text-muted-foreground">
                This builds each packet and lets your approval policy act. It
                never approves or sends anything for you; each packet is
                approved on its own.
              </p>
            )}
          </div>
        )}

        {phase === "preview" && preview && (
          <PreviewView
            preview={preview}
            undoMinutes={options.data?.undo_window_minutes}
          />
        )}

        {phase === "run" && (
          <RunView
            op={op.data}
            items={items.data?.items ?? []}
            onUndo={() => undoM.mutate()}
            undoing={undoM.isPending}
          />
        )}

        <DialogFooter className="gap-2">
          {phase === "setup" && (
            <>
              <Button variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button
                disabled={
                  !chosenAction ||
                  !!missing ||
                  nothingSelected ||
                  previewM.isPending
                }
                onClick={() => previewM.mutate()}
              >
                Preview
              </Button>
            </>
          )}
          {phase === "preview" && preview && (
            <>
              <Button variant="ghost" onClick={() => setPhase("setup")}>
                Back
              </Button>
              <Button
                disabled={runM.isPending || preview.will_change === 0}
                onClick={() =>
                  runM.mutate({
                    id: preview.operation_id,
                    count: preview.selected,
                  })
                }
              >
                {chosenAction === "export_csv"
                  ? `Export ${plural(preview.will_change, "row")}`
                  : `Run on ${plural(preview.will_change, "item")}`}
              </Button>
            </>
          )}
          {phase === "run" && (
            <>
              {op.data?.action === "export_csv" && finished && opId && (
                <Button asChild variant="outline">
                  <a href={csvUrl(opId)} download>
                    <Download aria-hidden="true" />
                    Download CSV
                  </a>
                </Button>
              )}
              {op.data &&
                (op.data.status === "partial" ||
                  op.data.status === "failed") && (
                  <Button
                    variant="outline"
                    disabled={runM.isPending}
                    onClick={() =>
                      runM.mutate({
                        id: op.data.id,
                        count: op.data.selected,
                      })
                    }
                  >
                    Retry failed items
                  </Button>
                )}
              <Button onClick={() => close(false)}>
                {finished ? "Close" : "Hide"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  id,
  label,
  children,
}: {
  id: string
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="eyebrow">
        {label}
      </label>
      {children}
    </div>
  )
}

const statusWords = (o: OperationOut) =>
  ({
    previewed: "ready",
    queued: "waiting to start",
    running: "running",
    done: "done",
    partial: "done with some failures",
    failed: "failed",
    undone: "undone",
  })[o.status]

/** "42 selected: 37 will change, 5 can't because ..." grouped by reason. */
export function PreviewView({
  preview,
  undoMinutes,
}: {
  preview: PreviewOut
  undoMinutes?: number
}) {
  return (
    <div className="grid gap-3" aria-live="polite">
      <p className="text-sm font-semibold" data-testid="preview-summary">
        {preview.selected} selected: {preview.will_change} will change
        {preview.unchanged
          ? `, ${preview.unchanged.count} already as asked`
          : ""}
        {preview.refused_total ? `, ${preview.refused_total} can't` : ""}.
      </p>
      {preview.refused.length > 0 && (
        <ul className="grid gap-2" aria-label="Why some can't">
          {preview.refused.map((g) => (
            <ReasonBlock key={g.code} group={g} />
          ))}
        </ul>
      )}
      <p className="text-sm text-muted-foreground">
        {preview.reversible
          ? `You can undo this${undoMinutes ? ` for ${undoMinutes} minutes` : ""} after it runs.`
          : "This one cannot be undone."}
      </p>
    </div>
  )
}

function ReasonBlock({ group }: { group: ReasonGroup }) {
  const more = group.count - group.samples.length
  return (
    <li data-reason={group.code} className="rounded-sm bg-sunken p-3 text-sm">
      <div className="font-semibold">
        {group.count} can't: {group.title}
      </div>
      <ul className="mt-1 grid gap-0.5 text-muted-foreground">
        {group.samples.map((s) => (
          <li key={s.id}>
            {s.label}: {s.reason}
          </li>
        ))}
        {more > 0 && <li>and {more} more</li>}
      </ul>
    </li>
  )
}

function RunView({
  op,
  items,
  onUndo,
  undoing,
}: {
  op: OperationOut | undefined
  items: ItemOut[]
  onUndo: () => void
  undoing: boolean
}) {
  if (!op) return <p className="text-sm text-faint">Starting…</p>
  const running = isRunning(op.status)
  const failed = items.filter((i) => i.outcome === "failed")
  const refused = items.filter((i) => i.outcome === "refused")
  const skipped = items.filter((i) => i.outcome === "undo_skipped")
  return (
    <div className="grid gap-3" aria-live="polite">
      <div className="grid gap-1">
        <progress
          aria-label="Progress"
          className="h-2 w-full accent-primary"
          max={Math.max(op.selected, 1)}
          value={op.done}
        />
        <p className="num text-sm text-muted-foreground">
          {op.done} of {op.selected} done
          {running ? "" : ` · ${statusWords(op)}`}
        </p>
      </div>
      {!running && (
        <ul
          className="flex flex-wrap gap-x-4 gap-y-1 text-sm"
          aria-label="Results"
        >
          {Object.entries(op.counts)
            .filter(([k, n]) => n > 0 && k !== "pending")
            .map(([k, n]) => (
              <li key={k} data-outcome={k}>
                <span className="num font-semibold">{n}</span>{" "}
                {k.replace("_", " ")}
              </li>
            ))}
        </ul>
      )}
      {op.error && <p className="text-sm text-danger">{op.error}</p>}
      {failed.length > 0 && (
        <ItemList title="Failed" items={failed} tone="danger" />
      )}
      {refused.length > 0 && (
        <ItemList title="Refused" items={refused} tone="warn" />
      )}
      {skipped.length > 0 && (
        <ItemList
          title="Left alone (changed since)"
          items={skipped}
          tone="warn"
        />
      )}
      {op.can_undo && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={undoing}
            onClick={onUndo}
          >
            <Undo2 aria-hidden="true" />
            Undo
          </Button>
          {op.undo_until && (
            <span className="text-sm text-muted-foreground">
              until{" "}
              {new Date(op.undo_until).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function ItemList({
  title,
  items,
  tone,
}: {
  title: string
  items: ItemOut[]
  tone: "danger" | "warn"
}) {
  return (
    <div className="rounded-sm bg-sunken p-3 text-sm">
      <div
        className={
          tone === "danger"
            ? "font-semibold text-danger"
            : "font-semibold text-warn"
        }
      >
        {title} ({items.length})
      </div>
      <ul className="mt-1 grid max-h-40 gap-0.5 overflow-y-auto">
        {items.map((i) => (
          <li key={i.id}>
            {i.label}:{" "}
            <span className="text-muted-foreground">{i.reason ?? i.code}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
