import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { Archive, Copy, Pause, Play, Plus, Target } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Chip } from "@/components/chip"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { campaignsQuery, tracksQuery, useCampaignMutations } from "./api"
import { MODES } from "./automation"
import { toneForStatus } from "./bits"
import type { Campaign } from "./types"

const plainDate = (iso: string | null | undefined) =>
  iso
    ? new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(new Date(iso))
    : null

const count = (n: number | undefined, word: string) =>
  `${n ?? 0} ${word}${n === 1 ? "" : "s"}`

export function statusWords(c: Campaign): string {
  if (c.status === "paused" && c.paused_until)
    return `Paused until ${plainDate(c.paused_until)}`
  return c.status[0].toUpperCase() + c.status.slice(1)
}

/** Campaigns: one search run on a schedule, with its own rules and budget (DESIGN 10.3). */
export function CampaignsPage() {
  const q = useQuery(campaignsQuery())
  const tracks = useQuery(tracksQuery()).data ?? []
  const m = useCampaignMutations()
  const navigate = useNavigate()
  const [showArchived, setShowArchived] = useState(false)
  const [pausing, setPausing] = useState<Campaign | null>(null)
  const [until, setUntil] = useState("")

  const all = q.data ?? []
  const rows = all.filter((c) => showArchived || c.status !== "archived")
  const trackName = (id: string | null | undefined) =>
    tracks.find((t) => t.id === id)?.name ?? "No track"

  const run = async (p: Promise<unknown>, ok: string) => {
    try {
      await p
      toast.success(ok)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "That did not work.")
    }
  }

  const create = async () => {
    try {
      const c = await m.create.mutateAsync({
        name: "Untitled campaign",
        criteria: {},
      })
      void navigate({ to: "/campaigns/$id", params: { id: c.id } })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not create it.")
    }
  }

  const columns: Column<Campaign>[] = [
    {
      id: "name",
      header: "Campaign",
      sortValue: (c) => c.name,
      cell: (c) => (
        <div>
          <Link
            to="/campaigns/$id"
            params={{ id: c.id }}
            className="font-medium text-foreground hover:underline"
          >
            {c.name}
          </Link>
          <div className="text-sm text-muted-foreground">
            {trackName(c.track_id)}
          </div>
        </div>
      ),
    },
    {
      id: "status",
      header: "Status",
      sortValue: (c) => c.status,
      cell: (c) => (
        <div className="flex flex-wrap gap-1">
          <Chip tone={toneForStatus[c.status]}>{statusWords(c)}</Chip>
          {c.review_state === "needs_review" && (
            <Chip tone="warn">Needs your confirmation</Chip>
          )}
        </div>
      ),
    },
    {
      id: "mode",
      header: "Mode",
      hideBelow: "md",
      cell: (c) =>
        MODES.find((x) => x.value === (c.automation?.mode ?? "prepare"))?.label,
    },
    {
      id: "last",
      header: "Last run",
      hideBelow: "md",
      sortValue: (c) => c.last_sweep_checkpoint ?? "",
      cell: (c) =>
        plainDate(c.last_sweep_checkpoint) ?? (
          <span className="text-faint">Not run yet</span>
        ),
    },
    {
      id: "counts",
      header: "Set up",
      hideBelow: "lg",
      cell: (c) => (
        <span className="text-sm text-muted-foreground">
          {count(c.criteria?.titles?.length, "title")},{" "}
          {count(c.criteria?.rules?.length, "rule")},{" "}
          {count(c.source_ids?.length, "source")}
        </span>
      ),
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (c) => (
        <div className="flex justify-end gap-0.5">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Copy ${c.name}`}
            title="Make a copy"
            onClick={() =>
              void run(m.clone.mutateAsync(c.id), `Copied ${c.name}.`)
            }
          >
            <Copy aria-hidden="true" />
          </Button>
          {c.status === "paused" || c.status === "draft" ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`${c.status === "draft" ? "Start" : "Resume"} ${c.name}`}
              title={c.status === "draft" ? "Start" : "Resume"}
              disabled={c.review_state === "needs_review"}
              onClick={() =>
                void run(
                  m.setStatus.mutateAsync({ id: c.id, status: "active" }),
                  `${c.name} is running.`
                )
              }
            >
              <Play aria-hidden="true" />
            </Button>
          ) : c.status === "active" ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`Pause ${c.name}`}
              title="Pause until a date"
              onClick={() => {
                setPausing(c)
                setUntil("")
              }}
            >
              <Pause aria-hidden="true" />
            </Button>
          ) : null}
          {c.status !== "archived" && (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`Archive ${c.name}`}
              title="Archive"
              onClick={() =>
                void run(
                  m.setStatus.mutateAsync({ id: c.id, status: "archived" }),
                  `${c.name} archived.`
                )
              }
            >
              <Archive aria-hidden="true" />
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <View>
      <PageHeader
        title="Campaigns"
        description="Each campaign is one search: what to look for, how to score it and how far to go on your behalf."
        actions={
          <Button
            type="button"
            onClick={() => void create()}
            disabled={m.create.isPending}
          >
            <Plus aria-hidden="true" /> New campaign
          </Button>
        }
      />
      <label className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={showArchived}
          onChange={(e) => setShowArchived(e.target.checked)}
        />
        Show archived
      </label>
      {q.isLoading ? (
        <p className="text-muted-foreground">Loading campaigns...</p>
      ) : q.isError ? (
        <p role="alert">
          We could not load your campaigns. Try again in a moment.
        </p>
      ) : (
        <DataTable
          caption="Campaigns"
          columns={columns}
          rows={rows}
          getRowId={(c) => c.id}
          minWidth={560}
          empty={
            <EmptyState
              icon={Target}
              title="No campaigns yet"
              description="A campaign is one search you run on a schedule. Create one to start."
            />
          }
        />
      )}

      <Dialog
        open={pausing !== null}
        onOpenChange={(o) => !o && setPausing(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Pause {pausing?.name}</DialogTitle>
            <DialogDescription>
              It stops looking for roles and picks up again on the day you
              choose. Leave the date empty to pause until you resume it.
            </DialogDescription>
          </DialogHeader>
          <label className="grid gap-1 text-sm">
            <span className="font-medium">Resume on</span>
            <Input
              type="date"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPausing(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (!pausing) return
                const c = pausing
                setPausing(null)
                void run(
                  m.setStatus.mutateAsync({
                    id: c.id,
                    status: "paused",
                    paused_until: until || null,
                  }),
                  `${c.name} paused.`
                )
              }}
            >
              Pause
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </View>
  )
}
