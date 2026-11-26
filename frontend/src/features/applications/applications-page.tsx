import { useMemo, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { Columns3, Pin, Search, Table2, X } from "lucide-react"
import { toast } from "sonner"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { KanbanBoard } from "@/components/kanban-board"
import { ScoreRing } from "@/components/score-ring"
import { Segmented } from "@/components/segmented"
import { StagePill, type Stage } from "@/components/stage-pill"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { View } from "@/components/view"
import { BulkDialog } from "@/features/bulk/bulk-dialog"
import type { BulkAction } from "@/features/bulk/api"
import { useEmployerChips } from "@/features/employers/api"
import { EmployerChip } from "@/features/employers/employer-chip"
import { DrillBar } from "@/features/insights/drill"
import {
  pickDrill,
  withoutDrill,
  type AppDrill,
} from "@/features/insights/drill-search"
import { meQuery } from "@/lib/api/endpoints"
import {
  appKeys,
  applicationsKey,
  applicationsQuery,
  campaignsQuery,
  changeStage,
  type ApplicationSummary,
  type Channel,
} from "./api"
import {
  ApplicationCard,
  ChannelIcon,
  CHANNEL_META,
  NextStep,
} from "./application-card"
import { AppliedMyselfDialog } from "./applied-myself-dialog"
import { daysSince } from "./format"
import { QuickLookDrawer } from "./quick-look-drawer"
import { PinButton, SnoozeButton } from "./row-actions"
import { BOARD_COLUMNS, checkMove, columnOf, columnTitle } from "./stages"
import { useLayoutPreference } from "./use-layout-preference"

export { BOARD_COLUMNS }

const ALL = "all"

/**
 * Applications: board and table of every role you are pursuing (DESIGN 10.3). `drill` comes from
 * an Insights link: the list is then exactly the applications that number counted.
 */
export function ApplicationsPage({
  drill,
  onDrill,
}: {
  drill?: AppDrill
  onDrill?: (next: AppDrill | undefined) => void
} = {}) {
  const qc = useQueryClient()
  const me = useQuery(meQuery())
  const timeZone = me.data?.timezone
  const listKey = applicationsKey(drill)
  const apps = useQuery(applicationsQuery(drill))
  const campaigns = useQuery(campaignsQuery())
  const [layout, setLayout] = useLayoutPreference()

  const [text, setText] = useState("")
  const [channel, setChannel] = useState<string>(ALL)
  const [campaign, setCampaign] = useState<string>(ALL)
  const [refusal, setRefusal] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [appliedId, setAppliedId] = useState<string | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [bulkOpen, setBulkOpen] = useState<BulkAction | "more" | null>(null)
  const toggleChecked = (id: string) =>
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const all = useMemo(() => apps.data?.items ?? [], [apps.data])
  const rows = useMemo(() => {
    const q = text.trim().toLowerCase()
    return all.filter(
      (a) =>
        (channel === ALL || a.channel === channel) &&
        (campaign === ALL || a.campaign_id === campaign) &&
        (!q ||
          `${a.employer} ${a.title} ${a.next_step ?? ""}`
            .toLowerCase()
            .includes(q))
    )
  }, [all, text, channel, campaign])

  const chips = useEmployerChips(rows.map((a) => a.job_id))

  const campaignOptions = useMemo(() => {
    const names = new Map(
      (campaigns.data?.items ?? []).map((c) => [c.id, c.name])
    )
    const ids = new Set(
      all.map((a) => a.campaign_id).filter((x): x is string => !!x)
    )
    return [...ids].map((id, i) => ({
      id,
      name: names.get(id) ?? `Campaign ${i + 1}`,
    }))
  }, [all, campaigns.data])

  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: Stage }) =>
      changeStage(id, stage),
    onMutate: async ({ id, stage }) => {
      await qc.cancelQueries({ queryKey: listKey })
      const before = qc.getQueryData(listKey)
      patchList(qc, listKey, id, { stage })
      return { before }
    },
    onError: (e, _v, ctx) => {
      if (ctx?.before) qc.setQueryData(listKey, ctx.before)
      setRefusal(e.message)
      toast.error(e.message)
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: appKeys.list }),
  })

  const onMove = (id: string, toColumn: string) => {
    const app = all.find((a) => a.id === id)
    if (!app) return
    const result = checkMove(app.stage, toColumn)
    if (result.kind === "refused") {
      setRefusal(
        `${app.employer} can't move to ${columnTitle(toColumn)}. ${result.reason}`
      )
      return
    }
    setRefusal(null)
    if (result.kind === "applied-myself") {
      setAppliedId(id)
      return
    }
    move.mutate({ id, stage: result.stage })
  }

  const needStep = all.filter(
    (a) => a.open_pending_actions > 0 || (a.next_due && !isDone(a.stage))
  ).length
  const active = all.filter((a) => !isDone(a.stage)).length
  const openApp = all.find((a) => a.id === openId) ?? null
  const appliedApp = all.find((a) => a.id === appliedId) ?? null

  const allRowsChecked = rows.length > 0 && rows.every((r) => checked.has(r.id))
  const columns: Column<ApplicationSummary>[] = [
    {
      id: "select",
      header: (
        <input
          type="checkbox"
          aria-label="Select all shown"
          checked={allRowsChecked}
          onChange={() =>
            setChecked(
              allRowsChecked ? new Set() : new Set(rows.map((r) => r.id))
            )
          }
          className="size-4 cursor-pointer accent-primary"
        />
      ),
      cell: (r) => (
        <input
          type="checkbox"
          aria-label={`Select ${r.employer}, ${r.title}`}
          checked={checked.has(r.id)}
          onChange={() => toggleChecked(r.id)}
          onClick={(e) => e.stopPropagation()}
          className="size-4 cursor-pointer accent-primary"
        />
      ),
    },
    {
      id: "employer",
      header: "Company",
      sortValue: (r) => r.employer,
      cell: (r) => (
        <span className="inline-flex flex-wrap items-center gap-1 font-semibold">
          {r.employer}
          <EmployerChip chip={chips[r.job_id]} onApplication />
          {r.pinned && (
            <Pin
              className="size-3 text-primary-ink"
              strokeWidth={1.5}
              aria-label="Pinned"
            />
          )}
        </span>
      ),
    },
    {
      id: "role",
      header: "Role",
      sortValue: (r) => r.title,
      cell: (r) => r.title,
    },
    {
      id: "stage",
      header: "Stage",
      sortValue: (r) => columnOf(r.stage),
      cell: (r) => <StagePill stage={r.stage} />,
    },
    {
      id: "score",
      header: "Score",
      sortValue: (r) => r.score ?? -1,
      hideBelow: "sm",
      cell: (r) =>
        r.score === null ? "" : <ScoreRing score={r.score} size={28} />,
    },
    {
      id: "channel",
      header: "Channel",
      hideBelow: "md",
      cell: (r) =>
        r.channel ? (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <ChannelIcon channel={r.channel} />
            {CHANNEL_META[r.channel].label}
          </span>
        ) : null,
    },
    {
      id: "days",
      header: "In stage",
      sortValue: (r) => daysSince(r.updated_at),
      hideBelow: "md",
      cell: (r) => <span className="num">{daysSince(r.updated_at)}d</span>,
    },
    {
      id: "next",
      header: "Next step",
      hideBelow: "lg",
      cell: (r) => <NextStep app={r} timeZone={timeZone} />,
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      hideBelow: "sm",
      cell: (r) => (
        <span className="inline-flex gap-1.5">
          <PinButton app={r} />
          <SnoozeButton app={r} timeZone={timeZone} />
        </span>
      ),
    },
  ]

  return (
    <View>
      <div className="mb-3 flex flex-wrap items-center gap-2.5 pr-1">
        <Segmented
          aria-label="Layout"
          value={layout}
          onValueChange={setLayout}
          options={[
            { value: "board", label: "Board", icon: Columns3 },
            { value: "table", label: "Table", icon: Table2 },
          ]}
        />
        <span className="text-[0.9rem] text-muted-foreground">
          <span className="num">{active}</span> active ·{" "}
          {needStep === 0 ? (
            "nothing needs a step"
          ) : (
            <>
              <span className="num">{needStep}</span> with a next step
            </>
          )}
        </span>
        <span className="ml-auto text-[0.84rem] text-faint max-md:hidden">
          Drag cards between stages, or focus a card and use the arrow keys
        </span>
      </div>

      <DrillBar
        drill={drill}
        onRemove={(k) => onDrill?.(pickDrill(withoutDrill(drill ?? {}, k)))}
        onClear={() => onDrill?.(undefined)}
      />
      <div
        role="search"
        aria-label="Filter applications"
        className="mb-4 flex flex-wrap items-center gap-2"
      >
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <Input
            aria-label="Search applications"
            placeholder="Search employer or role"
            className="pl-8"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <Select value={channel} onValueChange={setChannel}>
          <SelectTrigger aria-label="Channel" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All channels</SelectItem>
            {(Object.keys(CHANNEL_META) as Channel[]).map((c) => (
              <SelectItem key={c} value={c}>
                {CHANNEL_META[c].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {campaignOptions.length > 0 && (
          <Select value={campaign} onValueChange={setCampaign}>
            <SelectTrigger aria-label="Campaign" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All campaigns</SelectItem>
              {campaignOptions.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {(text || channel !== ALL || campaign !== ALL) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setText("")
              setChannel(ALL)
              setCampaign(ALL)
            }}
          >
            <X aria-hidden="true" />
            Clear filters
          </Button>
        )}
      </div>

      {checked.size > 0 && (
        <div
          role="toolbar"
          aria-label="Selected applications"
          className="mb-3 flex flex-wrap items-center gap-1.5 rounded-sm bg-highlight-soft px-3 py-2 text-sm"
        >
          <span
            className="mr-1 font-semibold text-highlight-ink"
            aria-live="polite"
          >
            {checked.size} selected
          </span>
          <Button
            variant="outline"
            size="xs"
            onClick={() => setBulkOpen("move_stage")}
          >
            Move stage
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={() => setBulkOpen("send_for_approval")}
          >
            Send for approval
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={() => setBulkOpen("snooze")}
          >
            Snooze
          </Button>
          <Button
            variant="outline"
            size="xs"
            onClick={() => setBulkOpen("more")}
          >
            More actions
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="ml-auto"
            onClick={() => setChecked(new Set())}
          >
            Clear
          </Button>
        </div>
      )}
      {refusal && (
        <Alert variant="destructive" className="mb-3" role="alert">
          <AlertTitle>Move refused</AlertTitle>
          <AlertDescription>{refusal}</AlertDescription>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Dismiss"
            className="absolute top-2 right-2"
            onClick={() => setRefusal(null)}
          >
            <X aria-hidden="true" />
          </Button>
        </Alert>
      )}

      {apps.isError ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Couldn't load applications</AlertTitle>
          <AlertDescription>
            {apps.error.message}{" "}
            <Button
              variant="link"
              size="xs"
              onClick={() => void apps.refetch()}
            >
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : layout === "board" ? (
        <KanbanBoard<ApplicationSummary>
          columns={BOARD_COLUMNS}
          items={rows}
          getId={(r) => r.id}
          getColumn={(r) => columnOf(r.stage)}
          getLabel={(r) => `${r.employer}, ${r.title}`}
          renderCard={(r) => (
            <ApplicationCard
              app={r}
              timeZone={timeZone}
              chip={chips[r.job_id]}
              checked={checked.has(r.id)}
              onToggle={() => toggleChecked(r.id)}
            />
          )}
          onMove={onMove}
          onOpen={setOpenId}
          emptyColumn={(c) => (
            <p className="rounded-sm border border-dashed border-border-strong px-3 py-4 text-center text-sm text-faint">
              {c.id === "shortlisted"
                ? "Shortlist a role from Matches and it starts here."
                : "No roles at this stage."}
            </p>
          )}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          getRowId={(r) => r.id}
          caption="Applications"
          onRowClick={(r) => setOpenId(r.id)}
          empty={
            <EmptyState
              title={
                apps.isPending ? "Loading applications" : "No applications"
              }
              description={
                all.length > 0
                  ? "Nothing matches these filters."
                  : "Every role you shortlist, tailor or apply to is listed here with its stage and next step."
              }
            />
          }
        />
      )}

      <BulkDialog
        key={bulkOpen ?? "closed"}
        open={bulkOpen !== null}
        subject="applications"
        scope={{
          ids: [...checked],
          view: {
            count: rows.length,
            selection: {
              q: text.trim() || undefined,
              channel: channel === ALL ? undefined : channel,
              campaign_id: campaign === ALL ? undefined : campaign,
            },
          },
        }}
        initialAction={bulkOpen && bulkOpen !== "more" ? bulkOpen : undefined}
        onOpenChange={(o) => !o && setBulkOpen(null)}
        onDone={() => setChecked(new Set())}
      />
      <QuickLookDrawer
        app={openApp}
        timeZone={timeZone}
        onClose={() => setOpenId(null)}
      />
      <AppliedMyselfDialog
        app={appliedApp}
        timeZone={timeZone}
        onClose={() => setAppliedId(null)}
      />
    </View>
  )
}

const isDone = (s: Stage) =>
  ["rejected", "withdrawn", "closed", "skipped", "accepted"].includes(s)

function patchList(
  qc: QueryClient,
  key: ReturnType<typeof applicationsKey>,
  id: string,
  patch: Partial<ApplicationSummary>
) {
  qc.setQueryData<{ items: ApplicationSummary[] } | undefined>(
    key,
    (old) =>
      old && {
        ...old,
        items: old.items.map((a) =>
          a.id === id
            ? { ...a, ...patch, updated_at: new Date().toISOString() }
            : a
        ),
      }
  )
}
