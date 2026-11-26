import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Archive, RefreshCw, Tag, X } from "lucide-react"
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
import { Input } from "@/components/ui/input"
import { bulkAction, campaignsQuery, invalidateJobs, rescore } from "./api"
import { plural } from "./format"
import type { BulkAction } from "./types"

export type BulkKind = "skip" | "archive" | "tag" | "untag" | "rescore"

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
      <Button variant="outline" size="xs" onClick={() => onAction("rescore")}>
        <RefreshCw data-icon="inline-start" aria-hidden="true" />
        Rescore
      </Button>
      <Button variant="ghost" size="xs" className="ml-auto" onClick={onClear}>
        Clear
      </Button>
    </div>
  )
}

const TITLES: Record<BulkKind, string> = {
  skip: "Skip these roles?",
  archive: "Archive these roles?",
  tag: "Tag these roles",
  untag: "Remove a tag from these roles",
  rescore: "Rescore these roles",
}

/** Preview, then confirm, a bulk action over the selection. */
export function BulkDialog({
  kind,
  ids,
  onOpenChange,
  onDone,
}: {
  kind: BulkKind | null
  ids: string[]
  onOpenChange: (open: boolean) => void
  onDone: () => void
}) {
  const qc = useQueryClient()
  const id = useId()
  const [tag, setTag] = useState("")
  const [committedTag, setCommittedTag] = useState("")
  const [campaignId, setCampaignId] = useState("")
  const open = kind !== null
  const isTag = kind === "tag" || kind === "untag"
  const action = (kind === "rescore" ? null : kind) as BulkAction | null
  const ready = !!action && (!isTag || !!committedTag)

  const preview = useQuery({
    queryKey: ["matches", "bulk-preview", action, committedTag, ids],
    queryFn: () =>
      bulkAction({
        job_ids: ids,
        action: action as BulkAction,
        tag: isTag ? committedTag : null,
        preview: true,
      }),
    enabled: open && ready,
    gcTime: 0,
  })
  const campaigns = useQuery({
    ...campaignsQuery(),
    enabled: kind === "rescore",
  })
  const chosenCampaign = campaignId || campaigns.data?.items[0]?.id || ""

  const run = useMutation({
    mutationFn: async () => {
      if (kind === "rescore") return rescore(ids, chosenCampaign)
      return bulkAction({
        job_ids: ids,
        action: action as BulkAction,
        tag: isTag ? committedTag : null,
        preview: false,
      })
    },
    onSuccess: (res) => {
      if (kind === "rescore")
        toast.success(
          `Rescoring ${plural(ids.length, "role")}. New scores land in the list when done.`
        )
      else if (res && "affected" in res)
        toast.success(`Done: ${plural(res.affected, "role")} changed.`)
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
            {kind ? TITLES[kind] : ""}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {plural(ids.length, "role")} selected. Nothing changes until you
            confirm.
          </DialogDescription>
        </DialogHeader>

        {isTag && (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              setCommittedTag(tag.trim().toLowerCase())
            }}
          >
            <div className="grid flex-1 gap-1.5">
              <label htmlFor={id} className="eyebrow">
                Tag
              </label>
              <Input
                id={id}
                autoFocus
                value={tag}
                onChange={(e) => setTag(e.target.value)}
              />
            </div>
            <Button type="submit" variant="outline" disabled={!tag.trim()}>
              Preview
            </Button>
          </form>
        )}

        {kind === "rescore" && (
          <div className="grid gap-1.5">
            <label htmlFor={`${id}-c`} className="eyebrow">
              Score against campaign
            </label>
            <select
              id={`${id}-c`}
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
            <p className="text-sm text-muted-foreground">
              Each role is scored again with the campaign's current rubric.
              Scoring uses the model budget.
            </p>
          </div>
        )}

        {ready && (
          <div className="grid gap-2" aria-live="polite">
            {preview.isLoading ? (
              <p className="text-sm text-faint">
                Working out what would change…
              </p>
            ) : preview.data ? (
              <>
                <p className="text-sm font-semibold">
                  {plural(preview.data.affected, "role")} would change.
                </p>
                <ul className="max-h-56 overflow-y-auto rounded-sm bg-sunken p-3 text-sm">
                  {preview.data.detail.map((d) => (
                    <li key={d} className="py-0.5">
                      {d}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-sm text-danger">The preview did not load.</p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={
              run.isPending ||
              (kind === "rescore"
                ? !chosenCampaign
                : !preview.data || preview.data.affected === 0)
            }
            onClick={() => run.mutate()}
          >
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
