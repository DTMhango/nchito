import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Bookmark,
  BookmarkPlus,
  MoreHorizontal,
  Save,
  Settings2,
  Tags,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import {
  addCampaignRule,
  campaignsQuery,
  createView,
  deleteView,
  mkeys,
  previewCampaignRule,
  updateView,
  viewsQuery,
} from "./api"
import {
  sameView,
  summarise,
  viewBody,
  viewStateFromBody,
  type ViewState,
} from "./filters"
import { plural } from "./format"
import type {
  CampaignRuleIn,
  ConditionSet,
  FacetCatalogEntry,
  SavedViewOut,
} from "./types"

const errText = (e: unknown, fallback: string) =>
  e instanceof Error ? e.message : fallback

// ---- the rail ----------------------------------------------------------------------------------

type ViewsRailProps = {
  activeViewId?: string
  onApply: (view: SavedViewOut) => void
  onManageTags: () => void
  onUseAsRule: (view: SavedViewOut) => void
  catalog: FacetCatalogEntry[]
  className?: string
}

/** Saved views pinned beside the list, each with a live count (DESIGN 6.1). */
export function ViewsRail({
  activeViewId,
  onApply,
  onManageTags,
  onUseAsRule,
  catalog,
  className,
}: ViewsRailProps) {
  const views = useQuery(viewsQuery())
  const items = views.data?.items ?? []
  const pinned = items.filter((v) => v.pinned)
  const others = items.filter((v) => !v.pinned)
  return (
    <nav
      aria-label="Saved views"
      className={cn(
        "flex min-h-0 flex-col gap-3 overflow-y-auto border-r border-border py-4 pr-2",
        className
      )}
    >
      <div className="flex items-center gap-2 px-2">
        <Bookmark className="size-4 text-faint" aria-hidden="true" />
        <h2 className="eyebrow">Saved views</h2>
      </div>
      {views.isLoading ? (
        <p className="px-2 text-sm text-faint">Loading…</p>
      ) : items.length === 0 ? (
        <p className="px-2 text-sm text-muted-foreground">
          Filter the list, then Save view to keep it here with a live count.
        </p>
      ) : (
        <ViewList
          views={pinned}
          activeViewId={activeViewId}
          onApply={onApply}
          onUseAsRule={onUseAsRule}
          catalog={catalog}
        />
      )}
      {others.length > 0 && (
        <>
          <h3 className="mt-2 px-2 eyebrow">Other views</h3>
          <ViewList
            views={others}
            activeViewId={activeViewId}
            onApply={onApply}
            onUseAsRule={onUseAsRule}
            catalog={catalog}
          />
        </>
      )}
      <div className="mt-auto px-1 pt-2">
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start"
          onClick={onManageTags}
        >
          <Tags data-icon="inline-start" aria-hidden="true" />
          Rule tags and questions
        </Button>
      </div>
    </nav>
  )
}

function ViewList({
  views,
  activeViewId,
  onApply,
  onUseAsRule,
  catalog,
}: {
  views: SavedViewOut[]
  activeViewId?: string
  onApply: (v: SavedViewOut) => void
  onUseAsRule: (v: SavedViewOut) => void
  catalog: FacetCatalogEntry[]
}) {
  return (
    <ul className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-px">
      {views.map((v) => (
        <ViewItem
          key={v.id}
          view={v}
          active={v.id === activeViewId}
          onApply={onApply}
          onUseAsRule={onUseAsRule}
          catalog={catalog}
        />
      ))}
    </ul>
  )
}

function ViewItem({
  view,
  active,
  onApply,
  onUseAsRule,
  catalog,
}: {
  view: SavedViewOut
  active: boolean
  onApply: (v: SavedViewOut) => void
  onUseAsRule: (v: SavedViewOut) => void
  catalog: FacetCatalogEntry[]
}) {
  const qc = useQueryClient()
  const [renaming, setRenaming] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const save = useMutation({
    mutationFn: (patch: Partial<SavedViewOut>) =>
      updateView(view.id, {
        name: patch.name ?? view.name,
        body: view.body as never,
        pinned: patch.pinned ?? view.pinned,
        sort_order: view.sort_order,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: mkeys.views }),
    onError: (e) => toast.error(errText(e, "Could not save the view.")),
  })
  const del = useMutation({
    mutationFn: () => deleteView(view.id),
    onSuccess: () => {
      toast.success(`Deleted “${view.name}”`)
      void qc.invalidateQueries({ queryKey: mkeys.views })
    },
    onError: (e) => toast.error(errText(e, "Could not delete the view.")),
  })
  const summary = summarise(viewStateFromBody(view.body as never), catalog)
  return (
    <li className="group/view relative">
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        onClick={() => onApply(view)}
        title={summary || undefined}
        className={cn(
          "flex w-full items-center gap-2 rounded-md py-1.5 pr-8 pl-2 text-left text-sm hover:bg-sunken",
          active &&
            "bg-primary-soft font-semibold text-primary-ink hover:bg-primary-soft"
        )}
      >
        <span className="min-w-0 flex-1 truncate">{view.name}</span>
        <span
          className="num text-xs text-faint"
          aria-label={`${view.count ?? 0} jobs`}
        >
          {view.count ?? "–"}
        </span>
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Actions for ${view.name}`}
            className="absolute top-1/2 right-1 -translate-y-1/2 opacity-0 group-hover/view:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100"
          >
            <MoreHorizontal aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onSelect={() => setRenaming(true)}>
            Rename…
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => save.mutate({ pinned: !view.pinned })}
          >
            {view.pinned ? "Unpin" : "Pin to the rail"}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onUseAsRule(view)}>
            Use as campaign rule…
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => setConfirmDelete(true)}
          >
            Delete…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <NameDialog
        key={`rename-${renaming}`}
        open={renaming}
        onOpenChange={setRenaming}
        title="Rename view"
        initial={view.name}
        submitLabel="Rename"
        onSubmit={(name) => save.mutateAsync({ name })}
      />
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle className="heading text-md">
              Delete “{view.name}”?
            </DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">
              Only the saved view goes. No job changes, and any campaign rule
              made from it stays.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              Keep it
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirmDelete(false)
                del.mutate()
              }}
            >
              Delete view
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  )
}

// ---- save / update -----------------------------------------------------------------------------

/** "Save view" and, when a saved view is open and changed, "Update view". */
export function ViewActions({
  state,
  activeView,
  onSaved,
}: {
  state: ViewState
  activeView: SavedViewOut | undefined
  onSaved: (view: SavedViewOut) => void
}) {
  const qc = useQueryClient()
  const [naming, setNaming] = useState(false)
  const changed =
    !!activeView &&
    !sameView(state, viewStateFromBody(activeView.body as never))
  const create = useMutation({
    mutationFn: (name: string) =>
      createView({ name, body: viewBody(state), pinned: true, sort_order: 0 }),
    onSuccess: (v) => {
      toast.success(`Saved “${v.name}”`)
      void qc.invalidateQueries({ queryKey: mkeys.views })
      onSaved(v)
    },
  })
  const update = useMutation({
    mutationFn: () =>
      updateView(activeView!.id, {
        name: activeView!.name,
        body: viewBody(state),
        pinned: activeView!.pinned,
        sort_order: activeView!.sort_order,
      }),
    onSuccess: (v) => {
      toast.success(`Updated “${v.name}”`)
      void qc.invalidateQueries({ queryKey: mkeys.views })
    },
    onError: (e) => toast.error(errText(e, "Could not update the view.")),
  })
  const empty = !state.f && !state.r && !state.q?.trim() && !state.g
  return (
    <>
      {changed && (
        <Button variant="outline" size="xs" onClick={() => update.mutate()}>
          <Save data-icon="inline-start" aria-hidden="true" />
          Update “{activeView.name}”
        </Button>
      )}
      {!empty && (!activeView || changed) && (
        <Button variant="ghost" size="xs" onClick={() => setNaming(true)}>
          <BookmarkPlus data-icon="inline-start" aria-hidden="true" />
          Save view
        </Button>
      )}
      <NameDialog
        key={`save-${naming}`}
        open={naming}
        onOpenChange={setNaming}
        title="Save this view"
        description="The filter, grouping and sort are kept under this name, pinned beside the list with a live count. A view only changes what you see; it never hides a job from the pipeline."
        submitLabel="Save view"
        onSubmit={(name) => create.mutateAsync(name)}
      />
    </>
  )
}

function NameDialog({
  open,
  onOpenChange,
  title,
  description,
  initial = "",
  submitLabel,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description?: string
  initial?: string
  submitLabel: string
  onSubmit: (name: string) => Promise<unknown>
}) {
  const id = useId()
  const [name, setName] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">{title}</DialogTitle>
          {description && (
            <DialogDescription className="text-sm text-muted-foreground">
              {description}
            </DialogDescription>
          )}
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!name.trim()) return setError("Give the view a name.")
            try {
              await onSubmit(name.trim())
              onOpenChange(false)
            } catch (err) {
              setError(errText(err, "Could not save."))
            }
          }}
        >
          <div className="grid gap-1.5">
            <label htmlFor={id} className="eyebrow">
              Name
            </label>
            <Input
              id={id}
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={!!error || undefined}
              placeholder="Relocation, sponsorship offered"
            />
            {error && <p className="text-sm text-danger">{error}</p>}
          </div>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit">{submitLabel}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---- use as campaign rule ------------------------------------------------------------------------

const EFFECTS: { id: CampaignRuleIn["effect"]; label: string; hint: string }[] =
  [
    {
      id: "exclude",
      label: "Exclusion",
      hint: "Matching roles are never applied to.",
    },
    {
      id: "include",
      label: "Inclusion",
      hint: "Only matching roles go ahead.",
    },
    { id: "penalty", label: "Penalty", hint: "Matching roles lose points." },
    { id: "bonus", label: "Bonus", hint: "Matching roles gain points." },
  ]

/** Copy a view's filter into a campaign as a hard rule or a score adjustment (DESIGN 6.1). */
export function CampaignRuleDialog({
  open,
  onOpenChange,
  name,
  conditions,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  name: string
  conditions: ConditionSet
}) {
  const campaigns = useQuery({ ...campaignsQuery(), enabled: open })
  const [campaignId, setCampaignId] = useState<string>("")
  const [effect, setEffect] = useState<CampaignRuleIn["effect"]>("exclude")
  const [points, setPoints] = useState<string>("")
  const list = campaigns.data?.items ?? []
  const chosen = campaignId || list[0]?.id || ""
  const preview = useQuery({
    queryKey: ["matches", "rule-preview", chosen, conditions],
    queryFn: () => previewCampaignRule(chosen, conditions),
    enabled: open && !!chosen,
  })
  const needsPoints = effect === "penalty" || effect === "bonus"
  const pts = Number(points)
  const pointsOk =
    !needsPoints || (Number.isInteger(pts) && pts >= 1 && pts <= 100)
  const add = useMutation({
    mutationFn: () =>
      addCampaignRule(chosen, {
        effect,
        conditions: conditions as never,
        points: needsPoints ? pts : null,
        reason: `From the saved view “${name}”`,
      }),
    onSuccess: () => {
      const c = list.find((x) => x.id === chosen)
      toast.success(
        `Added to ${c?.name ?? "the campaign"} as ${effect === "include" ? "an inclusion" : `a ${effect === "exclude" ? "exclusion" : effect}`}`
      )
      onOpenChange(false)
    },
    onError: (e) => toast.error(errText(e, "Could not add the rule.")),
  })
  const effId = useId()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            Use “{name}” as a campaign rule
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            The view stays as it is. The campaign gets a copy of the same
            filter, and from then on it decides what the pipeline does.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-1.5">
          <label htmlFor={`${effId}-c`} className="eyebrow">
            Campaign
          </label>
          <select
            id={`${effId}-c`}
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
            value={chosen}
            onChange={(e) => setCampaignId(e.target.value)}
          >
            {list.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {campaigns.isError && (
            <p className="text-sm text-danger">
              Campaigns could not be loaded.
            </p>
          )}
        </div>
        <fieldset className="grid gap-1.5">
          <legend className="mb-1.5 eyebrow">As</legend>
          <div className="grid grid-cols-2 gap-2">
            {EFFECTS.map((e) => (
              <label
                key={e.id}
                className={cn(
                  "grid cursor-pointer gap-0.5 rounded-md border border-border p-2.5 text-sm has-checked:border-primary has-checked:bg-primary-soft"
                )}
              >
                <span className="flex items-center gap-2 font-semibold">
                  <input
                    type="radio"
                    name={`${effId}-effect`}
                    value={e.id}
                    checked={effect === e.id}
                    onChange={() => setEffect(e.id)}
                    className="accent-primary"
                  />
                  {e.label}
                </span>
                <span className="text-xs text-muted-foreground">{e.hint}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {needsPoints && (
          <div className="grid gap-1.5">
            <label htmlFor={`${effId}-p`} className="eyebrow">
              Points (1 to 100)
            </label>
            <Input
              id={`${effId}-p`}
              type="number"
              inputMode="numeric"
              min={1}
              max={100}
              className="w-28"
              value={points}
              onChange={(e) => setPoints(e.target.value)}
              aria-invalid={(!!points && !pointsOk) || undefined}
            />
          </div>
        )}
        <p className="rounded-sm bg-sunken p-3 text-sm" aria-live="polite">
          {preview.isLoading
            ? "Counting the saved jobs it would affect…"
            : preview.data
              ? `It would affect ${plural(preview.data.matched, "saved job")} of ${preview.data.total}.`
              : preview.isError
                ? "The preview is not available yet."
                : "Choose a campaign to see how many saved jobs it would affect."}
        </p>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={
              !chosen || !pointsOk || (needsPoints && !points) || add.isPending
            }
            onClick={() => add.mutate()}
          >
            <Settings2 data-icon="inline-start" aria-hidden="true" />
            Add rule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
