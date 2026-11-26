import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Archive,
  Columns3,
  MoreHorizontal,
  RefreshCw,
  Tag,
  X,
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
import { campaignsQuery, invalidateJobs, rescore } from "./api"
import { plural } from "./format"

/** What the bar opens: a preset action in the shared bulk dialog, "more" for its picker, or rescoring. */
export type BulkKind = "skip" | "archive" | "tag" | "untag" | "more" | "rescore"

type BulkBarProps = {
  ids: string[]
  onClear: () => void
  onAction: (kind: BulkKind) => void
}

/** Shown while jobs are selected. Every action previews before it changes anything. */
export function BulkBar({ ids, onClear, onAction }: BulkBarProps) {
  return (
    <div
      role="toolbar"
      aria-label="Selected jobs"
      className="flex flex-wrap items-center gap-1.5 border-b border-border bg-highlight-soft py-2 pr-3 pl-5.5 text-sm"
    >
      <span
        className="mr-1 font-semibold text-highlight-ink"
        aria-live="polite"
      >
        {ids.length} selected
      </span>
      <Button variant="outline" size="xs" onClick={() => onAction("skip")}>
        <X data-icon="inline-start" aria-hidden="true" />
        Skip
      </Button>
      <Button variant="outline" size="xs" onClick={() => onAction("archive")}>
        <Archive data-icon="inline-start" aria-hidden="true" />
        Archive
      </Button>
      <Button variant="outline" size="xs" onClick={() => onAction("tag")}>
        <Tag data-icon="inline-start" aria-hidden="true" />
        Tag
      </Button>
      <Button variant="outline" size="xs" onClick={() => onAction("untag")}>
        Remove tag
      </Button>
      <Button variant="outline" size="xs" onClick={() => onAction("more")}>
        <MoreHorizontal data-icon="inline-start" aria-hidden="true" />
        More actions
      </Button>
      <Button variant="outline" size="xs" onClick={() => onAction("rescore")}>
        <RefreshCw data-icon="inline-start" aria-hidden="true" />
        Rescore
      </Button>
      {ids.length >= 2 && ids.length <= 4 ? (
        <Button asChild variant="outline" size="xs">
          <Link to="/compare" search={{ ids: ids.join(",") }}>
            <Columns3 data-icon="inline-start" aria-hidden="true" />
            Compare
          </Link>
        </Button>
      ) : (
        <Button
          variant="outline"
          size="xs"
          disabled
          title="Select 2 to 4 roles to compare"
        >
          <Columns3 data-icon="inline-start" aria-hidden="true" />
          Compare
        </Button>
      )}
      <Button variant="ghost" size="xs" className="ml-auto" onClick={onClear}>
        Clear
      </Button>
    </div>
  )
}

/** Rescore the selected roles against a campaign (a scoring job, not a bulk operation). */
export function RescoreDialog({
  open,
  ids,
  onOpenChange,
  onDone,
}: {
  open: boolean
  ids: string[]
  onOpenChange: (open: boolean) => void
  onDone: () => void
}) {
  const qc = useQueryClient()
  const id = useId()
  const [campaignId, setCampaignId] = useState("")
  const campaigns = useQuery({ ...campaignsQuery(), enabled: open })
  const chosen = campaignId || campaigns.data?.items[0]?.id || ""
  const run = useMutation({
    mutationFn: () => rescore(ids, chosen),
    onSuccess: () => {
      toast.success(
        `Rescoring ${plural(ids.length, "role")}. New scores land in the list when done.`
      )
      invalidateJobs(qc)
      onDone()
      onOpenChange(false)
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "That did not work."),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            Rescore these roles
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {plural(ids.length, "role")} selected. Nothing changes until you
            confirm.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-1.5">
          <label htmlFor={`${id}-c`} className="eyebrow">
            Score against campaign
          </label>
          <select
            id={`${id}-c`}
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
            value={chosen}
            onChange={(e) => setCampaignId(e.target.value)}
          >
            {(campaigns.data?.items ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <p className="text-sm text-muted-foreground">
            Each role is scored again with the campaign's current rubric.
            Scoring uses the model budget.
          </p>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={run.isPending || !chosen}
            onClick={() => run.mutate()}
          >
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
