import { recheckSummary } from "@/features/jobs/recheck"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  Bookmark,
  Inbox,
  Keyboard,
  MousePointerClick,
} from "lucide-react"
import { toast } from "sonner"
import { EmptyState } from "@/components/empty-state"
import { SplitView } from "@/components/split-view"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { View } from "@/components/view"
import { cn } from "@/lib/utils"
import {
  facetCatalogQuery,
  invalidateJobs,
  isNotBuilt,
  jobQuery,
  mkeys,
  patchJob,
  recheckJob,
  viewsQuery,
} from "./api"
import { BulkDialog } from "@/features/bulk/bulk-dialog"
import type { BulkAction } from "@/features/bulk/api"
import { useEmployerChips } from "@/features/employers/api"
import { BulkBar, RescoreDialog, type BulkKind } from "./bulk"
import { CorrectionDialog, type Correction } from "./corrections"
import { FilterBar } from "./filter-bar"
import {
  TABS,
  toConditionSet,
  viewStateFromBody,
  type MatchesSearch,
  type TabId,
} from "./filters"
import { JobDetailPane, type DetailActions } from "./job-detail"
import { JobList, type JobListHandle } from "./job-list"
import { ShortcutSheet, useMatchesKeys } from "./shortcuts"
import { TagsManager } from "./tags-manager"
import type { JobPatch, SavedViewOut } from "./types"
import { listParams, useJobList, useTabCounts } from "./use-job-list"
import { CampaignRuleDialog, ViewActions, ViewsRail } from "./views"

export type MatchesPageProps = {
  search: MatchesSearch
  onSearch: (next: MatchesSearch, opts?: { replace?: boolean }) => void
}

const PHONE = "(max-width: 767px)"
function useIsPhone() {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE).matches)
  useEffect(() => {
    const mq = window.matchMedia(PHONE)
    const on = () => setPhone(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return phone
}

const WAVE_2 = {
  tailor:
    "Tailoring arrives in wave 2. Shortlist the role now and it will be first in line.",
  apply:
    "Applying from Nchito arrives in wave 2. If you apply yourself, use More, then I applied myself.",
}

/** Matches: inbox triage with filters, saved views, bulk actions and the role on the right. */
export function MatchesPage({ search, onSearch }: MatchesPageProps) {
  const qc = useQueryClient()
  const isPhone = useIsPhone()
  const catalog = useQuery(facetCatalogQuery()).data ?? []
  const views = useQuery(viewsQuery()).data?.items ?? []
  const activeView = views.find((v) => v.id === search.view)
  const counts = useTabCounts(search)
  const list = useJobList(search)

  const update = useCallback(
    (patch: Partial<MatchesSearch>, replace = false) =>
      onSearch({ ...search, ...patch }, { replace }),
    [onSearch, search]
  )

  // ---- selection ----
  const jobIds = useMemo(() => {
    const seen = new Set<string>()
    const ids: string[] = []
    for (const r of list.rows)
      if (r.kind === "job" && !seen.has(r.job.id)) {
        seen.add(r.job.id)
        ids.push(r.job.id)
      }
    return ids
  }, [list.rows])
  const chips = useEmployerChips(jobIds)
  const selectedId = search.job ?? (isPhone ? null : (jobIds[0] ?? null))
  const listRef = useRef<JobListHandle>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const open = useCallback(
    (id: string) => update({ job: id }, !isPhone),
    [update, isPhone]
  )
  const move = (delta: number) => {
    if (!jobIds.length) return
    const i = selectedId ? jobIds.indexOf(selectedId) : -1
    const next = jobIds[Math.max(0, Math.min(jobIds.length - 1, i + delta))]
    if (next && next !== selectedId) {
      update({ job: next }, true)
      listRef.current?.scrollToJob(next)
    }
  }

  // ---- bulk selection ----
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const anchor = useRef<string | null>(null)
  const toggle = useCallback(
    (id: string, range: boolean) => {
      setChecked((prev) => {
        const next = new Set(prev)
        if (range && anchor.current) {
          const a = jobIds.indexOf(anchor.current)
          const b = jobIds.indexOf(id)
          if (a >= 0 && b >= 0) {
            for (const x of jobIds.slice(Math.min(a, b), Math.max(a, b) + 1))
              next.add(x)
            return next
          }
        }
        if (next.has(id)) next.delete(id)
        else next.add(id)
        anchor.current = id
        return next
      })
    },
    [jobIds]
  )
  const [bulk, setBulk] = useState<BulkKind | null>(null)

  // ---- dialogs ----
  const [snoozeOpen, setSnoozeOpen] = useState(false)
  const [keysOpen, setKeysOpen] = useState(false)
  const [tagsOpen, setTagsOpen] = useState(false)
  const [ruleView, setRuleView] = useState<SavedViewOut | null>(null)
  const [correction, setCorrection] = useState<Correction | null>(null)

  // ---- actions on the open role ----
  const patch = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string
      body: JobPatch
      message: string
      nextId?: string | null
    }) => patchJob(id, body),
    onSuccess: (data, { id, message, nextId }) => {
      qc.setQueryData(mkeys.job(id), data)
      invalidateJobs(qc, id)
      toast.success(message)
      if (nextId !== undefined) update({ job: nextId ?? undefined }, true)
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "That did not save."),
  })
  const recheck = useMutation({
    mutationFn: (id: string) => recheckJob(id),
    onSuccess: (r, id) => {
      invalidateJobs(qc, id)
      toast.success(recheckSummary(r))
    },
    onError: (e) =>
      toast.error(
        isNotBuilt(e)
          ? "Rechecking arrives with the sweep runner."
          : "Recheck failed."
      ),
  })

  const current = useQuery({
    ...jobQuery(selectedId ?? ""),
    enabled: !!selectedId,
  }).data
  const label = current ? `${current.title}, ${current.employer}` : "the role"
  const nextAfter = (id: string) => {
    const i = jobIds.indexOf(id)
    return jobIds[i + 1] ?? jobIds[i - 1] ?? null
  }
  const actions: DetailActions = {
    tailor: () => toast.info(WAVE_2.tailor),
    apply: () => toast.info(WAVE_2.apply),
    skip: () =>
      selectedId &&
      patch.mutate({
        id: selectedId,
        body: { triage: "skipped" },
        message: `Skipped ${label}`,
        nextId: nextAfter(selectedId),
      }),
    snooze: (days) => {
      if (!selectedId) return
      const until = new Date(Date.now() + days * 86_400_000).toISOString()
      patch.mutate({
        id: selectedId,
        body: { snoozed_until: until },
        message: `Snoozed ${label}`,
        nextId: nextAfter(selectedId),
      })
    },
    pin: () =>
      selectedId &&
      patch.mutate({
        id: selectedId,
        body: { pinned: !current?.pinned },
        message: current?.pinned
          ? `Unpinned ${label}`
          : `Pinned ${label} to the top`,
      }),
    shortlist: () =>
      selectedId &&
      patch.mutate({
        id: selectedId,
        body: { triage: "shortlisted" },
        message: `Shortlisted ${label}`,
      }),
    archive: () =>
      selectedId &&
      patch.mutate({
        id: selectedId,
        body: { triage: "archived" },
        message: `Archived ${label}`,
        nextId: nextAfter(selectedId),
      }),
    appliedMyself: () => setCorrection("applied"),
    release: () => setCorrection("release"),
    recheck: () => selectedId && recheck.mutate(selectedId),
  }

  useMatchesKeys({
    j: () => move(1),
    k: () => move(-1),
    t: () => selectedId && actions.tailor(),
    a: () => selectedId && actions.apply(),
    s: () => selectedId && actions.skip(),
    z: () => selectedId && setSnoozeOpen(true),
    p: () => selectedId && actions.pin(),
    x: () => selectedId && toggle(selectedId, false),
    "/": () => searchRef.current?.focus(),
    "?": () => setKeysOpen(true),
    Enter: () => {
      if (isPhone && !search.job && jobIds[0]) open(jobIds[0])
    },
    Escape: () => {
      if (checked.size) setChecked(new Set())
      else if (isPhone && search.job) update({ job: undefined })
    },
  })

  const applyView = (v: SavedViewOut) => {
    onSearch({
      tab: search.tab,
      ...viewStateFromBody(v.body as never),
      view: v.id,
    })
    setChecked(new Set())
  }

  const viewState = {
    q: search.q,
    f: search.f,
    r: search.r,
    g: search.g,
    sort: search.sort,
  }
  const groupLabel = catalog.find((c) => c.facet === search.g)?.label
  const showDetail = isPhone && !!search.job

  // ---- list column ----
  const listCol = (
    <>
      <div className="flex items-end border-b border-border pt-3 pr-3 md:pl-5.5">
        <div
          role="tablist"
          aria-label="Match lists"
          className="flex min-w-0 flex-1 [scrollbar-width:none] gap-0.5 overflow-x-auto [mask-image:linear-gradient(to_left,transparent,black_20px)] pr-4"
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={search.tab === t.id}
              onClick={() => {
                update({ tab: t.id as TabId, job: undefined })
                setChecked(new Set())
              }}
              className={cn(
                "-mb-px inline-flex items-center gap-1.5 border-b-2 border-transparent px-2 pt-2 pb-2.5 text-sm font-semibold whitespace-nowrap text-muted-foreground hover:text-foreground",
                "aria-selected:border-primary aria-selected:text-foreground"
              )}
            >
              {t.label}
              <span className="num text-xs font-medium text-faint">
                {counts[t.id] ?? ""}
              </span>
            </button>
          ))}
        </div>
      </div>
      {checked.size > 0 && (
        <BulkBar
          ids={[...checked]}
          onClear={() => setChecked(new Set())}
          onAction={setBulk}
        />
      )}
      <div
        role="tabpanel"
        aria-label={TABS.find((t) => t.id === search.tab)?.label}
        className="flex min-h-0 flex-1 flex-col"
      >
        {list.isError ? (
          <EmptyState
            icon={AlertTriangle}
            title={
              isNotBuilt(list.error)
                ? "Matches are not served yet"
                : "The list did not load"
            }
            description={
              isNotBuilt(list.error)
                ? "The jobs endpoint arrives with the wave 1 backend. In mock mode the list works now."
                : list.error instanceof Error
                  ? list.error.message
                  : "Try again in a moment."
            }
          />
        ) : !list.isLoading && list.rows.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title={
              search.f || search.r || search.q
                ? "Nothing matches this filter"
                : "Nothing in this list"
            }
            description={
              search.f || search.r || search.q
                ? "Loosen a filter or clear them all. Not stated counts as a value, so check whether it is excluded."
                : search.tab === "new"
                  ? "Roles from each sweep land here, scored and sorted. Add one now with Add job, or set up a campaign to start sweeping."
                  : "Roles move here as you triage."
            }
          />
        ) : (
          <JobList
            handle={listRef}
            rows={list.rows}
            selectedId={selectedId}
            checked={checked}
            chips={chips}
            onOpen={open}
            onToggle={toggle}
            onToggleGroup={list.toggleGroup}
            groupLabel={groupLabel}
            onEndReached={
              list.hasNextPage && !list.isFetchingNextPage
                ? () => void list.fetchNextPage()
                : undefined
            }
            footer={
              <p className="px-5.5 py-3.5 text-[0.84rem] text-faint">
                {list.isLoading
                  ? "Loading…"
                  : list.isFetchingNextPage
                    ? "Loading more…"
                    : list.total != null
                      ? `${list.total} ${list.total === 1 ? "role" : "roles"}${search.g ? ` in ${list.rows.filter((r) => r.kind === "group").length} groups` : ""}`
                      : ""}
              </p>
            }
          />
        )}
      </div>
    </>
  )

  const detailCol = selectedId ? (
    <JobDetailPane
      key={selectedId}
      id={selectedId}
      actions={actions}
      snoozeOpen={snoozeOpen}
      onSnoozeOpenChange={setSnoozeOpen}
    />
  ) : (
    <div className="max-w-[640px]">
      <EmptyState
        icon={MousePointerClick}
        title="Pick a role to see why it scored the way it did"
        description="The detail shows the score per criterion with evidence, hard-filter results, why it fits, the gaps, the requirements and the posting."
        className="items-start text-left [&_[data-slot=empty-header]]:items-start [&_[data-slot=empty-header]]:text-left"
      />
    </div>
  )

  return (
    <View flush>
      <div className="grid h-full min-h-0 xl:grid-cols-[220px_minmax(0,1fr)]">
        <ViewsRail
          className="max-xl:hidden"
          activeViewId={search.view}
          onApply={applyView}
          onManageTags={() => setTagsOpen(true)}
          onUseAsRule={setRuleView}
          catalog={catalog}
        />
        <div className="flex min-h-0 min-w-0 flex-col">
          <div className={cn(showDetail && "max-md:hidden")}>
            <FilterBar
              search={search}
              catalog={catalog}
              onChange={(p) => update({ ...p, job: undefined })}
              searchRef={searchRef}
              tools={
                <>
                  <ViewsMenu
                    views={views}
                    onApply={applyView}
                    onManageTags={() => setTagsOpen(true)}
                    activeViewId={search.view}
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="shrink-0 max-md:hidden"
                    aria-label="Keyboard shortcuts"
                    title="Keyboard shortcuts (?)"
                    onClick={() => setKeysOpen(true)}
                  >
                    <Keyboard aria-hidden="true" />
                  </Button>
                </>
              }
              viewActions={
                search.f || search.r || search.q || search.g || activeView ? (
                  <ViewActions
                    state={viewState}
                    activeView={activeView}
                    onSaved={(v) => update({ view: v.id }, true)}
                  />
                ) : undefined
              }
            />
          </div>
          <div className="min-h-0 flex-1">
            <SplitView
              list={listCol}
              detail={detailCol}
              showDetail={showDetail}
              onBack={() => update({ job: undefined })}
              listLabel="Matches"
              backLabel="All matches"
            />
          </div>
        </div>
      </div>

      <ShortcutSheet open={keysOpen} onOpenChange={setKeysOpen} />
      <TagsManager
        open={tagsOpen}
        onOpenChange={setTagsOpen}
        catalog={catalog}
      />
      <BulkDialog
        key={bulk && bulk !== "rescore" ? bulk : "closed"}
        open={!!bulk && bulk !== "rescore"}
        subject="jobs"
        scope={{
          ids: [...checked],
          view: {
            count: counts[search.tab] ?? null,
            selection: {
              conditions: JSON.stringify(listParams(search).conditions),
              q: search.q?.trim() || undefined,
            },
          },
        }}
        initialAction={
          bulk && bulk !== "rescore" && bulk !== "more"
            ? (bulk as BulkAction)
            : undefined
        }
        onOpenChange={(o) => !o && setBulk(null)}
        onDone={() => setChecked(new Set())}
      />
      <RescoreDialog
        key={bulk === "rescore" ? "open" : "closed"}
        open={bulk === "rescore"}
        ids={[...checked]}
        onOpenChange={(o) => !o && setBulk(null)}
        onDone={() => setChecked(new Set())}
      />
      <CampaignRuleDialog
        open={!!ruleView}
        onOpenChange={(o) => !o && setRuleView(null)}
        name={ruleView?.name ?? ""}
        conditions={
          ruleView
            ? toConditionSet(viewStateFromBody(ruleView.body as never), {
                withText: true,
              })
            : toConditionSet({})
        }
      />
      <CorrectionDialog
        key={`${correction}-${selectedId}`}
        kind={correction}
        jobId={selectedId}
        jobTitle={label}
        onOpenChange={(o) => !o && setCorrection(null)}
      />
    </View>
  )
}

/** Saved views for screens without the side rail. */
function ViewsMenu({
  views,
  onApply,
  onManageTags,
  activeViewId,
}: {
  views: SavedViewOut[]
  onApply: (v: SavedViewOut) => void
  onManageTags: () => void
  activeViewId?: string
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="xs" className="xl:hidden">
          <Bookmark data-icon="inline-start" aria-hidden="true" />
          Views
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[240px]">
        <DropdownMenuLabel>Saved views</DropdownMenuLabel>
        {views.map((v) => (
          <DropdownMenuItem
            key={v.id}
            onSelect={() => onApply(v)}
            className={cn(v.id === activeViewId && "font-semibold")}
          >
            <span className="min-w-0 flex-1 truncate">{v.name}</span>
            <span className="num text-xs text-faint">{v.count ?? ""}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onManageTags}>
          Rule tags and questions…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
