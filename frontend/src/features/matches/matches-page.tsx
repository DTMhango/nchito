import { useState } from "react"
import { Inbox, MousePointerClick } from "lucide-react"
import { FilterChip, type FilterState } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { KeyHint } from "@/components/key-hint"
import { SplitView } from "@/components/split-view"
import { View } from "@/components/view"
import { cn } from "@/lib/utils"

const TABS = [
  { id: "new", label: "New" },
  { id: "shortlisted", label: "Shortlisted" },
  { id: "below", label: "Below threshold" },
  { id: "archived", label: "Archived" },
] as const
type Tab = (typeof TABS)[number]["id"]

/** Starter facet chips (DESIGN 6.1). Values come from the condition engine in wave 1. */
const FACETS = [
  {
    id: "sponsorship",
    facet: "Visa sponsorship",
    label: "Sponsorship offered",
  },
  {
    id: "relocation",
    facet: "Relocation required",
    label: "Relocation required",
  },
  { id: "remote", facet: "Remote scope", label: "Remote worldwide" },
  { id: "pay", facet: "Pay", label: "Pay stated" },
  { id: "pay-not-stated", facet: "Pay", label: "Pay not stated" },
]

const KEYS: [string, string][] = [
  ["J K", "Move through the list"],
  ["T", "Tailor documents"],
  ["A", "Approve and apply"],
  ["S", "Skip"],
  ["Z", "Snooze"],
  ["P", "Pin"],
]

/** Matches: inbox-style triage, list on the left and the role on the right (DESIGN 10.3). */
export function MatchesPage() {
  const [tab, setTab] = useState<Tab>("new")
  const [filters, setFilters] = useState<Record<string, FilterState>>({})
  const [showDetail, setShowDetail] = useState(false)

  const list = (
    <>
      <div
        role="tablist"
        aria-label="Match lists"
        className="flex [scrollbar-width:none] gap-0.5 overflow-x-auto border-b border-border pt-3 pr-3 md:pl-5.5"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 border-transparent px-2.5 pt-2 pb-2.5 text-[0.88rem] font-semibold whitespace-nowrap text-muted-foreground hover:text-foreground",
              "aria-selected:border-primary aria-selected:text-foreground"
            )}
          >
            {t.label}
            {t.id !== "archived" && (
              <span className="num text-xs font-medium text-faint">0</span>
            )}
          </button>
        ))}
      </div>
      <div
        className="flex flex-wrap gap-1.5 border-b border-border py-2.5 md:pl-5.5"
        role="group"
        aria-label="Filters"
      >
        {FACETS.map((f) => (
          <FilterChip
            key={f.id}
            facet={f.facet}
            label={f.label}
            state={filters[f.id] ?? "off"}
            onStateChange={(s) =>
              setFilters((prev) => ({ ...prev, [f.id]: s }))
            }
          />
        ))}
      </div>
      <div
        role="tabpanel"
        aria-label={TABS.find((t) => t.id === tab)?.label}
        className="min-h-0 flex-1 overflow-auto md:pl-3"
      >
        <EmptyState
          icon={Inbox}
          title={tab === "new" ? "No new matches yet" : "Nothing in this list"}
          description={
            tab === "new"
              ? "Roles from each sweep land here, scored and sorted, with pay, location and deadline at a glance. Add one now with Add job, or set up a campaign to start sweeping."
              : "Roles move here as you triage. Filters with a tick include a value, a dash excludes it, and Not stated counts as a value too."
          }
        />
      </div>
    </>
  )

  const detail = (
    <div className="max-w-[640px]">
      <EmptyState
        icon={MousePointerClick}
        title="Pick a role to see why it scored the way it did"
        description="The detail shows the score breakdown per criterion with evidence, hard-filter results, why it fits, the gaps, the requirement table and the posting text."
        className="items-start text-left [&_[data-slot=empty-header]]:items-start [&_[data-slot=empty-header]]:text-left"
      />
      <div className="mt-2 px-4">
        <div className="mb-2 eyebrow">Keys</div>
        <dl className="grid max-w-[360px] grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 text-sm">
          {KEYS.map(([k, d]) => (
            <div key={k} className="contents">
              <dt>
                <KeyHint keys={k.split(" ")} />
              </dt>
              <dd className="text-muted-foreground">{d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )

  return (
    <View flush>
      <SplitView
        list={list}
        detail={detail}
        showDetail={showDetail}
        onBack={() => setShowDetail(false)}
        listLabel="Matches"
        backLabel="All matches"
      />
    </View>
  )
}
